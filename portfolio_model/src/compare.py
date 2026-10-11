"""Run-to-run comparison.

The fastest way to understand what a metric means is to change one assumption and watch which
numbers move. This module builds that diff: two runs of the same portfolio under different
assumptions, side by side, with the change expressed both absolutely and as a percentage, plus
the rule flags that appeared or disappeared.
"""
from __future__ import annotations

import pandas as pd

# Decision-relevant rows from the engine comparison table. Percentiles and probabilities are
# read from the comparison sheet rather than the engine summaries so both runs are measured the
# same way regardless of which engine produced them.
COMPARISON_ROWS = [
    "Median terminal value (2033)",
    "5th percentile",
    "25th percentile",
    "75th percentile",
    "Probability terminal > contributions",
    "Probability reserve fully funded",
    "CVaR 95% (terminal)",
    "Median max drawdown (growth)",
    "Probability >20% drawdown",
]
COMPARISON_ENGINES = ["Monte Carlo", "Historical Bootstrap"]

SEVERITIES = ("CRITICAL", "HIGH", "WARNING", "MONITOR", "INFO")


def headline_metrics(results: dict) -> dict[str, float]:
    """The numbers a comparison should show first, pulled from stable report tables."""
    out: dict[str, float] = {}

    comp = results["comparison_sheet"]
    if len(comp):
        indexed = comp.set_index("metric")
        for metric in COMPARISON_ROWS:
            if metric not in indexed.index:
                continue
            row = indexed.loc[metric]
            for engine in COMPARISON_ENGINES:
                if engine in indexed.columns and pd.notna(row[engine]):
                    out[f"{metric} [{engine}]"] = float(row[engine])

    mc = results["mc_sum"]
    out["Median facility value 2033 [Monte Carlo]"] = float(mc["median_facility"])
    out["Probability the facility gets nothing [Monte Carlo]"] = float(mc["prob_facility_negative"])
    out["Median max drawdown [Monte Carlo]"] = float(mc["median_max_drawdown"])

    conc = results["conc"]["hhi"]
    out["HHI (normalized)"] = float(conc["normalized"])
    out["Effective number of independent bets"] = float(conc["effective_n"])
    out["Largest position weight"] = float(results["conc"]["largest"][1])
    out["Top 3 weight"] = float(results["conc"]["top3"])

    flags = results.get("rule_flags", [])
    for sev in SEVERITIES:
        out[f"Rule flags: {sev}"] = float(sum(1 for f in flags if f.get("severity") == sev))
    return out


def flag_deltas(results_a: dict, results_b: dict) -> list[dict]:
    """Flags that only exist in one of the two runs - the practical signal of a decision.

    Flag ids are sequence numbers assigned during the run, so the same rule can come out as
    RESV-05 in one run and RESV-04 in another. Matching on the raw id would report a flag as
    both appearing and disappearing. Flags are matched on rule and metric instead.
    """
    def key(f: dict) -> tuple:
        return (f["severity"], f["metric"], f["rule"])

    a = {key(f): f for f in results_a.get("rule_flags", [])}
    b = {key(f): f for f in results_b.get("rule_flags", [])}

    def describe(f: dict) -> dict:
        return {"flag": f["id"], "severity": f["severity"], "metric": f["metric"],
                "value": f["current_value"], "action": f["action"]}

    return ([{"change": "only in run A", **describe(f)} for k, f in a.items() if k not in b]
            + [{"change": "only in run B", **describe(f)} for k, f in b.items() if k not in a])


def compare_runs(results_a: dict, results_b: dict, label_a: str = "A", label_b: str = "B") -> pd.DataFrame:
    """Side-by-side metrics with the absolute and relative change."""
    ma, mb = headline_metrics(results_a), headline_metrics(results_b)
    rows = []
    for metric in ma:
        va, vb = ma[metric], mb.get(metric)
        if vb is None:
            continue
        delta = vb - va
        pct = (delta / abs(va)) if abs(va) > 1e-12 else None
        rows.append({
            "metric": metric,
            label_a: va,
            label_b: vb,
            "change": delta,
            "change_%": pct,
            "moves": "better" if _is_better(metric, delta) else ("worse" if delta else "unchanged"),
        })
    return pd.DataFrame(rows)


def _is_better(metric: str, delta: float) -> bool:
    """Direction of improvement. Loss and drawdown metrics improve by getting smaller."""
    if delta == 0:
        return False
    worse_when_higher = ("drawdown", "cvar", "var", "gets nothing", "HHI")
    return not any(w in metric.lower() for w in worse_when_higher) if delta > 0 else \
        any(w in metric.lower() for w in worse_when_higher)


def _is_money(metric: str) -> bool:
    """Money metrics are values; everything else here is a ratio, a weight or a probability."""
    lowered = metric.lower()
    if any(w in lowered for w in ("probability", "weight", "hhi", "bets", "drawdown", "cvar", "var")):
        return False
    return "value" in lowered or "facility" in lowered or "terminal" in lowered


def format_comparison(df: pd.DataFrame, flags: list[dict],
                      label_a: str = "A", label_b: str = "B") -> str:
    lines = [f"{'metric':<52}{label_a:>14}{label_b:>14}{'change':>14}{'change %':>10}"]
    lines.append("-" * 104)
    for _, r in df.iterrows():
        money = _is_money(r["metric"])
        fmtv = (lambda v: f"${v:,.0f}") if money else (lambda v: f"{v:,.3f}")
        pct = "" if r["change_%"] is None or pd.isna(r["change_%"]) else f"{r['change_%']:+.1%}"
        lines.append(f"{r['metric'][:52]:<52}{fmtv(r[label_a]):>14}{fmtv(r[label_b]):>14}"
                     f"{fmtv(r['change']):>14}{pct:>10}")
    if flags:
        lines.append("")
        lines.append("Rule flags that differ between the two runs:")
        for f in flags:
            lines.append(f"  [{f['change']}] {f['flag']} ({f['severity']}) {f['metric']} "
                         f"= {f['value']:.3f}")
            lines.append(f"      action: {f['action']}")
    else:
        lines.append("\nBoth runs triggered the same rule flags.")
    return "\n".join(lines)
