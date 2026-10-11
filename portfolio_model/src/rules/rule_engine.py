"""Deterministic rule-based risk/rebalancing flag engine (spec: rule-based recommendations).

Every flag produced here is traceable to a named rule, a configured threshold, and a
calculated value. No AI/LLM is involved. Each flag carries:

  id, severity, category, metric, current_value, threshold, rule, action, evidence

Severity ladder: CRITICAL > HIGH > WARNING > MONITOR > INFO.
"""
from __future__ import annotations

import pandas as pd

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "WARNING": 2, "MONITOR": 3, "INFO": 4}

# Every flag family maps to the glossary entry that explains the metric it compares.
# This is what lets the report, the workbook and the web UI say "what this flag is about"
# without re-describing the metric in three places.
FLAG_GLOSSARY = {
    "POS": "max_position_weight",
    "DRF": "rebalance_band",
    "GRP": "max_correlated_group_weight",
    "SEC": "max_sector_weight",
    "SBND": "max_sector_weight",
    "CASH": "min_cash_weight",
    "CORR": "correlation",
    "HHI": "effective_n",
    "DD": "max_drawdown_growth",
    "TAIL": "cvar",
    "RESV": "prob_all_payments_funded",
    "SUCC": "prob_terminal_gt_start",
    "MODEL": "engine_disagreement",
    "CONF": "confidence",
    "THESIS": "thesis_coverage",
    "REBAL": "turnover",
    "GLIDE": "glide_path",
    "SENS": "fragile_vol_threshold",
}


def glossary_key_for(flag_id: str) -> str | None:
    """Glossary key behind a flag id like 'RESV-05'."""
    prefix = "".join(ch for ch in flag_id.split("-")[0] if ch.isalpha())
    return FLAG_GLOSSARY.get(prefix)


def _flag(flags: list, fid: str, severity: str, category: str, metric: str,
          current: float, threshold: float, rule: str, action: str,
          evidence: str, fmt: str = "pct") -> None:
    flags.append({
        "id": fid,
        "severity": severity,
        "category": category,
        "metric": metric,
        "current_value": float(current),
        "threshold": float(threshold),
        "rule": rule,
        "action": action,
        "evidence": evidence,
        "format": fmt,
        "glossary_key": glossary_key_for(fid),
    })


def _pct(v: float) -> str:
    return f"{v:.1%}"


def build_rule_flags(cfg: dict, holdings: pd.DataFrame, sector_tbl: pd.DataFrame,
                     conc: dict, corr_flags: list, mc_sum: dict, bs_sum: dict,
                     mk_sum: dict, disagreement: pd.DataFrame, confidence: dict,
                     reb_df: pd.DataFrame, sens_interp: dict) -> list[dict]:
    risk = cfg["risk"]
    reb = cfg["rebalancing"]
    flags: list[dict] = []
    n = 1

    # ---------------------------------------------------------------- positions
    max_pos = risk["max_position_weight"]
    for _, h in holdings.iterrows():
        w = float(h["weight"])
        if w > max_pos + 1e-9:
            _flag(flags, f"POS-{n:02d}", "HIGH", "Concentration",
                  f"{h['ticker']} position weight", w, max_pos,
                  f"Single holding weight > configured maximum position weight ({_pct(max_pos)})",
                  f"Reduce {h['ticker']} toward the {_pct(max_pos)} cap; stage the trim to manage tax impact.",
                  f"{h['ticker']} is {_pct(w)} of the portfolio vs a {_pct(max_pos)} cap.")
            n += 1

    # target-weight drift (spreadsheet target_weight column, when supplied)
    if "target_weight" in holdings.columns:
        for _, h in holdings.iterrows():
            tgt = h.get("target_weight")
            if pd.notna(tgt) and float(tgt) > 0:
                dev = float(h["weight"]) - float(tgt)
                band = reb["band"]
                if abs(dev) > band + 1e-9:
                    _flag(flags, f"DRF-{n:02d}", "WARNING", "Rebalancing",
                          f"{h['ticker']} drift vs target", dev, band,
                          f"|current weight - target weight| > {reb['method']} band of {_pct(band)}",
                          f"{'Buy' if dev < 0 else 'Trim'} {h['ticker']} by {abs(dev):.1%} to restore the {float(tgt):.1%} target.",
                          f"{h['ticker']}: current {_pct(h['weight'])} vs target {_pct(float(tgt))}.")
                    n += 1

    # ---------------------------------------------------------------- groups
    grp_cap = risk["max_correlated_group_weight"]
    if "correlation_group" in holdings.columns:
        grp = holdings[holdings["correlation_group"].notna()].groupby("correlation_group")["weight"].sum()
        for g, s in grp.items():
            if s > grp_cap + 1e-9:
                members = ", ".join(holdings[holdings["correlation_group"] == g]["ticker"])
                _flag(flags, f"GRP-{n:02d}", "HIGH", "Concentration",
                      f"Correlated group '{g}' total weight", float(s), grp_cap,
                      f"Correlated-group exposure > configured cap ({_pct(grp_cap)})",
                      f"Trim the '{g}' group ({members}) toward {_pct(grp_cap)}; these holdings move together and diversification is overstated.",
                      f"Group '{g}' ({members}) totals {_pct(float(s))} vs a {_pct(grp_cap)} cap.")
                n += 1

    # ---------------------------------------------------------------- sectors
    max_sec = risk["max_sector_weight"]
    targets = cfg.get("sector_targets") or {}
    for sector, row in sector_tbl.iterrows():
        w = float(row["weight"])
        if w <= 0:
            continue
        if w > max_sec + 1e-9:
            _flag(flags, f"SEC-{n:02d}", "WARNING", "Sector Concentration",
                  f"{sector} sector weight", w, max_sec,
                  f"Sector allocation > configured maximum sector weight ({_pct(max_sec)})",
                  f"Review/rebalance {sector} exposure toward the {_pct(max_sec)} cap.",
                  f"{sector}: {_pct(w)} of portfolio ({row['holdings']}).")
            n += 1
        tgt = targets.get(sector)
        if tgt is not None and float(tgt) > 0:
            dev = w - float(tgt)
            band = reb["band"]
            if abs(dev) > band + 1e-9:
                _flag(flags, f"SBND-{n:02d}", "WARNING", "Sector Concentration",
                      f"{sector} allocation vs target", w, float(tgt) + band,
                      f"Sector allocation > target ({_pct(float(tgt))}) + {band * 100:.0f} percentage points",
                      f"Review/rebalance {sector} exposure back toward the {_pct(float(tgt))} target band.",
                      f"{sector}: {_pct(w)} vs target {_pct(float(tgt))} (allowed band {_pct(float(tgt) - band)}-{_pct(float(tgt) + band)}).")
                n += 1

    # ---------------------------------------------------------------- cash floor
    min_cash = risk["min_cash_weight"]
    cash_w = float(holdings[holdings["asset_class"] == "Cash"]["weight"].sum())
    if cash_w < min_cash - 1e-9:
        _flag(flags, f"CASH-{n:02d}", "WARNING", "Liquidity",
              "Cash weight", cash_w, min_cash,
              f"Cash allocation < configured minimum cash weight ({_pct(min_cash)})",
              "Raise cash to at least the configured minimum before the 2033 reserve phase.",
              f"Cash is {_pct(cash_w)} vs a {_pct(min_cash)} minimum.")
        n += 1

    # ---------------------------------------------------------------- correlations
    corr_th = risk["correlation_threshold"]
    for f in corr_flags[:12]:
        _flag(flags, f"CORR-{n:02d}", "WARNING", "Correlation",
              f"{f['a']}-{f['b']} correlation", f["correlation"], corr_th,
              f"|Pairwise monthly correlation| > configured threshold ({corr_th:.2f})",
              f"Treat {f['a']} and {f['b']} as one risk bet when sizing exposure; avoid adding correlated positions.",
              f"Correlation {f['correlation']:.2f} exceeds {corr_th:.2f}.")
        n += 1

    # ---------------------------------------------------------------- HHI / effective bets
    eff_n = conc["hhi"]["effective_n"]
    n_hold = conc["hhi"]["n_holdings"]
    if n_hold >= 3 and eff_n < 0.6 * n_hold:
        _flag(flags, f"HHI-{n:02d}", "MONITOR", "Concentration",
              "Effective number of independent bets", eff_n, 0.6 * n_hold,
              "HHI effective-bet count < 60% of holding count (weights concentrated)",
              "Concentration is driven by a few large/correlated positions; review sizing before adding holdings.",
              f"HHI {_pct(conc['hhi']['raw'])} normalized {conc['hhi']['normalized']:.2f}; effective bets {eff_n:.1f} of {n_hold} holdings.",
              fmt="num")
        n += 1

    # ---------------------------------------------------------------- drawdown review trigger
    dd_th = 0.25
    for label, s in (("Monte Carlo", mc_sum), ("Historical Bootstrap", bs_sum)):
        p = s["prob_dd_gt_20"]
        if p > dd_th:
            _flag(flags, f"DD-{n:02d}", "WARNING", "Drawdown",
                  f"{label} P(>20% growth-phase drawdown)", p, dd_th,
                  f"Simulated probability of a >20% drawdown > {_pct(dd_th)} review trigger",
                  "Portfolio-level review triggered: consider glide-path acceleration, band tightening, or a defensive sleeve.",
                  f"{label}: P(>20% drawdown) = {_pct(p)} (median max drawdown {_pct(s['median_max_drawdown'])}).")
            n += 1

    # ---------------------------------------------------------------- tail risk
    cvar_th = 0.30
    for label, s in (("Monte Carlo", mc_sum), ("Historical Bootstrap", bs_sum)):
        cvar = s["mc_cvar_95"]
        if cvar > cvar_th:
            _flag(flags, f"TAIL-{n:02d}", "HIGH", "Tail Risk",
                  f"{label} terminal CVaR 95%", cvar, cvar_th,
                  f"Simulated terminal CVaR(95%) loss > {_pct(cvar_th)} threshold",
                  "Size the 2033 reserve from the heavier-tail engine; treat point estimates as optimistic.",
                  f"{label} CVaR95 = {_pct(cvar)} (expected loss in the worst 5% of 2033 outcomes).")
            n += 1

    # ---------------------------------------------------------------- reserve funding
    res_th = 0.90
    worst_res = min(mc_sum["prob_all_payments_funded"], bs_sum["prob_all_payments_funded"])
    if worst_res < res_th:
        _flag(flags, f"RESV-{n:02d}", "HIGH", "Funding Risk",
              "Probability all 10 reserve payments funded", worst_res, res_th,
              f"min(MC, bootstrap) P(all reserve payments funded) < {_pct(res_th)}",
              "Increase the reserve discount buffer, extend the glide path, or reduce payment size; plan against the conservative engine.",
              f"MC {_pct(mc_sum['prob_all_payments_funded'])} / bootstrap {_pct(bs_sum['prob_all_payments_funded'])} vs a {_pct(res_th)} planning standard.")
        n += 1

    # ---------------------------------------------------------------- success probability
    succ_th = 0.80
    worst_succ = min(mc_sum["prob_terminal_gt_start"], bs_sum["prob_terminal_gt_start"])
    if worst_succ < succ_th:
        _flag(flags, f"SUCC-{n:02d}", "WARNING", "Funding Risk",
              "Probability terminal value > invested capital", worst_succ, succ_th,
              f"min(MC, bootstrap) P(2033 terminal > contributions) < {_pct(succ_th)}",
              "Reassess expected-return assumptions and contribution schedule; results are sensitive to the equity return assumption.",
              f"MC {_pct(mc_sum['prob_terminal_gt_start'])} / bootstrap {_pct(bs_sum['prob_terminal_gt_start'])}.")
        n += 1

    # ---------------------------------------------------------------- model disagreement
    if disagreement is not None and disagreement["flag"].astype(str).str.contains("Material").any():
        rows = "; ".join(f"{r['metric']} differs by {r['difference']}" for _, r in disagreement.iterrows())
        _flag(flags, f"MODEL-{n:02d}", "HIGH", "Model Risk",
              "Monte Carlo vs historical bootstrap disagreement", 1, 1,
              "Key metrics differ materially between Gaussian MC and real-history bootstrap (>10pp probability or >25% value)",
              "Report ranges, not point estimates; make reserve/funding decisions using the conservative bootstrap engine.",
              rows + ".", fmt="count")
        n += 1

    # ---------------------------------------------------------------- data confidence
    for t, c in confidence.items():
        if c == "Low":
            _flag(flags, f"CONF-{n:02d}", "MONITOR", "Data Quality",
                  f"{t} history length / estimate confidence", 0, 0,
                  "Holding has <2 years of return history (low-confidence statistics)",
                  f"Treat {t} expected return/volatility/correlation as low-confidence; re-estimate as history accumulates.",
                  f"{t} confidence rating: Low.", fmt="count")
            n += 1

    # ---------------------------------------------------------------- thesis completeness
    missing_thesis = [h["ticker"] for _, h in holdings.iterrows()
                      if not isinstance(h.get("thesis"), str) or len(str(h.get("thesis"))) <= 10]
    if missing_thesis:
        _flag(flags, f"THESIS-{n:02d}", "MONITOR", "Governance",
              "Holdings without a stated investment thesis", len(missing_thesis), 0,
              "Any holding with a missing/short thesis is a governance risk flag",
              f"Document an investment thesis for {', '.join(missing_thesis)} so thesis-break trim rules can be enforced.",
              f"{len(missing_thesis)} holding(s) lack a usable thesis: {', '.join(missing_thesis)}.", fmt="count")
        n += 1

    # ---------------------------------------------------------------- rebalancing bands
    if reb.get("enabled") and reb_df is not None:
        for _, r in reb_df[reb_df["trigger"]].iterrows():
            _flag(flags, f"REBAL-{n:02d}", "WARNING", "Rebalancing",
                  f"{r['class']} weight vs glide-path target band", float(r["current_weight"]), float(r["upper_band"]),
                  f"Class weight outside target band [{_pct(float(r['lower_band']))}, {_pct(float(r['upper_band']))}]",
                  f"Rebalance {r['class']} by {float(r['suggested_trade']):.1%} of portfolio toward the {_pct(float(r['target']))} target.",
                  f"Current {_pct(float(r['current_weight']))} vs target {_pct(float(r['target']))}.")
            n += 1

    # ---------------------------------------------------------------- glide path discipline
    if not cfg["glide_path"]["enabled"]:
        _flag(flags, f"GLIDE-{n:02d}", "MONITOR", "Glide Path",
              "2033 glide path enabled", 0, 1,
              "Glide path disabled while target year 2033 is configured",
              "Enable a glide path into 2033 or document why constant equity exposure is intended.",
              "Config: glide_path.enabled = false.", fmt="count")
        n += 1

    # ---------------------------------------------------------------- sensitivity fragility
    fv = sens_interp.get("fragile_vol_threshold")
    if fv is not None and fv <= 1.1:
        _flag(flags, f"SENS-{n:02d}", "MONITOR", "Sensitivity",
              "Volatility multiplier at which success falls below 75%", fv, 1.1,
              "Fragile volatility threshold <= 1.1x base volatility",
              "Outcomes are fragile to modest volatility increases; prefer conservative reserve sizing.",
              f"Success <75% at volatility >= {fv:.2f}x base.", fmt="num")
        n += 1

    flags.sort(key=lambda f: (SEVERITY_ORDER[f["severity"]], f["id"]))
    return flags
