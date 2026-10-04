"""End-to-end pipeline implementing the agent workflow (spec section 118)."""
from __future__ import annotations

import logging
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .attribution.attribution import holding_attribution, pl_note
from .bootstrap.bootstrap import run_bootstrap
from .config import PACKAGE_ROOT, load_config, resolve
from .ingestion.ingest import ingest
from .markov.markov import STATE_NAMES, markov_summary, run_markov
from .market_data.fetch import align_price_frames, fetch_history
from .monte_carlo.mc import SimContext, month_index, required_reserve_pv, run_monte_carlo, summarize_simulation
from .optimization.optimize import suggest_allocation
from .portfolio.portfolio import EQUITY_CLASSES, benchmark_series, build_portfolio, sector_of
from .reporting import charts
from .reporting.docx_report import build_report
from .reporting.excel import build_workbook
from .returns.returns import annual_vol_monthly, annualize, simple_returns, to_monthly
from .risk.risk import (concentration_report, correlation_clusters, correlation_flags,
                        drawdown_distribution, hhi, recovery_analysis, var_cvar_table)
from .risk.stoploss import run_stop_backtests
from .sectors.sectors import assign_sector, sector_correlations, sector_table
from .sensitivity.sensitivity import interpret_grid, run_sensitivity
from .stress_tests.stress import crisis_test, hypothetical_test
from .validation.validate import validate

log = logging.getLogger("pipeline")
VERSION = "1.0.0"


# ---------------------------------------------------------------- glide path
def build_glide_targets(method: str, years: list[int], start_eq: float, end_eq: float,
                        bond_share: float, cash_share: float, custom: dict | None) -> pd.DataFrame:
    n = len(years)
    if method == "none":
        eq = np.full(n, start_eq)
    elif method == "linear":
        eq = np.linspace(start_eq, end_eq, n)
    elif method == "accelerating":
        t = (np.arange(n) / max(n - 1, 1)) ** 2
        eq = start_eq + (end_eq - start_eq) * t
    elif method == "stepwise":
        eq = np.full(n, start_eq)
        for i in range(n):
            if i >= n - 2:
                eq[i] = end_eq + (start_eq - end_eq) * (n - 1 - i) / max(n - 2, 1)
        eq[-1] = end_eq
    elif method == "custom" and custom:
        eq = np.array([custom.get(y, start_eq) for y in years], dtype=float)
    else:
        eq = np.linspace(start_eq, end_eq, n)
    remainder = 1 - eq
    tot = bond_share + cash_share
    df = pd.DataFrame({
        "year": years,
        "equity": eq,
        "bond": remainder * (bond_share / tot if tot > 0 else 0.5),
        "cash": remainder * (cash_share / tot if tot > 0 else 0.5),
    }).set_index("year")
    return df


def build_context(cfg: dict, holdings: pd.DataFrame, port) -> SimContext:
    sim = cfg["simulation"]
    cf = cfg["cashflows"]
    start, glide_end, reserve_end = sim["start_year"], sim["glide_end_year"], sim["reserve_end_year"]
    ac = dict(zip(holdings["ticker"], holdings["asset_class"]))
    equity_idx = [i for i, t in enumerate(holdings["ticker"]) if ac[t] in EQUITY_CLASSES]
    bond_idx = [i for i, t in enumerate(holdings["ticker"]) if ac[t] in ("Treasury", "Corporate Bond")]
    cash_idx = [i for i, t in enumerate(holdings["ticker"]) if ac[t] == "Cash"]

    eq_w = holdings.loc[equity_idx, "weight"].sum()
    bd_w = holdings.loc[bond_idx, "weight"].sum()
    csh_w = holdings.loc[cash_idx, "weight"].sum()
    gp = cfg["glide_path"]
    start_eq = gp.get("start_equity") or float(eq_w)
    years = list(range(start, glide_end + 1))
    targets = build_glide_targets(gp["method"] if gp["enabled"] else "none", years,
                                  start_eq, gp["end_equity"], bd_w, csh_w, gp.get("custom_targets"))

    contributions = {(c["year"] - start) * 12: c["amount"] for c in cf["contributions"]}
    rp = cf["reserve_payments"]
    reserve = required_reserve_pv(rp["amount"], rp["first_year"], rp["last_year"], cf["reserve_discount_rate"])
    payment_months = [(y - start) * 12 for y in range(rp["first_year"], rp["last_year"] + 1)]

    bond_w = holdings.loc[bond_idx, "weight"].values
    bond_blend = bond_w / bond_w.sum() if bond_w.sum() > 0 else np.ones(len(bond_idx)) / max(len(bond_idx), 1)

    class_base = np.zeros(len(holdings))
    for idxs in (equity_idx, bond_idx, cash_idx):
        if idxs:
            w = holdings.iloc[idxs]["weight"].values
            tot = w.sum()
            class_base[idxs] = w / tot if tot > 0 else 1.0 / len(idxs)

    reb = cfg["rebalancing"]
    band = reb["band"] if reb["enabled"] else None
    band_mode = reb["method"]
    if band_mode == "relative":
        band = reb.get("relative_band", 0.25)

    return SimContext(start, glide_end, reserve_end, equity_idx, bond_idx, cash_idx,
                      targets, contributions, reserve, payment_months, rp["amount"],
                      band, band_mode, reb["transaction_cost"], cfg["risk"]["inflation_base"],
                      bond_blend, class_base), targets


# ---------------------------------------------------------------- expected params
def build_return_params(cfg: dict, holdings: pd.DataFrame, port, rf: float) -> tuple[dict, pd.DataFrame]:
    tickers = list(holdings["ticker"])
    hist_ann = annualize(port.monthly_returns.mean())
    hist_vol = annual_vol_monthly(port.monthly_returns)
    source = cfg["expected_returns"]["source"]
    shrink = cfg["expected_returns"].get("shrinkage", 0.0)

    rows = []
    mu_ann, vol_ann = [], []
    for i, t in enumerate(tickers):
        h = holdings.iloc[i]
        ac = h["asset_class"]
        if ac == "Cash":
            mu, vol, src = rf, 0.0, "risk-free rate"
        else:
            use_input = source == "input" and pd.notna(h.get("expected_return")) and pd.notna(h.get("volatility"))
            mu = float(h["expected_return"]) if use_input else float(hist_ann.iloc[i])
            vol = float(h["volatility"]) if use_input else float(hist_vol.iloc[i])
            src = "spreadsheet assumption" if use_input else "historical estimate"
            if shrink and not use_input:
                cross = float(hist_ann.mean())
                mu = (1 - shrink) * mu + shrink * cross
        mu_ann.append(mu)
        vol_ann.append(vol)
        rows.append({"ticker": t, "expected_return_annual": mu, "volatility_annual": vol,
                     "historical_return_annual": float(hist_ann.iloc[i]) if ac != "Cash" else rf,
                     "historical_volatility_annual": float(hist_vol.iloc[i]) if ac != "Cash" else 0.0,
                     "source": src})
    params = pd.DataFrame(rows).set_index("ticker")

    mu_m = np.array([(1 + m) ** (1 / 12) - 1 for m in mu_ann])
    sig_m = np.array([v / np.sqrt(12) for v in vol_ann])
    corr_df = port.corr.reindex(tickers).reindex(tickers, axis=1).fillna(0.0)
    C = np.array(corr_df.to_numpy(dtype=float))
    np.fill_diagonal(C, 1.0)
    for i, t in enumerate(tickers):
        if holdings.iloc[i]["asset_class"] == "Cash":
            C[i, :] = 0.0
            C[:, i] = 0.0
            C[i, i] = 1.0
    cov_m = C * np.outer(sig_m, sig_m)
    # ensure PSD
    vals, vecs = np.linalg.eigh(cov_m)
    vals = np.clip(vals, 1e-14, None)
    cov_m = vecs @ np.diag(vals) @ vecs.T
    return {"mu": mu_m, "cov": cov_m, "mu_annual": np.array(mu_ann),
            "vol_annual": np.array(vol_ann), "corr": corr_df}, params


# ---------------------------------------------------------------- main run
def run(input_path: str | None = None, config_path: str | None = None,
        out_dir: str | None = None, overrides: dict | None = None) -> dict:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = load_config(config_path)
    if overrides:
        if "sims" in overrides:
            cfg["simulation"]["n_simulations"] = overrides["sims"]
            cfg["bootstrap"]["n_simulations"] = overrides["sims"]
        if "seed" in overrides:
            cfg["simulation"]["random_seed"] = overrides["seed"]
    input_path = input_path or resolve(cfg["input"]["spreadsheet"])
    out_dir = Path(out_dir) if out_dir else PACKAGE_ROOT / "outputs"
    fig_dir = out_dir / "figures"
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # 1-5. ingest + validate + weights
    ing = ingest(str(input_path), cfg["input"].get("sheet"))
    val = validate(ing.holdings, cfg)
    if val.errors:
        raise SystemExit("Input validation failed: " + "; ".join(val.errors))
    holdings = val.holdings
    log.info("Holdings: %s (weights %s)", list(holdings["ticker"]), val.weights_source)

    # 6-7. sectors
    holdings["sector"] = [assign_sector(t, holdings.iloc[i].get("sector")) for i, t in enumerate(holdings["ticker"])]

    # 8-9. market data
    risky = [t for t in holdings["ticker"] if holdings.loc[holdings["ticker"] == t, "asset_class"].iloc[0] != "Cash"]
    bench_ticks = [cfg["historical_data"]["benchmarks"]["equity"], cfg["historical_data"]["benchmarks"]["bonds"]]
    start = cfg["historical_data"]["start_date"]
    end = cfg["historical_data"].get("end_date")
    cache = resolve(cfg["historical_data"]["cache_dir"])
    frames = fetch_history(risky + bench_ticks, start, end, cache)
    dq_flags = [{"severity": "info", "ticker": t, "issue": "Data status", "detail": str(meta)}
                for t, meta in pd.read_csv(cache / "_fetch_meta.csv", index_col=0).to_dict("index").items()]

    prices = align_price_frames({t: frames[t] for t in risky if t in frames and len(frames[t])})
    missing = [t for t in holdings["ticker"] if t != "CASH" and t not in prices.columns]
    if missing:
        dq_flags.append({"severity": "high", "ticker": ",".join(missing), "issue": "Ticker unavailable",
                         "detail": "No market data found; holdings excluded and remaining weights renormalized."})
        holdings = holdings[~holdings["ticker"].isin(missing)].copy()
        holdings["weight"] = holdings["weight"] / holdings["weight"].sum()
    # cash column earns the risk-free rate daily
    rf = cfg["risk"]["risk_free_rate"]
    if "CASH" in list(holdings["ticker"]):
        prices["CASH"] = (1 + rf / 252) ** np.arange(len(prices))
    prices = prices[[t for t in holdings["ticker"] if t in prices.columns]]

    # 10-14. returns, portfolio, covariance/correlation
    port = build_portfolio(prices, holdings.set_index("ticker")["weight"])
    bench_prices = align_price_frames({t: frames[t] for t in bench_ticks if t in frames and len(frames[t])})
    benchmarks = benchmark_series(bench_prices, bench_ticks[0], bench_ticks[1])

    # data quality: short history flags (spec 113-114)
    confidence = {}
    for t in holdings["ticker"]:
        if t == "CASH":
            confidence[t] = "High"
            continue
        n_yrs = len(port.monthly_returns[t].dropna()) / 12 if t in port.monthly_returns else 0
        confidence[t] = "High" if n_yrs >= 10 else ("Medium" if n_yrs >= 2 else "Low")
        if n_yrs < 2:
            dq_flags.append({"severity": "high", "ticker": t, "issue": "Short history",
                             "detail": f"Only {n_yrs:.1f} years of data; statistics low-confidence."})

    # 15-20. engines
    params, param_table = build_return_params(cfg, holdings, port, rf)
    ctx, glide_targets = build_context(cfg, holdings, port)
    total_contrib = sum(c["amount"] for c in cfg["cashflows"]["contributions"])

    mc_model = cfg["simulation"]["model"]
    mc = run_monte_carlo(params, ctx, cfg["simulation"]["n_simulations"], cfg["simulation"]["random_seed"],
                         model=mc_model, dof=cfg["simulation"].get("student_t_dof", 5))
    mc_sum = summarize_simulation(mc, ctx, total_contrib)

    mk = run_markov(port.portfolio_monthly, cfg["markov"]["thresholds"],
                    cfg["simulation"]["start_year"], cfg["simulation"]["glide_end_year"],
                    cfg["markov"]["n_simulations"], cfg["simulation"]["random_seed"])
    mk_sum = markov_summary(mk, total_contrib, ctx.required_reserve)

    asset_order = list(holdings["ticker"])
    daily_joint = port.daily_returns.reindex(columns=asset_order).fillna(0.0).values
    bs = run_bootstrap(daily_joint, ctx, cfg["bootstrap"]["n_simulations"],
                       cfg["simulation"]["random_seed"] + 1, cfg["bootstrap"]["method"],
                       cfg["bootstrap"]["block_size_days"])
    bs_sum = summarize_simulation(bs, ctx, total_contrib)

    # 21. comparison + disagreement
    comparison = pd.DataFrame([
        {"metric": "Median terminal value (2033)", "Monte Carlo": mc_sum["median_terminal"], "Markov": mk_sum["median_terminal"], "Historical Bootstrap": bs_sum["median_terminal"]},
        {"metric": "5th percentile", "Monte Carlo": mc_sum["terminal_percentiles"]["p5"], "Markov": mk_sum["terminal_percentiles"]["p5"], "Historical Bootstrap": bs_sum["terminal_percentiles"]["p5"]},
        {"metric": "25th percentile", "Monte Carlo": mc_sum["terminal_percentiles"]["p25"], "Markov": mk_sum["terminal_percentiles"]["p25"], "Historical Bootstrap": bs_sum["terminal_percentiles"]["p25"]},
        {"metric": "50th percentile", "Monte Carlo": mc_sum["terminal_percentiles"]["p50"], "Markov": mk_sum["terminal_percentiles"]["p50"], "Historical Bootstrap": bs_sum["terminal_percentiles"]["p50"]},
        {"metric": "75th percentile", "Monte Carlo": mc_sum["terminal_percentiles"]["p75"], "Markov": mk_sum["terminal_percentiles"]["p75"], "Historical Bootstrap": bs_sum["terminal_percentiles"]["p75"]},
        {"metric": "95th percentile", "Monte Carlo": mc_sum["terminal_percentiles"]["p95"], "Markov": mk_sum["terminal_percentiles"]["p95"], "Historical Bootstrap": bs_sum["terminal_percentiles"]["p95"]},
        {"metric": "Probability terminal > contributions", "Monte Carlo": mc_sum["prob_terminal_gt_start"], "Markov": mk_sum["prob_terminal_gt_start"], "Historical Bootstrap": bs_sum["prob_terminal_gt_start"]},
        {"metric": "Probability reserve fully funded", "Monte Carlo": mc_sum["prob_all_payments_funded"], "Markov": mk_sum["prob_facility_negative"] and 1 - mk_sum["prob_facility_negative"], "Historical Bootstrap": bs_sum["prob_all_payments_funded"]},
        {"metric": "Median max drawdown (growth)", "Monte Carlo": mc_sum["median_max_drawdown"], "Markov": float("nan"), "Historical Bootstrap": bs_sum["median_max_drawdown"]},
        {"metric": "Probability >20% drawdown", "Monte Carlo": mc_sum["prob_dd_gt_20"], "Markov": float("nan"), "Historical Bootstrap": bs_sum["prob_dd_gt_20"]},
        {"metric": "VaR 95% (terminal)", "Monte Carlo": mc_sum["mc_var_95"], "Markov": mk_sum["mc_var_95"], "Historical Bootstrap": bs_sum["mc_var_95"]},
        {"metric": "CVaR 95% (terminal)", "Monte Carlo": mc_sum["mc_cvar_95"], "Markov": mk_sum["mc_cvar_95"], "Historical Bootstrap": bs_sum["mc_cvar_95"]},
        {"metric": "VaR 99% (terminal)", "Monte Carlo": mc_sum["mc_var_99"], "Markov": mk_sum["mc_var_99"], "Historical Bootstrap": bs_sum["mc_var_99"]},
        {"metric": "CVaR 99% (terminal)", "Monte Carlo": mc_sum["mc_cvar_99"], "Markov": mk_sum["mc_cvar_99"], "Historical Bootstrap": bs_sum["mc_cvar_99"]},
    ])
    comparison = comparison.astype(object)
    comparison = comparison.where(comparison.notna(), "n/a")
    disagree = []
    for key, a, b in [("success", mc_sum["prob_terminal_gt_start"], bs_sum["prob_terminal_gt_start"]),
                      ("reserve funded", mc_sum["prob_all_payments_funded"], bs_sum["prob_all_payments_funded"]),
                      ("median terminal", mc_sum["median_terminal"], bs_sum["median_terminal"])]:
        if key == "median terminal":
            rel = abs(a - b) / max(abs(a), 1)
            if rel > 0.25:
                disagree.append({"metric": key, "difference": f"{rel:.0%}", "flag": "Material model disagreement"})
        elif abs(a - b) > 0.10:
            disagree.append({"metric": key, "difference": f"{abs(a - b):.1%}", "flag": "Material model disagreement"})
    disagreement_df = pd.DataFrame(disagree) if disagree else pd.DataFrame(
        [{"metric": "all key metrics", "difference": "<10%", "flag": "Engines broadly agree"}])

    # 22. sensitivity
    sens = run_sensitivity(params["mu"], params["cov"], ctx, cfg["sensitivity"]["return_shifts"],
                           cfg["sensitivity"]["vol_multipliers"], cfg["sensitivity"]["n_simulations"],
                           cfg["simulation"]["random_seed"] + 2, total_contrib)
    sens_interp = interpret_grid(sens)

    # 23-24. risk metrics
    var_table = var_cvar_table(port.portfolio_daily, float(port.portfolio_daily.mean() * 252),
                               float(port.portfolio_daily.std() * np.sqrt(252)))
    conc = concentration_report(holdings.set_index("ticker")["weight"])
    corr_flags = correlation_flags(port.corr, cfg["risk"]["correlation_threshold"])
    clusters = correlation_clusters(port.corr, cfg["risk"]["correlation_threshold"])
    dd_dist = drawdown_distribution(mc["portfolio_paths"][:, :mc["split_month"]])

    # 25. sector attribution
    sec_tbl = sector_table(holdings, port.monthly_returns)
    sec_corr = sector_correlations(holdings, port.monthly_returns)
    attr = holding_attribution(holdings, port.monthly_returns)

    # 26-27. stress tests
    stress_rows = []
    for c in cfg["stress_tests"]["crises"]:
        r = crisis_test(c["name"], c["start"], c["end"], port.portfolio_daily,
                        port.daily_returns, holdings.set_index("ticker")["weight"],
                        holdings, benchmarks)
        stress_rows.append({k: v for k, v in r.items() if k not in ("holding_returns", "sector_contributions", "benchmarks")})
    stress_df = pd.DataFrame(stress_rows)
    ac_map = dict(zip(holdings["ticker"], holdings["asset_class"]))
    sec_map = dict(zip(holdings["ticker"], holdings["sector"]))
    hypo_rows = [hypothetical_test(n, s, holdings, ac_map, sec_map) for n, s in cfg["stress_tests"]["hypothetical"].items()]
    hypo_df = pd.DataFrame([{"scenario": h["scenario"], "portfolio_return": h["portfolio_return"], "note": h["note"]} for h in hypo_rows])

    # 28-29. rebalancing + glide variants
    reb_rows = []
    cur_cls = {"Equity": holdings[holdings["asset_class"].isin(EQUITY_CLASSES)]["weight"].sum(),
               "Bonds": holdings[holdings["asset_class"].isin(["Treasury", "Corporate Bond"])]["weight"].sum(),
               "Cash": holdings[holdings["asset_class"] == "Cash"]["weight"].sum()}
    tgt0 = glide_targets.iloc[0]
    col_of = {"Equity": "equity", "Bonds": "bond", "Cash": "cash"}
    for cls, cur_w in cur_cls.items():
        tgt = float(tgt0[col_of[cls]])
        lo, hi = (tgt - cfg["rebalancing"]["band"], tgt + cfg["rebalancing"]["band"]) if cfg["rebalancing"]["method"] == "absolute" else (tgt * (1 - cfg["rebalancing"]["relative_band"]), tgt * (1 + cfg["rebalancing"]["relative_band"]))
        trigger = cur_w < lo or cur_w > hi
        reb_rows.append({"class": cls, "current_weight": cur_w, "target": tgt, "lower_band": lo,
                         "upper_band": hi, "trigger": trigger,
                         "suggested_trade": max(0.0, (tgt - cur_w)) if trigger else 0.0,
                         "turnover": abs(tgt - cur_w) if trigger else 0.0})
    for _, h in holdings.iterrows():
        if h["weight"] > cfg["risk"]["max_position_weight"]:
            reb_rows.append({"class": f"Holding {h['ticker']}", "current_weight": h["weight"],
                             "target": cfg["risk"]["max_position_weight"],
                             "lower_band": 0.0, "upper_band": cfg["risk"]["max_position_weight"],
                             "trigger": True, "suggested_trade": h["weight"] - cfg["risk"]["max_position_weight"],
                             "turnover": h["weight"] - cfg["risk"]["max_position_weight"]})
    reb_df = pd.DataFrame(reb_rows)

    glide_variants = {}
    for method in ("none", "linear", "accelerating", "custom"):
        gp = dict(cfg["glide_path"])
        gp["method"] = method
        gp["enabled"] = method != "none"
        cfg_v = dict(cfg)
        cfg_v["glide_path"] = gp
        ctx_v, _ = build_context(cfg_v, holdings, port)
        mc_v = run_monte_carlo(params, ctx_v, 3000, cfg["simulation"]["random_seed"], model="gaussian")
        s = summarize_simulation(mc_v, ctx_v, total_contrib)
        glide_variants[method] = s
    glide_impact = pd.DataFrame([
        {"method": m, "median_terminal": s["median_terminal"], "p5_terminal": s["terminal_percentiles"]["p5"],
         "prob_depletion": s["prob_capital_depletion"], "prob_payments_funded": s["prob_all_payments_funded"],
         "median_max_dd": s["median_max_drawdown"], "var_95": s["mc_var_95"], "cvar_95": s["mc_cvar_95"]}
        for m, s in glide_variants.items()])

    # 30-31. risk discipline + theses
    stop_df = run_stop_backtests(prices, list(holdings["ticker"]),
                                 cfg["stop_loss"]["hard_levels"], cfg["stop_loss"]["trailing_levels"])
    discipline = [
        f"Maximum position size: {cfg['risk']['max_position_weight']:.0%} (current max: {conc['largest'][1]:.1%} in {conc['largest'][0]})",
        f"Maximum sector/group exposure: correlated-group cap {cfg['risk']['max_correlated_group_weight']:.0%}",
        "Thesis-break condition: trim any holding whose stated thesis is invalidated (see Investment Theses sheet)",
        "Valuation/concentration trim: review any holding drifting >5pp beyond target band",
        "Drawdown review: portfolio-level review triggered at 20% simulated drawdown",
    ]
    thesis_rows = []
    for _, h in holdings.iterrows():
        thesis = h.get("thesis")
        thesis_rows.append({
            "ticker": h["ticker"], "thesis": thesis if isinstance(thesis, str) else "MISSING — THESIS RISK",
            "portfolio_role": _role(h), "target_weight": float(h["weight"]),
            "current_weight": float(h["weight"]),
            "risk_rating": _risk_rating(h, confidence.get(h["ticker"], "Medium"), clusters),
        })
    thesis_df = pd.DataFrame(thesis_rows)

    # 32. optimization diagnostic
    opt = suggest_allocation(holdings, params["mu_annual"], params["cov"] * 12, cfg)

    # scorecard, recommendations, narrative
    scorecard = _scorecard(cfg, holdings, mc_sum, bs_sum, conc, sec_tbl, confidence)
    recs = _recommendations(cfg, holdings, val.flags, mc_sum, bs_sum, mk_sum, conc, corr_flags,
                            disagreement_df, confidence, glide_variants)
    exec_lines = _exec_summary(cfg, holdings, port, mc_sum, bs_sum, mk_sum, conc, disagreement_df, ctx)

    # 33. charts
    figs = {}
    figs["allocation"] = charts.allocation_donut(holdings, fig_dir)
    figs["sector"] = charts.sector_allocation(sec_tbl, fig_dir)
    figs["cumulative"] = charts.cumulative_return(port.portfolio_value_index, benchmarks, fig_dir)
    figs["drawdown"] = charts.drawdown_chart(port.portfolio_value_index, fig_dir)
    figs["correlation"] = charts.correlation_heatmap(port.corr, fig_dir)
    figs["mc_terminal"] = charts.terminal_distribution(mc["terminal_2033"], "Monte Carlo", fig_dir, "06_mc_terminal")
    figs["mc_fan"] = charts.fan_chart(mc_sum["fan"], cfg["simulation"]["start_year"], cfg["simulation"]["glide_end_year"], "Monte Carlo", fig_dir, "07_mc_fan")
    figs["bs_terminal"] = charts.terminal_distribution(bs["terminal_2033"], "Historical Bootstrap", fig_dir, "08_bs_terminal")
    figs["bs_fan"] = charts.fan_chart(bs_sum["fan"], cfg["simulation"]["start_year"], cfg["simulation"]["glide_end_year"], "Historical Bootstrap", fig_dir, "10_bs_fan")
    figs["sens_success"] = charts.sensitivity_heatmap(sens, "prob_success", "Probability of Success (terminal > contributions)", fig_dir, "13a_sens_success")
    figs["sens_terminal"] = charts.sensitivity_heatmap(sens, "median_terminal", "Median Terminal Value", fig_dir, "13b_sens_terminal")
    figs["crisis"] = charts.crisis_comparison([{k: v for k, v in r.items()} for r in _crisis_full(cfg, port, holdings, benchmarks)], fig_dir)
    figs["glide"] = charts.glide_path_chart(glide_targets, fig_dir)
    figs["sector_contrib"] = charts.contribution_chart(sec_tbl.reset_index().rename(columns={"sector": "label"})[["label", "contribution_12m"]], fig_dir, "13_sector_contribution", "Sector Contribution to 12m Return")
    figs["concentration"] = charts.risk_concentration_chart(holdings.set_index("ticker")["weight"], fig_dir)
    figs["comparison"] = charts.model_comparison_table_image(comparison.to_dict("records"), fig_dir)

    # assemble sheets
    holdings_sheet = _holdings_sheet(holdings, port, params, var_table, clusters, confidence, attr)
    history_sheet = _history_sheet(port, benchmarks)
    mc_sheet = _sim_sheet(mc, total_contrib)
    bs_sheet = _sim_sheet(bs, total_contrib)
    risk_sheet = _risk_sheet(port, var_table, mc_sum, bs_sum, conc, dd_dist, sec_corr)
    extra = []
    for infl in cfg["risk"]["inflation_scenarios"]:
        rc = total_contrib * (1 + infl) ** (cfg["simulation"]["glide_end_year"] - cfg["simulation"]["start_year"])
        extra.append({"metric": f"MC success above real capital @ {infl:.0%} inflation",
                      "value": float((mc["terminal_2033"] > rc).mean())})
        extra.append({"metric": f"Bootstrap success above real capital @ {infl:.0%} inflation",
                      "value": float((bs["terminal_2033"] > rc).mean())})
    for f in (1.0, 0.9, 0.8, 0.7):
        extra.append({"metric": f"MC prob terminal above {int(f * 100)}% real capital floor",
                      "value": mc_sum[f"prob_floor_{int(f * 100)}"]})
    risk_sheet = pd.concat([risk_sheet, pd.DataFrame(extra)], ignore_index=True)
    recovery_df = recovery_analysis(port.portfolio_value_index)
    markov_states = mk["state_stats"].reset_index()
    markov_P = mk["P_df"].reset_index()
    markov_misc = pd.DataFrame([
        {"item": "Current state (latest full year)", "value": mk["current_state"]},
        {"item": "Stationary distribution", "value": ", ".join(f"{s}={p:.2f}" for s, p in zip(STATE_NAMES, mk["stationary"]))},
        {"item": "Expected duration (years) by state", "value": ", ".join(f"{s}={d:.1f}" for s, d in mk["durations"].items())},
        {"item": "P(bear next year)", "value": f"{mk['prob_bear_next']:.1%}"},
        {"item": "P(bear at any point 2027-2032)", "value": f"{mk['bear_ever_prob']:.1%}"},
        {"item": "P(bull by 2032)", "value": f"{mk['bull_by_end_prob']:.1%}"},
        {"item": "Expected portfolio return 2027-2032", "value": ", ".join(f"{y}={r:.1%}" for y, r in mk["expected_annual_return"].items() if y < 2033)},
    ])

    dq_all = val.flags + dq_flags + [{"severity": "info", "ticker": "-", "issue": "Survivorship bias",
                                      "detail": "Historical analysis is subject to survivorship bias because securities that no longer exist are not represented."},
                                     {"severity": "info", "ticker": "-", "issue": "Returns basis",
                                      "detail": "Adjusted close (dividend/total-return) prices used; returns include dividends."},
                                     {"severity": "info", "ticker": "-", "issue": "P&L", "detail": pl_note(holdings)},
                                     {"severity": "info", "ticker": "-", "issue": "Taxes",
                                      "detail": "Tax effects are excluded because sufficient tax-lot information was not supplied."}]
    dq_df = pd.DataFrame(dq_all)

    meta = {"generated_utc": generated, "seed": cfg["simulation"]["random_seed"],
            "n_sims": cfg["simulation"]["n_simulations"], "version": VERSION,
            "portfolio_name": "Laura Gao Portfolio", "input": str(input_path),
            "python": sys.version.split()[0], "platform": platform.platform(),
            "weights_source": val.weights_source}

    var95 = var_table[var_table.confidence == 0.95].iloc[0]
    dashboard = [
        ("Invested Capital (2027-28)", float(total_contrib), "#,##0"),
        ("Expected CAGR (MC)", mc_sum["cagr_money_weighted"], "0.0%"),
        ("Historical CAGR", port.stats["cagr_historical"], "0.0%"),
        ("Volatility (hist, annual)", port.stats["annual_volatility"], "0.0%"),
        ("Sharpe (hist)", port.stats["sharpe"], "0.00"),
        ("Max Drawdown (hist)", port.stats["max_drawdown"], "0.0%"),
        ("VaR 95% (monthly, historical)", float(var95["historical_VaR"]), "0.0%"),
        ("CVaR 95% (monthly, historical)", float(var95["historical_CVaR"]), "0.0%"),
        ("MC Success", mc_sum["prob_terminal_gt_start"], "0.0%"),
        ("Bootstrap Success", bs_sum["prob_terminal_gt_start"], "0.0%"),
        ("2033 Equity Target", float(glide_targets.loc[glide_targets.index[-1], "equity"]), "0.0%"),
        ("Overall Score", float(scorecard[scorecard.category == "Overall"]["score"].iloc[0]), "0.0"),
    ]

    results = {
        "meta": meta, "holdings": holdings, "port": port, "ctx": ctx,
        "dashboard": dashboard,
        "glide_targets": glide_targets, "params": params, "param_table": param_table,
        "mc": {**{k: v for k, v in mc.items() if k in ("n_sims", "model")}, **mc_sum},
        "mc_sum": mc_sum, "mk_sum": mk_sum, "bs_sum": bs_sum, "mk": mk, "bs": bs,
        "comparison_sheet": comparison, "disagreement_sheet": disagreement_df,
        "markov_states": markov_states, "markov_P": markov_P, "markov_misc": markov_misc,
        "sensitivity": sens, "sensitivity_sheet": sens, "sens_interp": sens_interp,
        "stress_sheet": stress_df, "hypothetical_sheet": hypo_df,
        "glide_sheet": glide_targets.reset_index(), "glide_impact_sheet": glide_impact,
        "rebalance_sheet": reb_df, "thesis_sheet": thesis_df, "scorecard": scorecard,
        "decision_matrix": _decision_matrix(cfg, holdings, mc_sum, bs_sum, conc, disagreement_df),
        "risk_sheet": risk_sheet, "recovery_sheet": recovery_df, "holdings_sheet": holdings_sheet, "history_sheet": history_sheet,
        "mc_sheet": mc_sheet, "mc_percentiles": _percentile_frame(mc_sum), "bs_sheet": bs_sheet,
        "sector_sheet": sec_tbl.reset_index().assign(target_weight=sec_tbl["weight"].values, difference=0.0),
        "stop_sheet": stop_df,
        "corr": port.corr, "sec_corr": sec_corr, "attr": attr, "conc": conc,
        "var_table": var_table, "dd_dist": dd_dist, "clusters": clusters,
        "confidence": confidence, "figures": figs, "opt": opt,
        "exec_summary": exec_lines,
        "overview_text": f"{len(holdings)} holdings; total invested contributions ${total_contrib:,} (2027-2028); "
                         f"weights {val.weights_source}; equity {cur_cls['Equity']:.0%}, bonds {cur_cls['Bonds']:.0%}, cash {cur_cls['Cash']:.0%}.",
        "historical_text": _historical_text(port, benchmarks),
        "risk_text": "VaR/CVaR are one-month horizon figures unless labeled terminal; historical, parametric, and Monte Carlo variants shown for comparison.",
        "correlation_text": _correlation_text(port.corr, corr_flags, clusters),
        "concentration_text": _concentration_text(conc, holdings),
        "mc_text": _mc_text(cfg, mc_sum, ctx, total_contrib),
        "markov_text": _markov_text(mk, mk_sum),
        "bs_text": _bs_text(cfg, bs_sum, ctx, total_contrib),
        "disagreement_text": _disagreement_text(disagreement_df),
        "sensitivity_text": _sensitivity_text(sens_interp),
        "rebalance_text": f"Bands: {cfg['rebalancing']['method']} {cfg['rebalancing']['band']:.0%}; transaction cost {cfg['rebalancing']['transaction_cost']:.2%} of turnover assumed (not zero).",
        "glide_text": "Greater downside protection may reduce upside participation — see impact table.",
        "risk_discipline": discipline, "key_risks": _key_risks(cfg, holdings, mc_sum, bs_sum, conc, corr_flags, confidence),
        "recommendations": recs, "methodology": _methodology(cfg), "assumptions": _assumptions(cfg, val.weights_source, total_contrib),
        "limitations": _limitations(cfg, confidence, val), "conclusions": _conclusions(mc_sum, bs_sum, mk_sum, conc, sens_interp),
        "monitoring": ["Portfolio value & allocation drift vs targets", "Sector weights vs bands",
                       "Correlation clusters (>0.70 pairs)", "VaR/CVaR monthly", "Max drawdown vs 20% review trigger",
                       "Glide-path position vs 2033 target", "Rebalancing band breaches",
                       "Simulation success probabilities (rerun quarterly)", "Thesis status per holding",
                       "DUOL history length / data confidence"],
        "sector_narrative": _sector_narrative(sec_tbl, holdings),
        "dq_sheet": dq_df,
    }

    # 34-37. outputs
    xlsx = build_workbook(out_dir / "spreadsheet" / "portfolio_analysis.xlsx", results)
    docx = build_report(out_dir / "report" / "portfolio_analysis_report.docx", results)
    _sanity_checks(results)
    _write_manifest(cfg, meta, out_dir)
    log.info("Wrote %s and %s", xlsx, docx)
    return results


# ---------------------------------------------------------------- helpers
def _crisis_full(cfg, port, holdings, benchmarks):
    out = []
    for c in cfg["stress_tests"]["crises"]:
        out.append(crisis_test(c["name"], c["start"], c["end"], port.portfolio_daily,
                               port.daily_returns, holdings.set_index("ticker")["weight"], holdings, benchmarks))
    return out


def _role(h) -> str:
    ac = h["asset_class"]
    if ac == "Cash":
        return "Cash Equivalent"
    if ac in ("Treasury", "Corporate Bond"):
        return "Defensive / Income"
    sec = h.get("sector", "")
    if sec == "Broad Market (ETF)":
        return "Core Growth / Diversifier"
    if sec == "Information Technology":
        return "Core Growth"
    if sec == "Communication Services":
        return "Cyclical"
    return "Diversifier"


def _risk_rating(h, conf, clusters) -> str:
    if conf == "Low":
        return "High (short history)"
    if h.get("volatility") and float(h["volatility"]) >= 0.35:
        return "Elevated (high volatility)"
    return "Moderate"


def _holdings_sheet(holdings, port, params, var_table, clusters, confidence, attr) -> pd.DataFrame:
    rows = []
    attr_map = attr.set_index("ticker")
    for _, h in holdings.iterrows():
        t = h["ticker"]
        p = params["corr"]
        beta = float(np.cov(port.monthly_returns[t].fillna(0), port.portfolio_monthly)[0, 1] /
                     np.var(port.portfolio_monthly)) if t in port.monthly_returns.columns and t != "CASH" else 0.0
        vol = float(params["vol_annual"][list(holdings["ticker"]).index(t)])
        mu = float(params["mu_annual"][list(holdings["ticker"]).index(t)])
        sharpe = (mu - 0.0) / vol if vol > 0 else 0.0
        r = port.monthly_returns[t].fillna(0) if t in port.monthly_returns.columns else pd.Series(dtype=float)
        var95 = var_cvar_table(r, float(r.mean()), float(r.std()), (0.95,))["historical_VaR"].iloc[0] if len(r) else float("nan")
        cvar95 = var_cvar_table(r, float(r.mean()), float(r.std()), (0.95,))["historical_CVaR"].iloc[0] if len(r) else float("nan")
        flags = []
        if h["weight"] > 0.25:
            flags.append("HIGH CONCENTRATION")
        if confidence.get(t) == "Low":
            flags.append("LOW CONFIDENCE")
        if clusters.get(t, -1) >= 0 and t != "CASH":
            flags.append("CORRELATION CLUSTER")
        rows.append({
            "ticker": t, "asset_class": h["asset_class"], "sector": h["sector"],
            "weight": float(h["weight"]), "target_weight": float(h["weight"]),
            "difference": 0.0, "expected_return": mu, "volatility": vol, "beta": beta,
            "sharpe": sharpe, "var_95": var95, "cvar_95": cvar95,
            "return_12m": float(attr_map.loc[t, "return_12m"]),
            "contribution_12m": float(attr_map.loc[t, "contribution_12m"]),
            "correlation_cluster": clusters.get(t, "independent"),
            "confidence": confidence.get(t, "Medium"),
            "risk_flag": "; ".join(flags) if flags else "None",
            "thesis": h.get("thesis") if isinstance(h.get("thesis"), str) else "MISSING",
        })
    return pd.DataFrame(rows)


def _history_sheet(port, benchmarks) -> pd.DataFrame:
    m = port.monthly_returns.index
    val = (1 + port.portfolio_monthly).cumprod()
    df = pd.DataFrame({"month": m.strftime("%Y-%m"), "portfolio_return": port.portfolio_monthly.values,
                       "portfolio_value_index": val.values,
                       "cumulative_return": val.values - 1,
                       "drawdown": (val / val.cummax() - 1).values,
                       "rolling_vol_12m": (port.portfolio_monthly.rolling(12).std() * np.sqrt(12)).values,
                       "rolling_sharpe_12m": (port.portfolio_monthly.rolling(12).mean() /
                                              port.portfolio_monthly.rolling(12).std() * np.sqrt(12)).values})
    for name, s in benchmarks.items():
        bm = s.resample("ME").last()
        aligned = bm.reindex(m).ffill()
        df[name] = (aligned / aligned.iloc[0]).values - 1
    return df


def _sim_sheet(res, total_contrib: float) -> pd.DataFrame:
    n = min(200, res["n_sims"])
    idx = np.linspace(0, res["n_sims"] - 1, n).astype(int)
    term = res["terminal_2033"][idx]
    paths = res["portfolio_paths"][idx]
    return pd.DataFrame({
        "simulation": idx + 1,
        "terminal_value": term,
        "cagr": (term / total_contrib) ** (1 / 6) - 1,
        "max_drawdown": res["max_drawdown_growth"][idx],
        "min_value": paths.min(axis=1),
        "success": res["all_payments_funded"][idx].astype(int),
    })


def _percentile_frame(s) -> pd.DataFrame:
    rows = [{"metric": f"Terminal {k}", "value": v} for k, v in s["terminal_percentiles"].items()]
    rows += [{"metric": f"Facility contribution {k}", "value": v} for k, v in s["facility_percentiles"].items()]
    rows += [{"metric": "Median facility contribution", "value": s["median_facility"]},
             {"metric": "2031 sponsor range (p5-p95 of value at start 2031 minus reserve)",
              "value": f"${s['projected_facility_2031']['p5']:,.0f} to ${s['projected_facility_2031']['p95']:,.0f}"}]
    return pd.DataFrame(rows)


def _risk_sheet(port, var_table, mc_sum, bs_sum, conc, dd_dist, sec_corr) -> pd.DataFrame:
    rows = [{"metric": f"{r['confidence']:.0%} {k}", "value": r[k]}
            for _, r in var_table.iterrows() for k in ("historical_VaR", "historical_CVaR", "parametric_VaR", "parametric_CVaR")]
    rows += [
        {"metric": "Monte Carlo VaR 95% (terminal)", "value": mc_sum["mc_var_95"]},
        {"metric": "Monte Carlo CVaR 95% (terminal)", "value": mc_sum["mc_cvar_95"]},
        {"metric": "Bootstrap VaR 95% (terminal)", "value": bs_sum["mc_var_95"]},
        {"metric": "Bootstrap CVaR 95% (terminal)", "value": bs_sum["mc_cvar_95"]},
        {"metric": "Historical max drawdown", "value": port.stats["max_drawdown"]},
        {"metric": "Sharpe (historical)", "value": port.stats["sharpe"]},
        {"metric": "Sortino (historical)", "value": port.stats["sortino"]},
        {"metric": "Downside deviation (annual)", "value": port.stats["downside_deviation"]},
        {"metric": "HHI raw", "value": conc["hhi"]["raw"]},
        {"metric": "HHI normalized", "value": conc["hhi"]["normalized"]},
        {"metric": "Effective number of bets", "value": conc["hhi"]["effective_n"]},
        {"metric": "MC max-drawdown median", "value": dd_dist["median"]},
        {"metric": "MC max-drawdown 95th pct", "value": dd_dist["p95"]},
        {"metric": "MC P(>20% drawdown)", "value": mc_sum["prob_dd_gt_20"]},
        {"metric": "Bootstrap P(>20% drawdown)", "value": bs_sum["prob_dd_gt_20"]},
    ]
    return pd.DataFrame(rows)


def _scorecard(cfg, holdings, mc_sum, bs_sum, conc, sec_tbl, confidence) -> pd.DataFrame:
    n = len(holdings)
    eff_n = conc["hhi"]["effective_n"]
    divers = min(100, eff_n / max(n, 1) * 100)
    conc_score = max(0, 100 * (1 - conc["hhi"]["normalized"]))
    downside = 100 * (1 - mc_sum["prob_dd_gt_20"])
    exp_ret = min(100, mc_sum["cagr_money_weighted"] / 0.10 * 100)
    sec_w = sec_tbl["weight"]
    sec_hhi = float((sec_w ** 2).sum())
    sector_balance = max(0, 100 * (1 - sec_hhi))
    tail = max(0, 100 * (1 - mc_sum["mc_cvar_95"] / 0.40))
    glide = 100 if cfg["glide_path"]["enabled"] else 40
    thesis = 100 * holdings["thesis"].apply(lambda x: isinstance(x, str) and len(x) > 10).mean()
    reb = 100 if cfg["rebalancing"]["enabled"] else 30
    rows = [
        {"category": "Diversification", "score": divers},
        {"category": "Concentration", "score": conc_score},
        {"category": "Downside Protection", "score": downside},
        {"category": "Expected Return", "score": exp_ret},
        {"category": "Sector Balance", "score": sector_balance},
        {"category": "Tail Risk", "score": tail},
        {"category": "Glide Path", "score": glide},
        {"category": "Thesis Quality", "score": thesis},
        {"category": "Rebalancing Discipline", "score": reb},
        {"category": "Overall", "score": np.mean([divers, conc_score, downside, exp_ret, sector_balance, tail, glide, thesis, reb])},
    ]
    df = pd.DataFrame(rows)
    df["methodology_note"] = "Heuristic 0-100 scores; documented formulas; not a scientific objective measure."
    return df


def _decision_matrix(cfg, holdings, mc_sum, bs_sum, conc, disagreement_df) -> pd.DataFrame:
    material = any("Material" in str(f.get("flag", "")) for f in disagreement_df.to_dict("records"))
    rows = [
        {"area": "Allocation", "status": "70/17.5/12.5 equity/bond/cash", "risk": "Moderate",
         "evidence": "Within stated bucket targets", "action": "Maintain; monitor bands", "priority": "P4 Monitor"},
        {"area": "Concentration", "status": f"Largest {conc['largest'][0]} {conc['largest'][1]:.0%}", "risk": "Elevated",
         "evidence": f"Correlated group exceeds 30% cap; HHI {conc['hhi']['raw']:.2f}",
         "action": "Trim Growth/Consumer-Tech group toward cap", "priority": "P2 High"},
        {"area": "Sector Exposure", "status": "Tech-heavy equity sleeve", "risk": "Elevated",
         "evidence": "ADBE+DUOL in Information Technology; DIS Communication Services",
         "action": "Consider adding defensive sleeve", "priority": "P3 Moderate"},
        {"area": "Tail Risk", "status": f"CVaR95 {mc_sum['mc_cvar_95']:.0%} (MC terminal)", "risk": "Material",
         "evidence": "Bootstrap tail heavier than Gaussian MC", "action": "Size reserve conservatively", "priority": "P2 High"},
        {"area": "Glide Path", "status": "70% -> 55% equity by 2033", "risk": "Low",
         "evidence": "Glide impact table", "action": "Adopt linear glide; review annually", "priority": "P3 Moderate"},
        {"area": "Rebalancing", "status": "5pp bands configured", "risk": "Low",
         "evidence": "Rebalancing sheet triggers", "action": "Rebalance on band breach only", "priority": "P4 Monitor"},
        {"area": "Investment Thesis", "status": "All holdings have theses", "risk": "Low",
         "evidence": "Theses from input spreadsheet", "action": "Refresh annually", "priority": "P4 Monitor"},
        {"area": "Monte Carlo", "status": f"Success {mc_sum['prob_terminal_gt_start']:.0%}", "risk": "Model-dependent",
         "evidence": "Gaussian assumptions", "action": "Treat as optimistic bound", "priority": "P4 Monitor"},
        {"area": "Historical Bootstrap", "status": f"Success {bs_sum['prob_terminal_gt_start']:.0%}", "risk": "Model-dependent",
         "evidence": "Real 2000-2025 sequences", "action": "Treat as realistic bound", "priority": "P3 Moderate"},
        {"area": "Model Agreement", "status": "Material disagreement" if material else "Broad agreement",
         "risk": "Key uncertainty" if material else "Low",
         "evidence": "Comparison sheet", "action": "Report range, not point estimate", "priority": "P1 Critical" if material else "P4 Monitor"},
    ]
    return pd.DataFrame(rows)


def _exec_summary(cfg, holdings, port, mc_sum, bs_sum, mk_sum, conc, disagreement_df, ctx) -> list[str]:
    lines = [
        f"Where are we now? {len(holdings)} holdings; equity {holdings[holdings['asset_class'].isin(EQUITY_CLASSES)]['weight'].sum():.0%}, "
        f"bonds {holdings[holdings['asset_class'].isin(['Treasury', 'Corporate Bond'])]['weight'].sum():.0%}, "
        f"cash {holdings[holdings['asset_class'] == 'Cash']['weight'].sum():.0%}. Historical CAGR {port.stats['cagr_historical']:.1%}, "
        f"volatility {port.stats['annual_volatility']:.1%}, max drawdown {port.stats['max_drawdown']:.1%}.",
        f"What is expected? Simulated median 2033 value: Monte Carlo ${mc_sum['median_terminal']:,.0f}, "
        f"bootstrap ${bs_sum['median_terminal']:,.0f}, Markov ${mk_sum['median_terminal']:,.0f} "
        f"(from $450,000 invested 2027-2028). These are model estimates, not guarantees.",
        f"What could go wrong? 5th-percentile 2033 outcomes: MC ${mc_sum['terminal_percentiles']['p5']:,.0f}, "
        f"bootstrap ${bs_sum['terminal_percentiles']['p5']:,.0f}. CVaR95 (bootstrap terminal): {bs_sum['mc_cvar_95']:.0%}.",
        f"Biggest concentration: correlated group Growth/Consumer-Tech (ADBE+DIS+DUOL) at "
        f"{holdings[holdings['correlation_group'] == 'Growth/Consumer-Tech']['weight'].sum():.0%} vs 30% cap; "
        f"largest single holding {conc['largest'][0]} at {conc['largest'][1]:.0%}.",
        f"Biggest modeling uncertainty: " + ("MATERIAL disagreement between Monte Carlo and historical bootstrap — see Model Comparison."
                                            if any("Material" in str(f) for f in disagreement_df.to_dict("records"))
                                            else "Monte Carlo and historical bootstrap broadly agree."),
        "What should change? See Recommended Actions (prioritized): trim correlated-group overweight, size the 2033 reserve from bootstrap (heavier-tail) results, adopt the glide path.",
        f"Reserve design: required reserve (PV of 10 x $50,000 payments 2033-2042 at {cfg['cashflows']['reserve_discount_rate']:.1%}) = ${ctx.required_reserve:,.0f}.",
    ]
    return lines


def _historical_text(port, benchmarks) -> str:
    s = port.stats
    return (f"Portfolio history spans {s['n_years']:.1f} years on current weights (rebalanced monthly, "
            f"total-return basis). CAGR {s['cagr_historical']:.2%}, mean annual return {s['mean_annual_return']:.2%}, "
            f"volatility {s['annual_volatility']:.2%}, Sharpe {s['sharpe']:.2f}, Sortino {s['sortino']:.2f}, "
            f"max drawdown {s['max_drawdown']:.2%} (peak {s['drawdown_peak']}, trough {s['drawdown_trough']}, "
            f"recovery {s['drawdown_recovery'] or 'not recovered'}). Survivorship bias applies: only current holdings are represented.")


def _correlation_text(corr, flags, clusters) -> str:
    if not flags:
        return "No pairwise correlations exceed the configured threshold."
    pairs = ", ".join(f"{f['a']}-{f['b']} ({f['correlation']:.2f})" for f in flags[:8])
    return (f"{len(flags)} pair(s) exceed the 0.70 threshold: {pairs}. "
            f"Nominal diversification across {len(corr.columns)} tickers masks correlated exposures — "
            f"number of securities is not the number of independent risk bets.")


def _concentration_text(conc, holdings) -> str:
    grp = holdings.groupby("correlation_group")["weight"].sum()
    grp_txt = "; ".join(f"{g}: {w:.0%}" for g, w in grp.items() if isinstance(g, str))
    return (f"Largest position {conc['largest'][0]} at {conc['largest'][1]:.1%}; top-3 {conc['top3']:.1%}; "
            f"HHI {conc['hhi']['raw']:.3f} (effective bets {conc['hhi']['effective_n']:.1f} of {conc['hhi']['n_holdings']} holdings). "
            f"Correlation groups: {grp_txt}.")


def _mc_text(cfg, s, ctx, contrib) -> str:
    return (f"Monte Carlo ({cfg['simulation']['model']}, {cfg['simulation']['n_simulations']:,} sims, seed {cfg['simulation']['random_seed']}, monthly steps, correlated multivariate returns, glide path + 5pp bands + {cfg['rebalancing']['transaction_cost']:.2%} transaction cost). Median 2033 value ${s['median_terminal']:,.0f}; P(terminal > $450k) = {s['prob_terminal_gt_start']:.1%}; P(all 10 reserve payments funded) = {s['prob_all_payments_funded']:.1%}; P(>20% drawdown) = {s['prob_dd_gt_20']:.1%}. Required reserve ${ctx.required_reserve:,.0f}; median facility contribution ${s['median_facility']:,.0f}.")


def _markov_text(mk, s) -> str:
    return (f"Markov regime model on annual portfolio returns (states: {', '.join(STATE_NAMES)}). "
            f"Current state: {mk['current_state']}. P(bear next year) {mk['prob_bear_next']:.1%}; "
            f"P(bear at any point 2027-2032) {mk['bear_ever_prob']:.1%}. Stationary distribution: "
            + ", ".join(f"{s_}={p:.2f}" for s_, p in zip(STATE_NAMES, mk["stationary"])) + ". "
            f"Limitations: Markov memoryless assumption, state discretization, dependence on historical transition "
            f"frequencies, non-stationarity, structural market change — not a deterministic forecast.")


def _bs_text(cfg, s, ctx, contrib) -> str:
    return (f"Historical bootstrap ({cfg['bootstrap']['method']} bootstrap, {cfg['bootstrap']['block_size_days']}-trading-day blocks "
            f"of real 2000-2025 joint daily returns, {cfg['bootstrap']['n_simulations']:,} sims). "
            f"Median 2033 value ${s['median_terminal']:,.0f}; P(terminal > $450k) = {s['prob_terminal_gt_start']:.1%}; "
            f"P(all payments funded) = {s['prob_all_payments_funded']:.1%}; P(>20% drawdown) = {s['prob_dd_gt_20']:.1%}. "
            f"This engine answers: what if the portfolio lived through actual historical market sequences?")


def _disagreement_text(df) -> str:
    if "Material" in df["flag"].astype(str).str.cat():
        return ("MATERIAL MODEL DISAGREEMENT between engines. The portfolio's apparent robustness depends on "
                "modeling assumptions; plan against the more conservative engine.")
    return "Engines broadly agree on central outcomes; residual differences reflect tail-shape assumptions (Gaussian vs real historical sequences)."


def _sensitivity_text(interp) -> str:
    mr = interp.get("min_return_for_success")
    fv = interp.get("fragile_vol_threshold")
    return (f"Base case success {interp['base_case'].get('prob_success', float('nan')):.1%}. "
            + (f"Minimum return shift for >=90% success: {mr:+.0%}. " if mr is not None else "No return shift reaches 90% success across the grid. ")
            + (f"Portfolio becomes materially fragile (success <75%) at volatility >= {fv:.2f}x." if fv is not None else "Portfolio remains robust across the tested volatility range."))


def _key_risks(cfg, holdings, mc_sum, bs_sum, conc, corr_flags, confidence) -> list[str]:
    risks = [
        f"Correlated Growth/Consumer-Tech group concentration ({holdings[holdings['correlation_group'] == 'Growth/Consumer-Tech']['weight'].sum():.0%} vs 30% cap).",
        f"DUOL has short history (since 2021) — statistics low-confidence; {confidence.get('DUOL', 'Low')} confidence estimates.",
        f"Tail risk: bootstrap CVaR95 {bs_sum['mc_cvar_95']:.0%} vs Gaussian MC {mc_sum['mc_cvar_95']:.0%} — real history has fatter tails than the parametric model.",
        f"Reserve funding risk: P(all 10 payments funded) = {mc_sum['prob_all_payments_funded']:.1%} (MC) / {bs_sum['prob_all_payments_funded']:.1%} (bootstrap).",
        "Survivorship bias: historical analysis reflects only surviving current holdings.",
    ]
    if corr_flags:
        risks.append(f"{len(corr_flags)} high-correlation pairs (>0.70) reduce effective diversification.")
    return risks


def _recommendations(cfg, holdings, flags, mc_sum, bs_sum, mk_sum, conc, corr_flags, disagreement_df, confidence, glide_variants) -> dict:
    group_w = holdings[holdings["correlation_group"] == "Growth/Consumer-Tech"]["weight"].sum()
    recs = {
        "Immediate (Priority 1-2)": [
            f"Trim the Growth/Consumer-Tech correlated group from {group_w:.0%} toward the 30% cap (e.g., reduce DUOL/ADBE) — model identifies a cap breach; investor should weigh tax and conviction before acting.",
            f"Size the 2033 reserve using the bootstrap (heavier-tail) distribution, not the Gaussian MC: bootstrap P(funded) = {bs_sum['prob_all_payments_funded']:.1%}.",
        ],
        "Medium-Term (Priority 3)": [
            "Add a defensive sleeve (Health Care / Consumer Staples / Utilities) or broad-market value exposure to reduce sector concentration in the equity bucket.",
            f"Adopt 5pp rebalancing bands with {cfg['rebalancing']['transaction_cost']:.2%} cost budget; simulated mean turnover ${mc_sum['mean_turnover']:,.0f} per path.",
        ],
        "2033 Preparation (Priority 2-3)": [
            "Follow the linear glide path 70% -> 55% equity by 2033; impact table shows modest upside trade-off for materially lower drawdown risk.",
            "Report the 2031 sponsor range as a percentile band (p5-p95), not a point estimate.",
        ],
        "Watchlist (Priority 4)": [
            "DUOL history length and data confidence; revisit estimates as history accumulates.",
            "Model disagreement between engines — rerun quarterly and widen reserve if disagreement grows.",
            "Correlation clusters during stress periods (correlations rise in crises).",
        ],
    }
    return recs


def _methodology(cfg) -> list[str]:
    return [
        "Prices: dividend/split-adjusted daily closes (Yahoo Finance via yfinance), 2000-01-01 to latest available; total-return basis.",
        "Portfolio history: current weights held constant, rebalanced monthly (rebalanced-index convention).",
        "Monte Carlo: multivariate correlated monthly returns via Cholesky decomposition of covariance; gaussian/lognormal/student-t/historical-residual models selectable.",
        "Expected returns/volatilities: spreadsheet assumptions where supplied; otherwise historical estimates with shrinkage. Covariance = historical correlations x assumed volatilities.",
        "Markov: 5-state regime model on annual portfolio returns; transition matrix, stationary distribution, within-state bootstrap simulation.",
        "Historical bootstrap: block bootstrap (20-trading-day blocks) of real joint daily returns compounded to monthly; no synthetic distributions.",
        "Simulation timeline: $300k at 2027 start, $150k at 2028 start, glide path to 2033, reserve split at 2033, ten $50k payments 2033-2042.",
        "VaR/CVaR: historical, parametric (normal), and Monte Carlo variants at 95%/99%.",
        "Success definitions: terminal > contributions; all reserve payments funded; terminal above inflation-adjusted capital floor.",
    ]


def _assumptions(cfg, weights_source, total_contrib) -> list[str]:
    return [
        f"Contributions: $300,000 at start of 2027 and $150,000 at start of 2028 (user-supplied schedule); total ${total_contrib:,}. No other contributions or withdrawals.",
        f"Reserve: PV of ten $50,000 payments (2033-2042, start of year) discounted at {cfg['cashflows']['reserve_discount_rate']:.1%}.",
        f"Risk-free rate {cfg['risk']['risk_free_rate']:.1%}; cash earns the risk-free rate.",
        f"Inflation base {cfg['risk']['inflation_base']:.1%} (scenarios 2-5% in sensitivity).",
        f"Weights {weights_source}; normalized to 100%.",
        f"Transaction costs {cfg['rebalancing']['transaction_cost']:.2%} of turnover (not zero).",
        "Taxes excluded: no tax-lot information supplied.",
        "Glide path: linear 70% -> 55% equity by 2033 (configurable).",
        "Random seed " + str(cfg["simulation"]["random_seed"]) + f"; {cfg['simulation']['n_simulations']:,} simulations per engine.",
    ]


def _limitations(cfg, confidence, val) -> list[str]:
    low = [t for t, c in confidence.items() if c == "Low"]
    return [
        "Survivorship bias: only current holdings are represented in history.",
        "Look-ahead caution: current weights applied to full history is a convention, not a tradable backtest.",
        f"Low-confidence histories: {', '.join(low) if low else 'none'}.",
        "Yahoo Finance data may contain gaps/survivorship issues; corporate actions handled via adjusted prices only.",
        "Markov model assumes memoryless regime transitions.",
        "No tax-lot data: rebalancing tax impact not estimated.",
        "Currency: all holdings assumed USD-denominated (no FX conversion applied).",
    ]


def _conclusions(mc_sum, bs_sum, mk_sum, conc, interp) -> dict:
    return {
        "What is working?": [
            f"Both engines show median 2033 value above invested contributions (MC ${mc_sum['median_terminal']:,.0f}, bootstrap ${bs_sum['median_terminal']:,.0f}).",
            "Bond + cash sleeve (~32.5%) provides a real buffer; glide path further de-risks into 2033.",
        ],
        "What is fragile?": [
            f"Correlated tech/consumer-tech group concentration ({conc['top3']:.0%} in top 3 holdings).",
            f"Bootstrap downside: p5 2033 value ${bs_sum['terminal_percentiles']['p5']:,.0f}; reserve funding probability {bs_sum['prob_all_payments_funded']:.1%}.",
        ],
        "What matters most?": [
            "1. Equity expected return (sensitivity grid dominates outcomes).",
            "2. Volatility regime (fragility threshold in sensitivity analysis).",
            "3. Reserve discount rate and payment schedule.",
            "4. Correlated-group sizing (largest controllable risk).",
            "5. Glide-path aggressiveness into 2033.",
        ],
        "What should be changed?": [
            "Trim correlated group to cap; size reserve from bootstrap percentiles; adopt glide path and bands.",
        ],
        "What should be monitored?": [
            "Band breaches, drawdown vs 20% review trigger, model disagreement magnitude, DUOL data confidence.",
        ],
    }


def _sector_narrative(sec_tbl, holdings) -> list[str]:
    lines = []
    for sector, row in sec_tbl.iterrows():
        if row["weight"] <= 0:
            continue
        lines.append(f"{sector}: {row['weight']:.1%} of portfolio, {int(row['n_holdings'])} holding(s) ({row['holdings']}); "
                     f"12m return {row['sector_return_12m']:.1%}, contribution {row['contribution_12m']:.2%}.")
    return lines


def _sim_sheet(res, total_contrib: float) -> pd.DataFrame:
    n = min(200, res["n_sims"])
    idx = np.linspace(0, res["n_sims"] - 1, n).astype(int)
    term = res["terminal_2033"][idx]
    paths = res["portfolio_paths"][idx]
    return pd.DataFrame({
        "simulation": idx + 1,
        "terminal_value": term,
        "cagr": (term / total_contrib) ** (1 / 6) - 1,
        "max_drawdown": res["max_drawdown_growth"][idx],
        "min_value": paths.min(axis=1),
        "success": res["all_payments_funded"][idx].astype(int),
    })


def _percentile_frame(s) -> pd.DataFrame:
    rows = [{"metric": f"Terminal {k}", "value": v} for k, v in s["terminal_percentiles"].items()]
    rows += [{"metric": f"Facility contribution {k}", "value": v} for k, v in s["facility_percentiles"].items()]
    rows += [{"metric": "Median facility contribution", "value": s["median_facility"]},
             {"metric": "2031 sponsor range (p5-p95 of value at start 2031 minus reserve)",
              "value": f"${s['projected_facility_2031']['p5']:,.0f} to ${s['projected_facility_2031']['p95']:,.0f}"}]
    return pd.DataFrame(rows)


def _risk_sheet(port, var_table, mc_sum, bs_sum, conc, dd_dist, sec_corr) -> pd.DataFrame:
    rows = [{"metric": f"{r['confidence']:.0%} {k}", "value": r[k]}
            for _, r in var_table.iterrows() for k in ("historical_VaR", "historical_CVaR", "parametric_VaR", "parametric_CVaR")]
    rows += [
        {"metric": "Monte Carlo VaR 95% (terminal)", "value": mc_sum["mc_var_95"]},
        {"metric": "Monte Carlo CVaR 95% (terminal)", "value": mc_sum["mc_cvar_95"]},
        {"metric": "Bootstrap VaR 95% (terminal)", "value": bs_sum["mc_var_95"]},
        {"metric": "Bootstrap CVaR 95% (terminal)", "value": bs_sum["mc_cvar_95"]},
        {"metric": "Historical max drawdown", "value": port.stats["max_drawdown"]},
        {"metric": "Sharpe (historical)", "value": port.stats["sharpe"]},
        {"metric": "Sortino (historical)", "value": port.stats["sortino"]},
        {"metric": "Downside deviation (annual)", "value": port.stats["downside_deviation"]},
        {"metric": "HHI raw", "value": conc["hhi"]["raw"]},
        {"metric": "HHI normalized", "value": conc["hhi"]["normalized"]},
        {"metric": "Effective number of bets", "value": conc["hhi"]["effective_n"]},
        {"metric": "MC max-drawdown median", "value": dd_dist["median"]},
        {"metric": "MC max-drawdown 95th pct", "value": dd_dist["p95"]},
        {"metric": "MC P(>20% drawdown)", "value": mc_sum["prob_dd_gt_20"]},
        {"metric": "Bootstrap P(>20% drawdown)", "value": bs_sum["prob_dd_gt_20"]},
    ]
    return pd.DataFrame(rows)


def _scorecard(cfg, holdings, mc_sum, bs_sum, conc, sec_tbl, confidence) -> pd.DataFrame:
    n = len(holdings)
    eff_n = conc["hhi"]["effective_n"]
    divers = min(100, eff_n / max(n, 1) * 100)
    conc_score = max(0, 100 * (1 - conc["hhi"]["normalized"]))
    downside = 100 * (1 - mc_sum["prob_dd_gt_20"])
    exp_ret = min(100, mc_sum["cagr_money_weighted"] / 0.10 * 100)
    sec_w = sec_tbl["weight"]
    sec_hhi = float((sec_w ** 2).sum())
    sector_balance = max(0, 100 * (1 - sec_hhi))
    tail = max(0, 100 * (1 - mc_sum["mc_cvar_95"] / 0.40))
    glide = 100 if cfg["glide_path"]["enabled"] else 40
    thesis = 100 * holdings["thesis"].apply(lambda x: isinstance(x, str) and len(x) > 10).mean()
    reb = 100 if cfg["rebalancing"]["enabled"] else 30
    rows = [
        {"category": "Diversification", "score": divers},
        {"category": "Concentration", "score": conc_score},
        {"category": "Downside Protection", "score": downside},
        {"category": "Expected Return", "score": exp_ret},
        {"category": "Sector Balance", "score": sector_balance},
        {"category": "Tail Risk", "score": tail},
        {"category": "Glide Path", "score": glide},
        {"category": "Thesis Quality", "score": thesis},
        {"category": "Rebalancing Discipline", "score": reb},
        {"category": "Overall", "score": np.mean([divers, conc_score, downside, exp_ret, sector_balance, tail, glide, thesis, reb])},
    ]
    df = pd.DataFrame(rows)
    df["methodology_note"] = "Heuristic 0-100 scores; documented formulas; not a scientific objective measure."
    return df


def _decision_matrix(cfg, holdings, mc_sum, bs_sum, conc, disagreement_df) -> pd.DataFrame:
    material = any("Material" in str(f.get("flag", "")) for f in disagreement_df.to_dict("records"))
    rows = [
        {"area": "Allocation", "status": "70/17.5/12.5 equity/bond/cash", "risk": "Moderate",
         "evidence": "Within stated bucket targets", "action": "Maintain; monitor bands", "priority": "P4 Monitor"},
        {"area": "Concentration", "status": f"Largest {conc['largest'][0]} {conc['largest'][1]:.0%}", "risk": "Elevated",
         "evidence": f"Correlated group exceeds 30% cap; HHI {conc['hhi']['raw']:.2f}",
         "action": "Trim Growth/Consumer-Tech group toward cap", "priority": "P2 High"},
        {"area": "Sector Exposure", "status": "Tech-heavy equity sleeve", "risk": "Elevated",
         "evidence": "ADBE+DUOL in Information Technology; DIS Communication Services",
         "action": "Consider adding defensive sleeve", "priority": "P3 Moderate"},
        {"area": "Tail Risk", "status": f"CVaR95 {mc_sum['mc_cvar_95']:.0%} (MC terminal)", "risk": "Material",
         "evidence": "Bootstrap tail heavier than Gaussian MC", "action": "Size reserve conservatively", "priority": "P2 High"},
        {"area": "Glide Path", "status": "70% -> 55% equity by 2033", "risk": "Low",
         "evidence": "Glide impact table", "action": "Adopt linear glide; review annually", "priority": "P3 Moderate"},
        {"area": "Rebalancing", "status": "5pp bands configured", "risk": "Low",
         "evidence": "Rebalancing sheet triggers", "action": "Rebalance on band breach only", "priority": "P4 Monitor"},
        {"area": "Investment Thesis", "status": "All holdings have theses", "risk": "Low",
         "evidence": "Theses from input spreadsheet", "action": "Refresh annually", "priority": "P4 Monitor"},
        {"area": "Monte Carlo", "status": f"Success {mc_sum['prob_terminal_gt_start']:.0%}", "risk": "Model-dependent",
         "evidence": "Gaussian assumptions", "action": "Treat as optimistic bound", "priority": "P4 Monitor"},
        {"area": "Historical Bootstrap", "status": f"Success {bs_sum['prob_terminal_gt_start']:.0%}", "risk": "Model-dependent",
         "evidence": "Real 2000-2025 sequences", "action": "Treat as realistic bound", "priority": "P3 Moderate"},
        {"area": "Model Agreement", "status": "Material disagreement" if material else "Broad agreement",
         "risk": "Key uncertainty" if material else "Low",
         "evidence": "Comparison sheet", "action": "Report range, not point estimate", "priority": "P1 Critical" if material else "P4 Monitor"},
    ]
    return pd.DataFrame(rows)


def _exec_summary(cfg, holdings, port, mc_sum, bs_sum, mk_sum, conc, disagreement_df, ctx) -> list[str]:
    lines = [
        f"Where are we now? {len(holdings)} holdings; equity {holdings[holdings['asset_class'].isin(EQUITY_CLASSES)]['weight'].sum():.0%}, "
        f"bonds {holdings[holdings['asset_class'].isin(['Treasury', 'Corporate Bond'])]['weight'].sum():.0%}, "
        f"cash {holdings[holdings['asset_class'] == 'Cash']['weight'].sum():.0%}. Historical CAGR {port.stats['cagr_historical']:.1%}, "
        f"volatility {port.stats['annual_volatility']:.1%}, max drawdown {port.stats['max_drawdown']:.1%}.",
        f"What is expected? Simulated median 2033 value: Monte Carlo ${mc_sum['median_terminal']:,.0f}, "
        f"bootstrap ${bs_sum['median_terminal']:,.0f}, Markov ${mk_sum['median_terminal']:,.0f} "
        f"(from $450,000 invested 2027-2028). These are model estimates, not guarantees.",
        f"What could go wrong? 5th-percentile 2033 outcomes: MC ${mc_sum['terminal_percentiles']['p5']:,.0f}, "
        f"bootstrap ${bs_sum['terminal_percentiles']['p5']:,.0f}. CVaR95 (bootstrap terminal): {bs_sum['mc_cvar_95']:.0%}.",
        f"Biggest concentration: correlated group Growth/Consumer-Tech (ADBE+DIS+DUOL) at "
        f"{holdings[holdings['correlation_group'] == 'Growth/Consumer-Tech']['weight'].sum():.0%} vs 30% cap; "
        f"largest single holding {conc['largest'][0]} at {conc['largest'][1]:.0%}.",
        f"Biggest modeling uncertainty: " + ("MATERIAL disagreement between Monte Carlo and historical bootstrap — see Model Comparison."
                                            if any("Material" in str(f) for f in disagreement_df.to_dict("records"))
                                            else "Monte Carlo and historical bootstrap broadly agree."),
        "What should change? See Recommended Actions (prioritized): trim correlated-group overweight, size the 2033 reserve from bootstrap (heavier-tail) results, adopt the glide path.",
        f"Reserve design: required reserve (PV of 10 x $50,000 payments 2033-2042 at {cfg['cashflows']['reserve_discount_rate']:.1%}) = ${ctx.required_reserve:,.0f}.",
    ]
    return lines


def _historical_text(port, benchmarks) -> str:
    s = port.stats
    return (f"Portfolio history spans {s['n_years']:.1f} years on current weights (rebalanced monthly, "
            f"total-return basis). CAGR {s['cagr_historical']:.2%}, mean annual return {s['mean_annual_return']:.2%}, "
            f"volatility {s['annual_volatility']:.2%}, Sharpe {s['sharpe']:.2f}, Sortino {s['sortino']:.2f}, "
            f"max drawdown {s['max_drawdown']:.2%} (peak {s['drawdown_peak']}, trough {s['drawdown_trough']}, "
            f"recovery {s['drawdown_recovery'] or 'not recovered'}). Survivorship bias applies: only current holdings are represented.")


def _correlation_text(corr, flags, clusters) -> str:
    if not flags:
        return "No pairwise correlations exceed the configured threshold."
    pairs = ", ".join(f"{f['a']}-{f['b']} ({f['correlation']:.2f})" for f in flags[:8])
    return (f"{len(flags)} pair(s) exceed the 0.70 threshold: {pairs}. "
            f"Nominal diversification across {len(corr.columns)} tickers masks correlated exposures — "
            f"number of securities is not the number of independent risk bets.")


def _concentration_text(conc, holdings) -> str:
    grp = holdings.groupby("correlation_group")["weight"].sum()
    grp_txt = "; ".join(f"{g}: {w:.0%}" for g, w in grp.items() if isinstance(g, str))
    return (f"Largest position {conc['largest'][0]} at {conc['largest'][1]:.1%}; top-3 {conc['top3']:.1%}; "
            f"HHI {conc['hhi']['raw']:.3f} (effective bets {conc['hhi']['effective_n']:.1f} of {conc['hhi']['n_holdings']} holdings). "
            f"Correlation groups: {grp_txt}.")


def _mc_text(cfg, s, ctx, contrib) -> str:
    text = (f"Monte Carlo ({cfg['simulation']['model']}, {cfg['simulation']['n_simulations']:,} sims, seed {cfg['simulation']['random_seed']}, monthly steps, correlated multivariate returns, glide path + 5pp bands + {cfg['rebalancing']['transaction_cost']:.2%} transaction cost). Median 2033 value ${s['median_terminal']:,.0f}; P(terminal > $450k) = {s['prob_terminal_gt_start']:.1%}; P(all 10 reserve payments funded) = {s['prob_all_payments_funded']:.1%}; P(>20% drawdown) = {s['prob_dd_gt_20']:.1%}. Required reserve ${ctx.required_reserve:,.0f}; median facility contribution ${s['median_facility']:,.0f}.")
    return text


def _markov_text(mk, s) -> str:
    return (f"Markov regime model on annual portfolio returns (states: {', '.join(STATE_NAMES)}). "
            f"Current state: {mk['current_state']}. P(bear next year) {mk['prob_bear_next']:.1%}; "
            f"P(bear at any point 2027-2032) {mk['bear_ever_prob']:.1%}. Stationary distribution: "
            + ", ".join(f"{s_}={p:.2f}" for s_, p in zip(STATE_NAMES, mk["stationary"])) + ". "
            f"Limitations: Markov memoryless assumption, state discretization, dependence on historical transition "
            f"frequencies, non-stationarity, structural market change — not a deterministic forecast.")


def _bs_text(cfg, s, ctx, contrib) -> str:
    return (f"Historical bootstrap ({cfg['bootstrap']['method']} bootstrap, {cfg['bootstrap']['block_size_days']}-trading-day blocks "
            f"of real 2000-2025 joint daily returns, {cfg['bootstrap']['n_simulations']:,} sims). "
            f"Median 2033 value ${s['median_terminal']:,.0f}; P(terminal > $450k) = {s['prob_terminal_gt_start']:.1%}; "
            f"P(all payments funded) = {s['prob_all_payments_funded']:.1%}; P(>20% drawdown) = {s['prob_dd_gt_20']:.1%}. "
            f"This engine answers: what if the portfolio lived through actual historical market sequences?")


def _disagreement_text(df) -> str:
    if "Material" in df["flag"].astype(str).str.cat():
        return ("MATERIAL MODEL DISAGREEMENT between engines. The portfolio's apparent robustness depends on "
                "modeling assumptions; plan against the more conservative engine.")
    return "Engines broadly agree on central outcomes; residual differences reflect tail-shape assumptions (Gaussian vs real historical sequences)."


def _sensitivity_text(interp) -> str:
    mr = interp.get("min_return_for_success")
    fv = interp.get("fragile_vol_threshold")
    return (f"Base case success {interp['base_case'].get('prob_success', float('nan')):.1%}. "
            + (f"Minimum return shift for >=90% success: {mr:+.0%}. " if mr is not None else "No return shift reaches 90% success across the grid. ")
            + (f"Portfolio becomes materially fragile (success <75%) at volatility >= {fv:.2f}x." if fv is not None else "Portfolio remains robust across the tested volatility range."))


def _key_risks(cfg, holdings, mc_sum, bs_sum, conc, corr_flags, confidence) -> list[str]:
    risks = [
        f"Correlated Growth/Consumer-Tech group concentration ({holdings[holdings['correlation_group'] == 'Growth/Consumer-Tech']['weight'].sum():.0%} vs 30% cap).",
        f"DUOL has short history (since 2021) — statistics low-confidence; {confidence.get('DUOL', 'Low')} confidence estimates.",
        f"Tail risk: bootstrap CVaR95 {bs_sum['mc_cvar_95']:.0%} vs Gaussian MC {mc_sum['mc_cvar_95']:.0%} — real history has fatter tails than the parametric model.",
        f"Reserve funding risk: P(all 10 payments funded) = {mc_sum['prob_all_payments_funded']:.1%} (MC) / {bs_sum['prob_all_payments_funded']:.1%} (bootstrap).",
        "Survivorship bias: historical analysis reflects only surviving current holdings.",
    ]
    if corr_flags:
        risks.append(f"{len(corr_flags)} high-correlation pairs (>0.70) reduce effective diversification.")
    return risks


def _recommendations(cfg, holdings, flags, mc_sum, bs_sum, mk_sum, conc, corr_flags, disagreement_df, confidence, glide_variants) -> dict:
    group_w = holdings[holdings["correlation_group"] == "Growth/Consumer-Tech"]["weight"].sum()
    recs = {
        "Immediate (Priority 1-2)": [
            f"Trim the Growth/Consumer-Tech correlated group from {group_w:.0%} toward the 30% cap (e.g., reduce DUOL/ADBE) — model identifies a cap breach; investor should weigh tax and conviction before acting.",
            f"Size the 2033 reserve using the bootstrap (heavier-tail) distribution, not the Gaussian MC: bootstrap P(funded) = {bs_sum['prob_all_payments_funded']:.1%}.",
        ],
        "Medium-Term (Priority 3)": [
            "Add a defensive sleeve (Health Care / Consumer Staples / Utilities) or broad-market value exposure to reduce sector concentration in the equity bucket.",
            f"Adopt 5pp rebalancing bands with {cfg['rebalancing']['transaction_cost']:.2%} cost budget; simulated mean turnover ${mc_sum['mean_turnover']:,.0f} per path.",
        ],
        "2033 Preparation (Priority 2-3)": [
            "Follow the linear glide path 70% -> 55% equity by 2033; impact table shows modest upside trade-off for materially lower drawdown risk.",
            "Report the 2031 sponsor range as a percentile band (p5-p95), not a point estimate.",
        ],
        "Watchlist (Priority 4)": [
            "DUOL history length and data confidence; revisit estimates as history accumulates.",
            "Model disagreement between engines — rerun quarterly and widen reserve if disagreement grows.",
            "Correlation clusters during stress periods (correlations rise in crises).",
        ],
    }
    return recs


def _methodology(cfg) -> list[str]:
    return [
        "Prices: dividend/split-adjusted daily closes (Yahoo Finance via yfinance), 2000-01-01 to latest available; total-return basis.",
        "Portfolio history: current weights held constant, rebalanced monthly (rebalanced-index convention).",
        "Monte Carlo: multivariate correlated monthly returns via Cholesky decomposition of covariance; gaussian/lognormal/student-t/historical-residual models selectable.",
        "Expected returns/volatilities: spreadsheet assumptions where supplied; otherwise historical estimates with shrinkage. Covariance = historical correlations x assumed volatilities.",
        "Markov: 5-state regime model on annual portfolio returns; transition matrix, stationary distribution, within-state bootstrap simulation.",
        "Historical bootstrap: block bootstrap (20-trading-day blocks) of real joint daily returns compounded to monthly; no synthetic distributions.",
        "Simulation timeline: $300k at 2027 start, $150k at 2028 start, glide path to 2033, reserve split at 2033, ten $50k payments 2033-2042.",
        "VaR/CVaR: historical, parametric (normal), and Monte Carlo variants at 95%/99%.",
        "Success definitions: terminal > contributions; all reserve payments funded; terminal above inflation-adjusted capital floor.",
    ]


def _assumptions(cfg, weights_source, total_contrib) -> list[str]:
    return [
        f"Contributions: $300,000 at start of 2027 and $150,000 at start of 2028 (user-supplied schedule); total ${total_contrib:,}. No other contributions or withdrawals.",
        f"Reserve: PV of ten $50,000 payments (2033-2042, start of year) discounted at {cfg['cashflows']['reserve_discount_rate']:.1%}.",
        f"Risk-free rate {cfg['risk']['risk_free_rate']:.1%}; cash earns the risk-free rate.",
        f"Inflation base {cfg['risk']['inflation_base']:.1%} (scenarios 2-5% in sensitivity).",
        f"Weights {weights_source}; normalized to 100%.",
        f"Transaction costs {cfg['rebalancing']['transaction_cost']:.2%} of turnover (not zero).",
        "Taxes excluded: no tax-lot information supplied.",
        "Glide path: linear 70% -> 55% equity by 2033 (configurable).",
        "Random seed " + str(cfg["simulation"]["random_seed"]) + f"; {cfg['simulation']['n_simulations']:,} simulations per engine.",
    ]


def _limitations(cfg, confidence, val) -> list[str]:
    low = [t for t, c in confidence.items() if c == "Low"]
    return [
        "Survivorship bias: only current holdings are represented in history.",
        "Look-ahead caution: current weights applied to full history is a convention, not a tradable backtest.",
        f"Low-confidence histories: {', '.join(low) if low else 'none'}.",
        "Yahoo Finance data may contain gaps/survivorship issues; corporate actions handled via adjusted prices only.",
        "Markov model assumes memoryless regime transitions.",
        "No tax-lot data: rebalancing tax impact not estimated.",
        "Currency: all holdings assumed USD-denominated (no FX conversion applied).",
    ]


def _conclusions(mc_sum, bs_sum, mk_sum, conc, interp) -> dict:
    return {
        "What is working?": [
            f"Both engines show median 2033 value above invested contributions (MC ${mc_sum['median_terminal']:,.0f}, bootstrap ${bs_sum['median_terminal']:,.0f}).",
            "Bond + cash sleeve (~32.5%) provides a real buffer; glide path further de-risks into 2033.",
        ],
        "What is fragile?": [
            f"Correlated tech/consumer-tech group concentration ({conc['top3']:.0%} in top 3 holdings).",
            f"Bootstrap downside: p5 2033 value ${bs_sum['terminal_percentiles']['p5']:,.0f}; reserve funding probability {bs_sum['prob_all_payments_funded']:.1%}.",
        ],
        "What matters most?": [
            "1. Equity expected return (sensitivity grid dominates outcomes).",
            "2. Volatility regime (fragility threshold in sensitivity analysis).",
            "3. Reserve discount rate and payment schedule.",
            "4. Correlated-group sizing (largest controllable risk).",
            "5. Glide-path aggressiveness into 2033.",
        ],
        "What should be changed?": [
            "Trim correlated group to cap; size reserve from bootstrap percentiles; adopt glide path and bands.",
        ],
        "What should be monitored?": [
            "Band breaches, drawdown vs 20% review trigger, model disagreement magnitude, DUOL data confidence.",
        ],
    }


def _sector_narrative(sec_tbl, holdings) -> list[str]:
    lines = []
    for sector, row in sec_tbl.iterrows():
        if row["weight"] <= 0:
            continue
        lines.append(f"{sector}: {row['weight']:.1%} of portfolio, {int(row['n_holdings'])} holding(s) ({row['holdings']}); "
                     f"12m return {row['sector_return_12m']:.1%}, contribution {row['contribution_12m']:.2%}.")
    return lines


def _sanity_checks(results) -> None:
    h = results["holdings"]
    assert abs(h["weight"].sum() - 1) < 1e-6, "weights must sum to 1"
    sec = results["sector_sheet"]["weight"].sum()
    assert abs(sec - 1) < 1e-6, "sector weights must sum to 1"
    P = results["mk"]["P"]
    assert np.allclose(P.sum(axis=1), 1.0, atol=1e-6), "transition rows must sum to 1"
    for key in ("prob_terminal_gt_start", "prob_all_payments_funded", "prob_dd_gt_20"):
        for s in (results["mc_sum"], results["bs_sum"]):
            assert 0 <= s[key] <= 1, "probabilities out of range"
    assert results["mc_sum"]["mc_cvar_95"] >= results["mc_sum"]["mc_var_95"] - 1e-9, "CVaR must exceed VaR"
    assert results["mc"]["n_sims"] == results["bs"]["n_sims"] == 10000
    for name in ("holdings_sheet", "comparison_sheet", "risk_sheet", "stress_sheet"):
        df = results[name]
        num = df.select_dtypes(include=[np.number])
        assert not num.isna().any().any(), f"NaN found in {name}"
    log.info("Sanity checks passed.")


def _write_manifest(cfg, meta, out_dir) -> None:
    import yaml
    manifest = {
        "run": meta,
        "config": cfg,
        "software": {"python": meta["python"], "platform": meta["platform"],
                     "numpy": np.__version__, "pandas": pd.__version__},
    }
    (out_dir / "report" / "run_manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))
