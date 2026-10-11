"""Serialize pipeline results into a JSON payload for the interactive web dashboard.

All figures are built server-side as Plotly figure specs (data + layout) so the
browser renders them with the locally vendored plotly.js — no CDN, no AI.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

STATE_NAMES = ["severe_bear", "bear", "neutral", "bull", "strong_bull"]
STATE_COLORS = {"severe_bear": "#b2182b", "bear": "#ef8a62", "neutral": "#bdbdbd",
                "bull": "#67a9cf", "strong_bull": "#2166ac"}
ENGINE_COLORS = {"Monte Carlo": "#4c72b0", "Markov": "#dd8452", "Historical Bootstrap": "#55a868"}


# ---------------------------------------------------------------- primitives
def _num(v):
    if v is None:
        return None
    if isinstance(v, np.ndarray):
        return [_num(x) for x in v.tolist()]
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        v = float(v)
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(v, float):
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, (int, str, bool)):
        return v
    return str(v)


def df_records(df: pd.DataFrame | None, rename: dict | None = None) -> list[dict]:
    if df is None or len(df) == 0:
        return []
    d = df.copy()
    if d.index.name or not isinstance(d.index, pd.RangeIndex):
        d = d.reset_index()
    if rename:
        d = d.rename(columns=rename)
    d.columns = [str(c) for c in d.columns]
    return [{c: _num(r[c]) for c in d.columns} for _, r in d.iterrows()]


def _fig(data: list, layout: dict) -> dict:
    base = dict(margin=dict(l=56, r=18, t=40, b=48), font=dict(size=11),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                hovermode="closest")
    base.update(layout)
    return {"data": data, "layout": base}


# ---------------------------------------------------------------- charts
def _allocation_donut(holdings: pd.DataFrame) -> dict:
    h = holdings.sort_values("weight", ascending=False)
    return _fig(
        [dict(type="pie", hole=0.45, labels=list(h["ticker"]), values=(h["weight"] * 100).round(2).tolist(),
              texttemplate="%{label}<br>%{percent}", textinfo="label+percent", textposition="outside",
              hovertemplate="%{label}: %{value:.1f}%<extra></extra>")],
        dict(title="Allocation by Holding", showlegend=False,
             annotations=[dict(text="Portfolio", showarrow=False, font=dict(size=13))]))


def _sector_bar(sector_rows: list[dict], targets: dict) -> dict:
    rows = [r for r in sector_rows if (r.get("weight") or 0) > 0]
    labels = [r["sector"] for r in rows]
    vals = [(r["weight"] or 0) * 100 for r in rows]
    data = [dict(type="bar", orientation="h", x=vals, y=labels, name="Current",
                 marker_color="#4c72b0", hovertemplate="%{y}: %{x:.1f}%<extra></extra>")]
    tgt_labels = [s for s in labels if targets.get(s) is not None]
    if tgt_labels:
        data.append(dict(type="bar", orientation="h", x=[float(targets[s]) * 100 for s in tgt_labels],
                         y=tgt_labels, name="Target", marker_color="rgba(255,255,255,0.0)",
                         marker_line_color="#e8e8e8", marker_line_width=1.5))
    return _fig(data, dict(title="Sector Allocation (current vs configured targets)", barmode="overlay"))


def _cumulative(history: list[dict]) -> dict:
    if not history:
        return _fig([], dict(title="Historical Growth"))
    months = [r["month"] for r in history]
    data = [dict(type="scatter", x=months, y=[(r["portfolio_value_index"] or 1) * 100 for r in history],
                 name="Portfolio (current weights)", line=dict(width=2, color="#4c72b0"))]
    for col in history[0]:
        if col in ("S&P 500 (SPY)", "US Agg Bond (AGG)", "60/40 Benchmark"):
            data.append(dict(type="scatter", x=months, y=[(r[col] + 1) * 100 if r[col] is not None else None for r in history],
                             name=col, line=dict(width=1.2), opacity=0.75))
    return _fig(data, dict(title="Historical Growth of $100 (monthly-rebalanced, total return)",
                           yaxis=dict(title="$100 invested"), showlegend=True, legend=dict(orientation="h", y=-0.2)))


def _drawdown(history: list[dict]) -> dict:
    if not history:
        return _fig([], dict(title="Drawdown"))
    months = [r["month"] for r in history]
    dd = [(r["drawdown"] or 0) * 100 for r in history]
    return _fig([dict(type="scatter", x=months, y=dd, fill="tozeroy", mode="none",
                      fillcolor="rgba(178,24,43,0.45)", line=dict(color="#b2182b", width=1),
                      name="Drawdown")],
                dict(title="Historical Portfolio Drawdown", yaxis=dict(title="%", zeroline=True)))


def _heatmap(df: pd.DataFrame, title: str) -> dict:
    z = [[_num(v) for v in row] for row in df.to_numpy()]
    text = [["" if v is None else f"{v:.2f}" for v in row] for row in z]
    return _fig([dict(type="heatmap", z=z, x=[str(c) for c in df.columns], y=[str(r) for r in df.index],
                      zmin=-1, zmax=1, colorscale="RdBu", text=text, texttemplate="%{text}",
                      coloraxis=dict(colorscale="RdBu", range=[-1, 1]),
                      hovertemplate="%{y} × %{x}: %{z:.2f}<extra></extra>")],
                dict(title=title))


def _histogram_bins(arrays: dict[str, np.ndarray], bins: int = 60) -> dict:
    pooled = np.concatenate([a for a in arrays.values() if len(a)])
    lo, hi = float(np.min(pooled)), float(np.max(pooled))
    edges = np.linspace(lo, hi, bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2
    data = []
    for name, arr in arrays.items():
        counts, _ = np.histogram(arr, bins=edges)
        data.append(dict(type="bar", x=centers.tolist(), y=counts.tolist(), name=name,
                         marker_color=ENGINE_COLORS.get(name, "#888"), opacity=0.55,
                         hovertemplate="$%{x:,.0f}: %{y} sims<extra></extra>"))
    return data, centers


def _terminal_distribution(results: dict) -> dict:
    arrays = {"Monte Carlo": results["mc_terminal"],
              "Historical Bootstrap": results["bs"]["terminal_2033"],
              "Markov": results["mk"]["terminal_values"] * sum(c["amount"] for c in results["cfg"]["cashflows"]["contributions"])}
    data, _ = _histogram_bins(arrays)
    invested = sum(c["amount"] for c in results["cfg"]["cashflows"]["contributions"])
    data.append(dict(type="line", x=[invested, invested], y=[0, max(sum(d["y"]) for d in data) * 1.05],
                     name="Invested capital", line=dict(color="#e8e8e8", width=1.5, dash="dash")))
    return _fig(data, dict(title="2033 Terminal Value Distribution (start of 2033)",
                           xaxis=dict(title="Portfolio value ($)"), yaxis=dict(title="Simulations"),
                           barmode="overlay", showlegend=True))


def _fan(summ: dict, start_year: int, end_year: int, label: str, color: str) -> dict:
    fan = summ["fan"]
    m = len(fan[50])
    x = [start_year + i / 12 for i in range(m)]
    bands = [(5, 95, 0.12), (10, 90, 0.22), (25, 75, 0.4)]
    data = []
    for lo, hi, alpha in bands:
        data.append(dict(type="scatter", x=x, y=fan[lo].tolist(), mode="lines",
                         line=dict(width=0), showlegend=False, hoverinfo="skip"))
        data.append(dict(type="scatter", x=x, y=fan[hi].tolist(), mode="lines", line=dict(width=0),
                         fill="nx", fillcolor=f"rgba(76,114,176,{alpha})" if color == "blue" else f"rgba(85,168,104,{alpha})",
                         name=f"P{lo}-P{hi}", hoverinfo="skip"))
    data.append(dict(type="scatter", x=x, y=fan[50].tolist(), mode="lines", name="Median",
                     line=dict(color="#111" if color == "blue" else "#1b5e20", width=2)))
    return _fig(data, dict(title=f"{label} — Simulated Portfolio Value Fan ({start_year}-{end_year})",
                           yaxis=dict(title="Portfolio value ($)"),
                           xaxis=dict(range=[start_year, end_year]), showlegend=True, legend=dict(orientation="h", y=-0.25)))


def _comparison_bar(results: dict) -> dict:
    invested = sum(c["amount"] for c in results["cfg"]["cashflows"]["contributions"])
    pcts = ["p5", "p25", "p50", "p75", "p95"]
    engines = [("Monte Carlo", results["mc_sum"]), ("Markov", results["mk_sum"]),
               ("Historical Bootstrap", results["bs_sum"])]
    data = []
    for name, s in engines:
        data.append(dict(type="bar", x=[p.upper() for p in pcts],
                         y=[(s["terminal_percentiles"][p] / invested - 1) * 100 for p in pcts],
                         name=name, marker_color=ENGINE_COLORS[name],
                         hovertemplate=f"{name} %{{x}}: %{{y:.1f}}% vs invested<extra></extra>"))
    return _fig(data, dict(title="2033 Terminal Outcome Percentiles (% vs invested capital)",
                           yaxis=dict(title="% above invested capital"), barmode="group"))


def _sensitivity_heatmap(sens: pd.DataFrame, value: str, title: str, fmt: str) -> dict:
    piv = sens.pivot(index="return_shift", columns="vol_multiplier", values=value)
    z = [[_num(v) for v in row] for row in piv.to_numpy()]
    text = [[(f"{v:.0%}" if fmt == "pct" else f"{v:,.0f}") if v is not None else "" for v in row] for row in z]
    return _fig([dict(type="heatmap", z=z, x=[f"{c:.1f}x" for c in piv.columns],
                      y=[f"{i:+.0%}" for i in piv.index], text=text, texttemplate="%{text}",
                      colorscale="RdYlGn",
                      hovertemplate="return shift %{y}, vol %{x}: %{z}<extra></extra>")],
                dict(title=title, xaxis=dict(title="Volatility multiplier"), yaxis=dict(title="Expected return shift")))


def _crisis_bar(stress_rows: list[dict]) -> dict:
    if not stress_rows:
        return _fig([dict(type="scatter", x=[], y=[])],
                    dict(title="Crisis tests: no configured window overlaps the price history",
                         annotations=[dict(text="See the Data Quality tab for skipped crisis windows.",
                                          x=0.5, y=0.5, showarrow=False)]))
    names = [r["crisis"] for r in stress_rows]
    data = [dict(type="bar", x=names, y=[(r["portfolio_return"] or 0) * 100 for r in stress_rows],
                 name="Portfolio return", marker_color="#4c72b0"),
            dict(type="bar", x=names, y=[(r["max_drawdown"] or 0) * 100 for r in stress_rows],
                 name="Max drawdown", marker_color="#b2182b")]
    return _fig(data, dict(title="Historical Crisis Stress Tests (current weights)",
                           yaxis=dict(title="%"), barmode="group"))


def _glide_area(glide_rows: list[dict]) -> dict:
    years = [r["year"] for r in glide_rows]
    series = [("Equity", "equity", "#4c72b0"), ("Bonds", "bond", "#dd8452"), ("Cash", "cash", "#937860")]
    data = []
    for i, (name, col, color) in enumerate(series):
        data.append(dict(type="scatter", x=years, y=[(r[col] or 0) * 100 for r in glide_rows], name=name,
                         stackgroups="glide", fill="tonexty" if i else "tozeroy",
                         fillcolor=color, line=dict(width=0.5, color="#333"), opacity=0.8))
    return _fig(data, dict(title="2033 Glide Path", yaxis=dict(title="% of portfolio", range=[0, 100]),
                           xaxis=dict(title="Year"), showlegend=True, legend=dict(orientation="h", y=-0.2)))


def _concentration_bar(holdings: pd.DataFrame, cap: float) -> dict:
    h = holdings.sort_values("weight", ascending=False)
    data = [dict(type="bar", x=list(h["ticker"]), y=(h["weight"] * 100).round(2).tolist(),
                 marker_color=["#b2182b" if w > cap else "#6a51a3" for w in h["weight"]],
                 hovertemplate="%{x}: %{y:.1f}%<extra></extra>"),
            dict(type="line", x=list(h["ticker"]), y=[cap * 100] * len(h), name=f"Max position cap ({cap:.0%})",
                 line=dict(color="#b2182b", dash="dash", width=1.5))]
    return _fig(data, dict(title="Holding Concentration vs Position Cap", yaxis=dict(title="% of portfolio"),
                           showlegend=True))


def _scorecard_bar(rows: list[dict]) -> dict:
    r = [x for x in rows if x["category"] != "Overall"]
    overall = next((x for x in rows if x["category"] == "Overall"), None)
    data = [dict(type="bar", orientation="h", x=[x["score"] for x in r], y=[x["category"] for x in r],
                 marker_color=["#55a868" if x["score"] >= 70 else ("#dd8452" if x["score"] >= 45 else "#b2182b") for x in r],
                 hovertemplate="%{y}: %{x:.0f}/100<extra></extra>")]
    layout = dict(title=f"Portfolio Scorecard (heuristic 0-100) — Overall {overall['score']:.0f}" if overall else "Portfolio Scorecard",
                  xaxis=dict(range=[0, 100], title="Score"))
    return _fig(data, layout)


def _markov_P(P: pd.DataFrame) -> dict:
    z = [[_num(v) for v in row] for row in P.to_numpy()]
    text = [["" if v is None else f"{v:.2f}" for v in row] for row in z]
    return _fig([dict(type="heatmap", z=z, x=list(P.columns), y=list(P.index), zmin=0, zmax=1,
                      colorscale="Blues", text=text, texttemplate="%{text}",
                      hovertemplate="from %{y} to %{x}: %{z:.2f}<extra></extra>")],
                dict(title="Markov Transition Matrix P(next | current)"))


def _markov_dist(dist_by_year: dict) -> dict:
    years = sorted(int(y) for y in dist_by_year)
    data = []
    for i, state in enumerate(STATE_NAMES):
        data.append(dict(type="bar", x=[str(y) for y in years],
                         y=[float(dist_by_year[y][i]) * 100 for y in years],
                         name=state, marker_color=STATE_COLORS[state]))
    return _fig(data, dict(title="Projected State Probability by Year (from current state)",
                           yaxis=dict(title="% probability", range=[0, 100]), barmode="stack"))


def _contribution_bar(holdings_rows: list[dict]) -> dict:
    rows = sorted(holdings_rows, key=lambda r: r.get("contribution_12m") or 0, reverse=True)
    data = [dict(type="bar", x=[r["ticker"] for r in rows],
                 y=[(r.get("contribution_12m") or 0) * 100 for r in rows],
                 marker_color=["#55a868" if (r.get("contribution_12m") or 0) >= 0 else "#b2182b" for r in rows],
                 hovertemplate="%{x}: %{y:.2f} pp<extra></extra>")]
    return _fig(data, dict(title="Contribution to Trailing 12-Month Return (percentage points)"))


def _dd_distribution(dd: np.ndarray) -> dict:
    counts, edges = np.histogram(dd, bins=50)
    centers = (edges[:-1] + edges[1:]) / 2
    return _fig([dict(type="bar", x=(centers * 100).tolist(), y=counts.tolist(),
                      marker_color="#b2182b", opacity=0.7,
                      hovertemplate="%{x:.1f}%: %{y} sims<extra></extra>")],
                dict(title="Monte Carlo Max Drawdown Distribution (growth phase)",
                     xaxis=dict(title="Max drawdown (%)"), yaxis=dict(title="Simulations")))


# ---------------------------------------------------------------- payload
def build_payload(results: dict) -> dict:
    cfg = results["cfg"]
    holdings = results["holdings"]
    history = df_records(results["history_sheet"])
    sector_rows = df_records(results["sector_sheet"])
    holdings_rows = df_records(results["holdings_sheet"])
    scorecard_rows = df_records(results["scorecard"])
    start_year = cfg["simulation"]["start_year"]
    glide_end = cfg["simulation"]["glide_end_year"]

    charts = {
        "allocation": _allocation_donut(holdings),
        "sector_bar": _sector_bar(sector_rows, cfg.get("sector_targets") or {}),
        "cumulative": _cumulative(history),
        "drawdown": _drawdown(history),
        "corr_heatmap": _heatmap(results["corr"], "Asset Correlation Matrix (monthly)"),
        "sec_corr_heatmap": _heatmap(results["sec_corr"], "Sector Correlation Matrix (monthly)"),
        "terminal_dist": _terminal_distribution(results),
        "mc_fan": _fan(results["mc_sum"], start_year, glide_end, "Monte Carlo", "blue"),
        "bs_fan": _fan(results["bs_sum"], start_year, glide_end, "Historical Bootstrap", "green"),
        "comparison": _comparison_bar(results),
        "sens_success": _sensitivity_heatmap(results["sensitivity"], "prob_success",
                                             "Sensitivity: Probability of Success (terminal > invested)", "pct"),
        "sens_terminal": _sensitivity_heatmap(results["sensitivity"], "median_terminal",
                                              "Sensitivity: Median 2033 Terminal Value", "money"),
        "crisis": _crisis_bar(df_records(results["stress_sheet"])),
        "glide": _glide_area(df_records(results["glide_sheet"])),
        "concentration": _concentration_bar(holdings, cfg["risk"]["max_position_weight"]),
        "scorecard": _scorecard_bar(scorecard_rows),
        "markov_P": _markov_P(results["mk"]["P_df"]),
        "markov_dist": _markov_dist(results["mk"]["dist_by_year"]),
        "contribution": _contribution_bar(holdings_rows),
        "dd_dist": _dd_distribution(results["mc_dd"]),
    }

    mk_states = pd.DataFrame({"year": results["mk"]["annual_returns"].index,
                              "annual_return": results["mk"]["annual_returns"].values,
                              "state": results["mk"]["states"].values})

    tables = {
        "holdings": holdings_rows,
        "sectors": sector_rows,
        "history": history,
        "comparison": df_records(results["comparison_sheet"]),
        "disagreement": df_records(results["disagreement_sheet"]),
        "markov_states": df_records(results["markov_states"]),
        "markov_timeline": df_records(mk_states),
        "markov_misc": df_records(results["markov_misc"]),
        "mc_percentiles": df_records(results["mc_percentiles"]),
        "risk": df_records(results["risk_sheet"]),
        "clusters": df_records(results.get("cluster_sheet")),
        "var_table": df_records(results["var_table"]),
        "sensitivity": df_records(results["sensitivity_sheet"]),
        "stress": df_records(results["stress_sheet"]),
        "hypothetical": df_records(results["hypothetical_sheet"]),
        "rebalance": df_records(results["rebalance_sheet"]),
        "glide": df_records(results["glide_sheet"]),
        "glide_impact": df_records(results["glide_impact_sheet"]),
        "scorecard": scorecard_rows,
        "decision_matrix": df_records(results["decision_matrix"]),
        "theses": df_records(results["thesis_sheet"]),
        "stops": df_records(results["stop_sheet"]),
        "recovery": df_records(results["recovery_sheet"]),
        "data_quality": df_records(results["dq_sheet"]),
        "optimization": df_records(results["opt"]["table"]),
    }

    thresholds = {
        "max_position_weight": cfg["risk"]["max_position_weight"],
        "max_sector_weight": cfg["risk"]["max_sector_weight"],
        "max_correlated_group_weight": cfg["risk"]["max_correlated_group_weight"],
        "min_cash_weight": cfg["risk"]["min_cash_weight"],
        "correlation_threshold": cfg["risk"]["correlation_threshold"],
        "rebalancing_band": cfg["rebalancing"]["band"],
        "transaction_cost": cfg["rebalancing"]["transaction_cost"],
        "risk_free_rate": cfg["risk"]["risk_free_rate"],
        "inflation_base": cfg["risk"]["inflation_base"],
        "reserve_discount_rate": cfg["cashflows"]["reserve_discount_rate"],
        "required_reserve": results["ctx"].required_reserve,
        "total_contributions": sum(c["amount"] for c in cfg["cashflows"]["contributions"]),
    }

    return {
        "meta": results["meta"],
        "thresholds": thresholds,
        "dashboard": [[l, _num(v), f] for l, v, f in results["dashboard"]],
        "rule_flags": results["rule_flags"],
        "charts": charts,
        "tables": tables,
        "texts": {k: results[k] for k in
                  ("overview_text", "historical_text", "risk_text", "correlation_text", "concentration_text",
                   "mc_text", "markov_text", "bs_text", "disagreement_text", "sensitivity_text",
                   "rebalance_text", "glide_text")},
        "exec_summary": results["exec_summary"],
        "recommendations": results["recommendations"],
        "key_risks": results["key_risks"],
        "risk_discipline": results["risk_discipline"],
        "methodology": results["methodology"],
        "assumptions": results["assumptions"],
        "limitations": results["limitations"],
        "conclusions": results["conclusions"],
        "monitoring": results["monitoring"],
        "sector_narrative": results["sector_narrative"],
        "opt_note": results["opt"]["note"],
    }
