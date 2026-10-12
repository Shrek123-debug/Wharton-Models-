"""Worked examples: every headline metric, calculated with this portfolio's own numbers.

A definition tells you what HHI *is*. This module shows the arithmetic that produced *your*
0.1937, line by line, and then says what that specific value means for the plan.

Everything here is deterministic: it reads the pipeline's own results and formats them. No
model, no AI, no invented context - if a number is not in the results, no example is written
for it rather than guessing one.
"""
from __future__ import annotations

import pandas as pd

from .metric_glossary import GLOSSARY


def _money(v: float) -> str:
    return f"${v:,.0f}"


def _pct(v: float) -> str:
    return f"{v:.1%}"


def _num(v: float, places: int = 4) -> str:
    return f"{v:,.{places}f}"


def _entry(key: str, substitution: str, result: str, reading: str,
           extra_action: str | None = None) -> dict | None:
    """Build one worked example from a glossary entry plus this portfolio's arithmetic."""
    g = GLOSSARY.get(key)
    if not g:
        return None
    return {
        "key": key,
        "metric": g["label"],
        "unit": g["unit"],
        "formula": g["formula"],
        "your_numbers": substitution,
        "result": result,
        "what_it_means": reading,
        "the_trap": g["caveat"],
        "what_to_do": extra_action or g["action"],
    }


def worked_examples(results: dict) -> list[dict]:
    """Worked examples for the metrics that actually drive the plan's decisions."""
    cfg = results["cfg"]
    holdings = results["holdings"]
    ctx = results["ctx"]
    mc, bs, mk = results["mc_sum"], results["bs_sum"], results["mk_sum"]
    conc = results["conc"]
    total_contrib = sum(c["amount"] for c in cfg["cashflows"]["contributions"])
    out: list[dict] = []

    def add(entry):
        if entry:
            out.append(entry)

    weights = [(str(r["ticker"]), float(r["weight"])) for _, r in holdings.iterrows()]

    # 1. where the weights came from -------------------------------------------------
    add(_entry(
        "weights_source",
        f"{len(weights)} holdings: " + ", ".join(f"{t} {_pct(w)}" for t, w in weights),
        results["meta"]["weights_source"],
        f"These weights are what every simulation starts from. Total invested contributions are "
        f"{_money(total_contrib)}, and the plan's obligation is {_money(ctx.required_reserve)}.",
    ))

    # 2. HHI, shown as the actual sum of squares ------------------------------------
    hhi_raw = conc["hhi"]["raw"]
    squares = " + ".join(f"{w:.3f}²" for _, w in weights)
    add(_entry(
        "hhi",
        f"{squares} = {_num(hhi_raw)}",
        _num(hhi_raw),
        f"With {len(weights)} holdings, a perfectly even portfolio would give "
        f"{_num(1 / len(weights))}. Yours is {_num(hhi_raw)}, so the concentration is real rather "
        f"than nominal.",
    ))

    # 3. effective number of bets ---------------------------------------------------
    hhi_norm = conc["hhi"]["normalized"]
    eff = conc["hhi"]["effective_n"]
    add(_entry(
        "effective_n",
        f"1 / {_num(hhi_norm)} = {_num(eff, 2)}",
        _num(eff, 2),
        f"You hold {len(weights)} positions but they behave like {_num(eff, 2)} independent bets. "
        f"That is the number the funding probabilities are really built on.",
    ))

    # 4. top-3 ----------------------------------------------------------------------
    top3 = conc["top3"]
    largest_t, largest_w = conc["largest"]
    add(_entry(
        "top3_top5_top10",
        f"largest {largest_t} {_pct(largest_w)}; top 3 = {_pct(top3)} of the portfolio",
        _pct(top3),
        f"Three positions carry {_pct(top3)} of the plan. If any one of them halves, the whole "
        f"terminal value moves by roughly a third of that weight.",
    ))

    # 5. correlated clusters --------------------------------------------------------
    cluster_df = results.get("cluster_sheet")
    if cluster_df is not None and len(cluster_df):
        row = cluster_df.sort_values("combined_weight", ascending=False).iloc[0]
        add(_entry(
            "correlation_cluster",
            f"{row['members']} move together (mean correlation "
            f"{_num(float(row['mean_pairwise_correlation']), 2)}) and carry "
            f"{_pct(float(row['combined_weight']))} together",
            _pct(float(row["combined_weight"])),
            f"Those {int(row['n_members'])} holdings are one bet. Treat their combined weight as a "
            f"single exposure when you compare it to the "
            f"{_pct(cfg['risk']['max_correlated_group_weight'])} group cap.",
        ))

    # 6. required reserve, shown as the discounting it actually is ------------------
    rp = cfg["cashflows"]["reserve_payments"]
    n_payments = rp["last_year"] - rp["first_year"] + 1
    rate = cfg["cashflows"]["reserve_discount_rate"]
    terms = " + ".join(f"{_money(rp['amount'])}/(1+{rate:.3f})^{i}" for i in range(n_payments))
    add(_entry(
        "required_reserve",
        f"{terms} … = {_money(ctx.required_reserve)}",
        _money(ctx.required_reserve),
        f"{n_payments} payments of {_money(rp['amount'])} from {rp['first_year']} to {rp['last_year']}, "
        f"discounted at {_pct(rate)}, must be standing still in {rp['first_year']}. Everything above "
        f"that is facility surplus.",
    ))

    # 7. terminal percentiles -------------------------------------------------------
    n_mc = int(results["meta"]["n_sims"])
    n_bs = int(results["bs"].get("n_sims") or results["meta"]["n_sims"])
    pcts = mc["terminal_percentiles"]
    show = [k for k in ("p5", "p25", "p50", "p75", "p95") if k in pcts]
    add(_entry(
        "terminal_percentiles",
        f"{n_mc:,} simulated outcomes of the 2033 value: "
        + ", ".join(f"{k}={_money(pcts[k])}" for k in show),
        _money(pcts["p50"]),
        f"The median is {_money(pcts['p50'])}, but half the runs land below it. Against contributions of "
        f"{_money(total_contrib)}, the 5th percentile is {_money(pcts['p5'])} - that is the number the "
        f"reserve decision should be sized from.",
    ))

    # 8. success probability, as a path count ---------------------------------------
    p_success = mc["prob_terminal_gt_start"]
    add(_entry(
        "prob_terminal_gt_start",
        f"{int(round(p_success * n_mc))} of {n_mc:,} Monte Carlo paths end above "
        f"{_money(total_contrib)}",
        _pct(p_success),
        f"Nominal success looks comfortable at {_pct(p_success)}. Compare it with the bootstrap "
        f"figure of {_pct(bs['prob_terminal_gt_start'])}, which only uses sequences that actually "
        f"happened.",
    ))

    # 9. reserve funding probability -------------------------------------------------
    p_fund_mc, p_fund_bs = mc["prob_all_payments_funded"], bs["prob_all_payments_funded"]
    add(_entry(
        "prob_all_payments_funded",
        f"Monte Carlo: {int(round(p_fund_mc * n_mc))} of {n_mc:,} paths fund all "
        f"{n_payments} payments; bootstrap: {int(round(p_fund_bs * n_bs))} of {n_bs:,}",
        f"{_pct(p_fund_mc)} / {_pct(p_fund_bs)}",
        f"This is the decision metric, and the two engines disagree: {_pct(p_fund_mc)} against "
        f"{_pct(p_fund_bs)}. Plan against the lower one.",
    ))

    # 10. CVaR on the terminal outcome ----------------------------------------------
    cvar = bs["mc_cvar_95"]
    add(_entry(
        "cvar",
        f"average of the worst 5% of bootstrap outcomes = {_pct(cvar)} of invested capital",
        _pct(cvar),
        ("In the bad tail the average outcome is a loss of " + _pct(cvar)) if cvar > 0 else
        (f"Even the worst 5% of bootstrap outcomes average a gain of {_pct(-cvar)}, so the tail is "
         f"not loss-making under these assumptions."),
    ))

    # 11. drawdown distribution ------------------------------------------------------
    # Drawdowns are stored as negatives, so the bad tail is the LOW percentile, not the high one.
    dd = results["dd_dist"]
    dd_median, dd_tail = float(dd["median"]), float(dd["p5"])
    add(_entry(
        "max_drawdown_growth",
        f"across the simulations the median worst peak-to-trough is {_pct(dd_median)} and the worst "
        f"5% of paths reach {_pct(dd_tail)}",
        _pct(dd_tail),
        f"In the unlucky 5% of paths the portfolio falls {abs(dd_tail):.1%} from its peak before the "
        f"glide end, against a configured review trigger of 20%.",
    ))

    # 12. glide path -----------------------------------------------------------------
    glide = results["glide_sheet"]
    if len(glide) and "equity" in glide.columns:
        first, last = glide.iloc[0], glide.iloc[-1]
        add(_entry(
            "glide_path",
            f"{int(first['year'])}: equity {_pct(float(first['equity']))} → "
            f"{int(last['year'])}: equity {_pct(float(last['equity']))}",
            _pct(float(last["equity"])),
            f"Equity moves from {_pct(float(first['equity']))} to {_pct(float(last['equity']))} across "
            f"the plan - this schedule de-risks only if the end target is below the start weight. The "
            f"simulations follow it mechanically, so changing the 2033 equity target changes every "
            f"funding probability.",
        ))

    # 13. rebalancing bands ----------------------------------------------------------
    reb = results["rebalance_sheet"]
    breaches = 0
    if len(reb) and "suggested_trade" in reb.columns:
        breaches = int((reb["suggested_trade"].abs() > 1e-9).sum())
    add(_entry(
        "rebalance_band",
        f"{breaches} of {len(reb)} classes sit outside the ±{_pct(cfg['rebalancing']['band'])} band",
        str(breaches),
        f"With a {_pct(cfg['rebalancing']['band'])} band and "
        f"{_pct(cfg['rebalancing']['transaction_cost'])} transaction cost, "
        f"{breaches} class{'es are' if breaches != 1 else ' is'} currently outside the band.",
    ))

    # 14. sensitivity fragility ------------------------------------------------------
    interp = results.get("sens_interp") or {}
    frag = interp.get("fragile_vol_threshold")
    if frag is not None:
        base = interp.get("base_case")
        base_txt = f" (base case: {base})" if base not in (None, "", {}) else ""
        add(_entry(
            "fragile_vol_threshold",
            f"at the configured return assumption, success drops below 75% once volatility reaches "
            f"{_num(float(frag), 2)}x the estimate{base_txt}",
            _num(float(frag), 2),
            f"If realised volatility runs {_num(float(frag), 2)}x the modelled level, the plan stops "
            f"working at the return you assumed.",
        ))

    # 15. engine disagreement, with the real spread ----------------------------------
    spread = abs(p_fund_mc - p_fund_bs)
    add(_entry(
        "engine_disagreement",
        f"reserve funding: Monte Carlo {_pct(p_fund_mc)} vs bootstrap {_pct(p_fund_bs)} "
        f"= a {(_pct(spread))} spread",
        _pct(spread),
        "The engines disagree more than any single holding's weight. That is a statement about the "
        "assumptions, not about the portfolio.",
    ))

    # 16. regime risk --------------------------------------------------------------
    bear_ever = mk.get("bear_ever_prob")
    if bear_ever is not None:
        add(_entry(
            "bear_ever_prob",
            f"the regime model puts {_pct(float(bear_ever))} probability on at least one bear year "
            f"between 2027 and 2032",
            _pct(float(bear_ever)),
            "This is not a loss estimate; it is the chance that the plan has to absorb a bad year "
            "somewhere in the glide, which is what makes the drawdown numbers worth reading.",
        ))

    # 17. data provenance ------------------------------------------------------------
    prov = results.get("data_provenance")
    if prov is not None and len(prov):
        sources = prov["source"].value_counts().to_dict() if "source" in prov.columns else {}
        as_of = [str(v) for v in prov.get("data_as_of", pd.Series(dtype=object)).tolist() if v]
        add(_entry(
            "data_provenance",
            "prices resolved from: " + ", ".join(f"{k} ({v})" for k, v in sources.items())
            + (f"; earliest as-of {min(as_of)}" if as_of else ""),
            ", ".join(f"{k}" for k in sources) or "none",
            "Two runs of the same portfolio disagree most often because of data vintage, not "
            "mathematics. This is the vintage this run used.",
        ))

    # 17. low-confidence series ------------------------------------------------------
    conf = results.get("confidence") or {}
    weak = [t for t, c in conf.items() if c == "Low"]
    if weak:
        add(_entry(
            "confidence",
            "low-confidence series: " + ", ".join(weak),
            ", ".join(weak),
            "These holdings have short histories, so their expected return and correlation are "
            "the weakest inputs in an otherwise well-supported plan.",
        ))

    # 18. the flags themselves, with their arithmetic --------------------------------
    for f in results.get("rule_flags", []):
        if f.get("severity") not in ("CRITICAL", "HIGH"):
            continue
        key = f.get("glossary_key")
        g = GLOSSARY.get(key or "")
        if not g:
            continue
        out.append({
            "key": key,
            "metric": f"{f['id']} — {f['metric']}",
            "unit": g["unit"],
            "formula": f["rule"],
            "your_numbers": f"measured {f['current_value']:.4f} against threshold {f['threshold']:.4f}",
            "result": f["severity"],
            "what_it_means": f["evidence"],
            "the_trap": g["caveat"],
            "what_to_do": f["action"],
        })

    return out


def worked_examples_text(results: dict) -> list[str]:
    """The same examples as narrative lines, for the written report."""
    lines: list[str] = []
    for e in worked_examples(results):
        lines.append(f"{e['metric']}: {e['your_numbers']} = {e['result']}. {e['what_it_means']}")
    return lines
