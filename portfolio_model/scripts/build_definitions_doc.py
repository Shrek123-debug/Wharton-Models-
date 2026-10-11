#!/usr/bin/env python
"""Generate docs/METRIC_DEFINITIONS.md from src/metric_glossary.py.

The glossary is the single source of truth. The web UI Definitions tab, the workbook
Definitions sheet and this markdown page are all rendered from it, so they cannot drift
apart from each other or from the code.

Usage:
  python scripts/build_definitions_doc.py            # writes docs/METRIC_DEFINITIONS.md
  python scripts/build_definitions_doc.py --check    # fail if the file is out of date
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.metric_glossary import CHART_GUIDE, GLOSSARY, SEVERITY_LEGEND, SHEET_GUIDE, SHEET_QUESTIONS  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUT_PATH = REPO_ROOT / "docs" / "METRIC_DEFINITIONS.md"

SECTIONS: list[tuple[str, str, list[str]]] = [
    ("1. Inputs and assumptions",
     "Everything downstream depends on these. If a number later in the report surprises you, "
     "it is usually because one of these was not what you assumed.",
     ["weights_source", "expected_return", "volatility", "risk_free_rate", "inflation_base"]),

    ("2. Historical portfolio metrics",
     "These describe what the *current weights* would have done over the price history. They are "
     "a hypothetical portfolio, not your account statement.",
     ["cagr_historical", "mean_annual_return", "annual_volatility", "sharpe", "sortino",
      "downside_deviation", "max_drawdown", "drawdown_peak_trough_recovery", "recovery_days",
      "correlation", "correlation_cluster", "hhi", "effective_n", "top3_top5_top10"]),

    ("3. Plan mechanics (money in, obligation out)",
     "The simulation is a schedule, not a generic forecast. These are the schedule's parts.",
     ["contributions", "required_reserve", "split_month", "facility_contribution",
      "glide_path", "rebalance_band", "turnover"]),

    ("4. Simulation outcomes",
     "The numbers people quote. Each one answers a different question, and quoting the wrong one "
     "is how portfolios get mis-sized.",
     ["terminal_2033", "median_terminal", "terminal_percentiles", "prob_terminal_gt_start",
      "prob_terminal_gt_real_start", "prob_floor_100 / 90 / 80 / 70", "prob_all_payments_funded",
      "prob_facility_negative", "prob_capital_depletion", "max_drawdown_growth",
      "cagr_money_weighted", "v2031 / projected_facility_2031"]),

    ("5. The three engines and why they disagree",
     "Three engines share one path simulator and differ only in where the returns come from. "
     "Their disagreement is information, not noise.",
     ["monte_carlo", "student_t", "bootstrap", "block_bootstrap", "markov", "markov_states",
      "transition_matrix", "stationary_distribution", "expected_duration", "bear_ever_prob",
      "bull_by_end_prob"]),

    ("6. Risk measures (VaR and CVaR)",
     "The most misread rows in the workbook. Read the horizon and the basis before comparing any two.",
     ["var", "cvar", "var_horizon_warning"]),

    ("7. Sensitivity and stress",
     "Sensitivity asks 'how much can the assumptions be wrong'. Stress asks 'what happens in a named bad world'.",
     ["sensitivity_grid", "min_return_for_success", "fragile_vol_threshold", "sharpe_proxy",
      "crisis_test", "hypothetical_shock"]),

    ("8. Stops and optimisation",
     "Both are diagnostics. Neither is a mandate.",
     ["stop_loss_backtest", "missed_upside", "suggested_allocation"]),

    ("9. Suggestions: how the rule flags work",
     "Every recommendation in this project is a deterministic threshold breach with a traceable "
     "number, rule and action. No AI is involved.",
     ["rule_flag", "severity_levels"]),

    ("10. Data quality and what the model refuses to invent",
     "These rows are the model telling you where its own numbers are weak.",
     ["confidence", "data_provenance", "adjusted_close_basis", "survivorship_bias",
      "pl_note", "tax_note"]),

    ("11. Rule caps and thresholds (what the flags compare against)",
     "Every rule flag is a measured value against a cap you configured. These are those caps, "
     "and what breaching one actually means.",
     ["max_position_weight", "max_sector_weight", "max_correlated_group_weight",
      "min_cash_weight", "rebalance_band", "engine_disagreement", "thesis_coverage",
      "rule_flag", "severity_levels"]),

    ("12. Scorecard",
     "A triage summary, deliberately not the conclusion.",
     ["scorecard"]),
]

MISREADINGS = [
    ("Quoting the median as if it were a promise",
     "The median is the middle outcome: half the simulations land worse. Size obligations from p5-p10."),
    ("Reading nominal success as purchasing-power success",
     "`prob_terminal_gt_start` counts a year of 2% inflation and 1% return as success. "
     "`prob_terminal_gt_real_start` does not."),
    ("Comparing VaR numbers across sheets",
     "Risk-sheet VaR is one-month; comparison-table VaR is the 2033 terminal outcome. Different horizons, different bases."),
    ("Treating a high `bear_ever_prob` as a warning",
     "It means 'at least one bear year before 2033', which is close to a certainty for an equity-heavy plan."),
    ("Believing the Gaussian Monte Carlo",
     "Gaussian MC understates crash frequency. The bootstrap engine is the one that has actually seen 2008."),
    ("Reading a 7-holding portfolio as diversified",
     "Compare holding count with `effective_n`. Seven names can be three bets."),
    ("Confusing the suggested allocation with a target",
     "It is a max-Sharpe diagnostic built on your own expected-return inputs; it amplifies estimation error."),
    ("Assuming a stop-loss backtest proves stops work",
     "It compares one fixed policy with a fixed 21-day re-entry on one history. Read `missed_upside` first."),
    ("Assuming the run used live prices",
     "Check the Data provenance rows. An offline run uses the committed snapshots in `data/offline/`."),
    ("Assuming the report includes taxes",
     "It does not. Transaction cost is modelled; tax is not."),
]


def _fmt_entry(key: str) -> str:
    e = GLOSSARY[key]
    lines = [f"### {e['label']}", ""]
    lines.append(f"*Glossary key: `{key}` · unit: {e['unit']}*")
    lines.append("")
    lines.append(f"- **What it is:** {e['formula']}")
    lines.append(f"- **What it measures:** {e['meaning']}")
    lines.append(f"- **How to read it for this portfolio:** {e['read_as']}")
    lines.append(f"- **What to do about it:** {e['action']}")
    lines.append(f"- **Trap:** {e['caveat']}")
    lines.append("")
    return "\n".join(lines)


def build_doc() -> str:
    used = [k for _, _, keys in SECTIONS for k in keys]
    missing = sorted(set(GLOSSARY) - set(used))
    if missing:
        print(f"WARNING: glossary keys not placed in any section: {', '.join(missing)}")

    out: list[str] = []
    out.append("# Metric Definitions — what every number in this report means")
    out.append("")
    out.append("> Generated from `portfolio_model/src/metric_glossary.py` by "
                "`portfolio_model/scripts/build_definitions_doc.py`.")
    out.append("> The web UI **Definitions** tab and the workbook **Definitions** sheet render the "
                "same entries, so the three views can never disagree.")
    out.append("")
    out.append("## How to use this page")
    out.append("")
    out.append("1. **Start with the question, not the metric.** "
                "\"Can the 2033 reserve be funded?\" is answered by *Probability all reserve payments funded*, "
                "not by the median terminal value.")
    out.append("2. **Read the basis and the horizon before comparing two numbers.** "
                "Monthly VaR and terminal VaR are not the same measurement.")
    out.append("3. **Prefer ranges to point estimates.** Every percentile row exists because a single "
                "number is the wrong basis for a decision.")
    out.append("4. **When two engines disagree, that is a finding.** The comparison and disagreement "
                "sheets exist to make the disagreement visible, not to average it away.")
    out.append("5. **Assumptions are configurable, and they are the real drivers.** "
                "Expected returns, inflation, the reserve discount rate and the glide path move the "
                "conclusions far more than the choice of engine.")
    out.append("")
    out.append("Quick index: " + " · ".join(f"[{t.split('. ', 1)[1]}](#{t.split('. ', 1)[1].lower().replace(' ', '-').replace('(', '').replace(')', '').replace(',', '')})" for t, _, _ in SECTIONS))
    out.append("")

    for title, intro, keys in SECTIONS:
        out.append(f"## {title}")
        out.append("")
        out.append(intro)
        out.append("")
        for k in keys:
            if k in GLOSSARY:
                out.append(_fmt_entry(k))

    out.append("## The ten most common misreadings")
    out.append("")
    for i, (name, text) in enumerate(MISREADINGS, 1):
        out.append(f"{i}. **{name}.** {text}")
    out.append("")

    out.append("## Where to look in the workbook")
    out.append("")
    out.append("The generated workbook opens on a **Read Me** sheet rendered from the same source as this list.")
    out.append("")
    out.append("| Question | Where to look |")
    out.append("|---|---|")
    for q, sheets in SHEET_QUESTIONS:
        out.append(f"| {q} | {sheets} |")
    out.append("")
    out.append("| Sheet | What it is for |")
    out.append("|---|---|")
    for s, d in SHEET_GUIDE:
        out.append(f"| `{s}` | {d} |")
    out.append("")
    out.append("| Severity | What it means |")
    out.append("|---|---|")
    for s, m in SEVERITY_LEGEND:
        out.append(f"| **{s}** | {m} |")
    out.append("")

    out.append("## Reading the charts")
    out.append("")
    out.append("One entry per figure in the web dashboard, generated from the same file as the "
               "captions the dashboard itself renders.")
    out.append("")
    for key, g in CHART_GUIDE.items():
        links = ", ".join(f"`{k}`" for k in g["keys"])
        out.append(f"### {g['title']}")
        out.append("")
        out.append(f"- **What it shows:** {g['shows']}")
        out.append(f"- **How to read it:** {g['read']}")
        out.append(f"- **Watch out:** {g['watch']}")
        out.append(f"- **Metrics behind it:** {links}")
        out.append("")

    out.append("## Metric reference table")
    out.append("")
    out.append("| Key | Label | Unit | One-line meaning |")
    out.append("|---|---|---|---|")
    for k in sorted(GLOSSARY):
        e = GLOSSARY[k]
        meaning = e["meaning"].split(". ")[0].replace("|", "/")
        out.append(f"| `{k}` | {e['label']} | {e['unit']} | {meaning} |")
    out.append("")
    out.append(f"_{len(GLOSSARY)} metric definitions. "
                "Add a key to `src/metric_glossary.py` and re-run the generator to extend every view at once._")
    out.append("")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate docs/METRIC_DEFINITIONS.md")
    ap.add_argument("--check", action="store_true", help="Fail if the generated file is out of date")
    ap.add_argument("--out", default=str(OUT_PATH))
    args = ap.parse_args()

    doc = build_doc()
    path = Path(args.out)
    if args.check:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != doc:
            print(f"OUT OF DATE: {path} (run scripts/build_definitions_doc.py)")
            return 1
        print(f"{path} is up to date ({len(GLOSSARY)} definitions)")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc, encoding="utf-8")
    print(f"Wrote {path} ({len(doc.splitlines())} lines, {len(GLOSSARY)} definitions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
