"""Written report generation (spec sections 97-101, 116)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt


def _h(doc: Document, text: str, level: int = 1):
    doc.add_heading(text, level=level)


def _p(doc: Document, text: str, italic: bool = False, bold: bool = False):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.italic = italic
    run.bold = bold
    return p


def _table(doc: Document, df: pd.DataFrame, pct_cols=(), max_rows: int = 40):
    df = df.head(max_rows)
    t = doc.add_table(rows=1, cols=len(df.columns))
    t.style = "Light Grid Accent 1"
    for i, c in enumerate(df.columns):
        cell = t.rows[0].cells[i]
        cell.text = str(c)
        for r in cell.paragraphs[0].runs:
            r.bold = True
            r.font.size = Pt(8)
    for _, row in df.iterrows():
        cells = t.add_row().cells
        for i, c in enumerate(df.columns):
            v = row[c]
            if isinstance(v, float):
                v = f"{v:.1%}" if c in pct_cols else (f"{v:,.0f}" if abs(v) >= 1000 else f"{v:,.3f}")
            cells[i].text = "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
            for r in cells[i].paragraphs[0].runs:
                r.font.size = Pt(8)


def _img(doc: Document, path: Path, width: float = 6.2):
    if path and Path(path).exists():
        doc.add_picture(str(path), width=Inches(width))


def build_report(path: Path, results: dict) -> Path:
    doc = Document()
    doc.styles["Normal"].font.size = Pt(10)
    m = results["meta"]

    doc.add_heading("Portfolio Modeling, Risk Management, Simulation & Reporting", 0)
    _p(doc, f"Prepared for: {m['portfolio_name']} | Generated {m['generated_utc']} | "
            f"Seed {m['seed']} | {m['n_sims']:,} simulations | Model v{m['version']}", italic=True)
    _p(doc, "All forward-looking figures are model estimates, simulation results, scenarios, or assumptions — "
            "never guarantees.", italic=True)

    # How to read this report
    _h(doc, "How to read this report")
    _p(doc, "Read it as answers to six questions rather than front to back:", italic=True)
    _table(doc, pd.DataFrame([
        {"question": "Can the 2033 obligation actually be funded?", "see": "Section 14 Model Comparison; Section 11 Risk"},
        {"question": "How bad can it get?", "see": "Section 7 Monte Carlo; Section 9 Historical Bootstrap"},
        {"question": "Is this actually diversified?", "see": "Section 2 Portfolio Overview; Section 11 Risk"},
        {"question": "Which decisions dominate the outcome?", "see": "Section 19.5 Rule-Based Flags"},
        {"question": "How much do my assumptions matter?", "see": "Section 15 Sensitivity"},
        {"question": "What would a real crisis do to this mix?", "see": "Section 16 Stress Tests"},
        {"question": "What does any given number mean?", "see": "Appendix A Metric Definitions"},
    ]))
    _p(doc, "Every metric named in this report is defined in Appendix A, generated from the same source "
            "file as the workbook Definitions sheet and the web UI Definitions tab.", italic=True)

    # 1 Executive Summary
    _h(doc, "1. Executive Summary")
    for line in results["exec_summary"]:
        _p(doc, line)
    _img(doc, results["figures"].get("allocation"))

    # 2 Portfolio Overview
    _h(doc, "2. Portfolio Overview")
    _p(doc, results["overview_text"])
    _table(doc, results["holdings_sheet"][["ticker", "asset_class", "sector", "weight", "expected_return", "volatility"]],
           pct_cols=("weight", "expected_return", "volatility"))

    # 3 Current Allocation
    _h(doc, "3. Current Allocation")
    _table(doc, results["sector_sheet"][["weight", "n_holdings"]], pct_cols=("weight",))
    _img(doc, results["figures"].get("sector"))

    # 4 Investment Thesis
    _h(doc, "4. Investment Thesis")
    _p(doc, "Theses below are taken from the input spreadsheet where supplied; missing theses are flagged as THESIS RISK.")
    _table(doc, results["thesis_sheet"], max_rows=20)

    # 5 Historical Performance
    _h(doc, "5. Historical Performance")
    _p(doc, results["historical_text"])
    _img(doc, results["figures"].get("cumulative"))
    _img(doc, results["figures"].get("drawdown"))

    # 6 Risk Analysis
    _h(doc, "6. Risk Analysis")
    _table(doc, results["risk_sheet"], pct_cols=("value",))
    _p(doc, results["risk_text"], italic=True)

    # 7 Correlation Analysis
    _h(doc, "7. Correlation Analysis")
    _img(doc, results["figures"].get("correlation"))
    _p(doc, results["correlation_text"])

    # 8 Concentration Analysis
    _h(doc, "8. Concentration Analysis")
    _p(doc, results["concentration_text"])
    _img(doc, results["figures"].get("concentration"))

    # 9 Monte Carlo Results
    _h(doc, "9. Monte Carlo Results")
    _p(doc, results["mc_text"])
    _img(doc, results["figures"].get("mc_terminal"))
    _img(doc, results["figures"].get("mc_fan"))

    # 10 Markov Model Results
    _h(doc, "10. Markov Model Results")
    _p(doc, results["markov_text"])
    _table(doc, results["markov_P"], pct_cols=tuple(results["markov_P"].columns))

    # 11 Historical Bootstrap Results
    _h(doc, "11. Historical Bootstrap Results")
    _p(doc, results["bs_text"])
    _img(doc, results["figures"].get("bs_terminal"))
    _img(doc, results["figures"].get("bs_fan"))

    # 12 Model Comparison
    _h(doc, "12. Model Comparison")
    _table(doc, results["comparison_sheet"])
    _p(doc, results["disagreement_text"], bold=True)

    # 13 Sensitivity Analysis
    _h(doc, "13. Sensitivity Analysis")
    _p(doc, results["sensitivity_text"])
    _img(doc, results["figures"].get("sens_success"))
    _img(doc, results["figures"].get("sens_terminal"))

    # 14 Crisis Stress Tests
    _h(doc, "14. Crisis Stress Tests")
    _table(doc, results["stress_sheet"], pct_cols=("portfolio_return", "max_drawdown"))
    _img(doc, results["figures"].get("crisis"))
    _h(doc, "14.1 Hypothetical Forward Scenarios (assumptions, not forecasts)", 2)
    _table(doc, results["hypothetical_sheet"], pct_cols=("portfolio_return",))

    # 15 Sector Analysis
    _h(doc, "15. Sector Analysis")
    for line in results["sector_narrative"]:
        _p(doc, line)
    _img(doc, results["figures"].get("sector_contrib"))

    # 16 Rebalancing Framework
    _h(doc, "16. Rebalancing Framework")
    _p(doc, results["rebalance_text"])
    _table(doc, results["rebalance_sheet"], pct_cols=("current_weight", "target", "lower_band", "upper_band", "suggested_trade"))

    # 17 2033 Glide Path
    _h(doc, "17. 2033 Glide Path")
    _img(doc, results["figures"].get("glide"))
    _table(doc, results["glide_impact_sheet"], pct_cols=("prob_depletion", "prob_payments_funded"))
    _p(doc, results["glide_text"], italic=True)

    # 18 Position-Level Risk Discipline
    _h(doc, "18. Position-Level Risk Discipline")
    _p(doc, "These are portfolio risk-discipline rules, not short-term trading signals.")
    for line in results["risk_discipline"]:
        _p(doc, f"- {line}")
    _h(doc, "18.1 Stop-Loss Backtests (historical, not advice)", 2)
    _p(doc, "Hard and trailing stops were backtested on adjusted price history with re-entry after 21 trading days. "
            "A stop is not selected merely because it produced the highest historical return.")
    _table(doc, results["stop_sheet"], pct_cols=("cagr", "max_drawdown", "missed_upside"), max_rows=30)

    # 19 Key Risks
    _h(doc, "19. Key Risks")
    for line in results["key_risks"]:
        _p(doc, f"- {line}")

    # 19.5 Rule-Based Risk Flags (deterministic)
    _h(doc, "19.5 Rule-Based Risk & Rebalancing Flags")
    _p(doc, "Every flag below is produced by an explicit rule with a configured threshold and a calculated value. "
            "These are rule-based portfolio risk flags, not AI-generated recommendations.", italic=True)
    rule_flags = results.get("rule_flags", [])
    if rule_flags:
        rdf = pd.DataFrame(rule_flags)[["id", "severity", "category", "metric", "current_value",
                                        "threshold", "rule", "action"]]
        _table(doc, rdf, max_rows=60)
    else:
        _p(doc, "No rule flags triggered for the current configuration.")

    # 20 Recommended Actions
    _h(doc, "20. Recommended Actions")
    for prio, items in results["recommendations"].items():
        _h(doc, prio, 2)
        for line in items:
            _p(doc, f"- {line}")

    # 21 Methodology
    _h(doc, "21. Methodology")
    for line in results["methodology"]:
        _p(doc, f"- {line}")

    # 22 Assumptions
    _h(doc, "22. Assumptions")
    for line in results["assumptions"]:
        _p(doc, f"- {line}")

    # 23 Data Limitations
    _h(doc, "23. Data Limitations")
    for line in results["limitations"]:
        _p(doc, f"- {line}")

    # Conclusions (spec 116)
    _h(doc, "Final Conclusions")
    for sec, lines in results["conclusions"].items():
        _h(doc, sec, 2)
        for line in lines:
            _p(doc, f"- {line}")

    _h(doc, "Monitoring Checklist")
    for line in results["monitoring"]:
        _p(doc, f"- [ ] {line}")

    # Appendix A: metric definitions (same source as the workbook sheet and the web UI tab)
    from ..metric_glossary import GLOSSARY

    doc.add_page_break()
    _h(doc, "Appendix A. Metric Definitions")
    _p(doc, "Generated from portfolio_model/src/metric_glossary.py — the same source as the workbook "
            "Definitions sheet and the web UI Definitions tab. The 'Trap' column is the way this metric "
            "is most often misread.", italic=True)
    _table(doc, pd.DataFrame([
        {"metric": e["label"], "what_it_is": e["formula"], "how_to_read_it": e["read_as"],
         "trap": e["caveat"]}
        for e in GLOSSARY.values()
    ]), max_rows=len(GLOSSARY))

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path
