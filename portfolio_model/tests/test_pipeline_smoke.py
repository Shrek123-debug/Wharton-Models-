"""End-to-end offline pipeline smoke test.

This is the test that answers "does the whole thing actually run on a clean machine with no
network?" It runs the real pipeline on the real example workbook, with the network disabled,
and checks that every deliverable exists and is internally consistent.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

PKG_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG_ROOT))

from src.pipeline import run  # noqa: E402

EXAMPLE = PKG_ROOT / "data" / "input" / "example_portfolio_full.xlsx"

OPTIONS = {
    "sims": 1200,
    "sensitivity_sims": 200,
    "seed": 11,
    "offline": "always",
    "bootstrap_method": "block",
}


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    out = tmp_path_factory.mktemp("pipeline_run")
    return run(input_path=str(EXAMPLE), out_dir=str(out), overrides=dict(OPTIONS)), out


def test_pipeline_completes_with_no_network(results):
    res, out = results
    assert (out / "spreadsheet" / "portfolio_analysis.xlsx").exists()
    assert (out / "report" / "portfolio_analysis_report.docx").exists()
    figs = list((out / "figures").glob("*.png"))
    assert len(figs) >= 15, f"expected 16 figures, got {len(figs)}"
    assert res["meta"]["offline_mode"] == "always"
    assert res["meta"]["data_as_of"] not in ("", "-")
    assert len(res["data_provenance"]) >= 3
    assert set(res["data_provenance"]["source"]) <= {"cache", "network", "bundled snapshot", "none"}


def test_every_engine_produced_usable_numbers(results):
    res, _ = results
    for key in ("mc_sum", "bs_sum", "mk_sum"):
        s = res[key]
        assert s["median_terminal"] > 0
        assert 0.0 <= s["prob_terminal_gt_start"] <= 1.0
        assert 0.0 <= s["prob_all_payments_funded"] <= 1.0
        assert s["mc_cvar_95"] >= s["mc_var_95"] - 1e-9, "CVaR must be at least as bad as VaR"
        for p in ("p5", "p25", "p50", "p75", "p95"):
            assert s["terminal_percentiles"][p] > 0
        assert (s["terminal_percentiles"]["p5"] <= s["terminal_percentiles"]["p50"]
                <= s["terminal_percentiles"]["p95"])


def test_run_is_deterministic_for_a_fixed_seed(results, tmp_path):
    res, _ = results
    # a second run with the same seed and options must reproduce the same median exactly
    again = run(input_path=str(EXAMPLE), out_dir=str(tmp_path / "repeat"),
                overrides=dict(OPTIONS), render_charts=False)
    assert again["mc_sum"]["median_terminal"] == res["mc_sum"]["median_terminal"]
    assert again["bs_sum"]["prob_all_payments_funded"] == res["bs_sum"]["prob_all_payments_funded"]


def test_rule_flags_are_complete_and_traceable(results):
    res, _ = results
    flags = res["rule_flags"]
    assert flags, "the example portfolio should trigger at least one rule flag"
    required = {"id", "severity", "category", "metric", "current_value", "threshold",
                "rule", "action", "evidence", "format"}
    for f in flags:
        assert required <= set(f), f"flag {f.get('id')} is missing fields"
        assert f["severity"] in {"CRITICAL", "HIGH", "WARNING", "MONITOR", "INFO"}
        assert f["action"].strip(), f"flag {f['id']} has no action"
        assert math.isfinite(f["current_value"]) and math.isfinite(f["threshold"])
    ids = [f["id"] for f in flags]
    assert len(ids) == len(set(ids)), "rule flag ids must be unique"


def test_workbook_sheets_and_definitions(results):
    from openpyxl import load_workbook

    from src.metric_glossary import GLOSSARY

    res, out = results
    wb = load_workbook(out / "spreadsheet" / "portfolio_analysis.xlsx")
    expected = {"Executive Summary", "Holdings", "Sector Allocation", "Correlation Matrix",
                "Historical Performance", "Monte Carlo", "Markov Model", "Historical Bootstrap",
                "Model Comparison", "Sensitivity", "Risk", "Stress Tests", "Glide Path",
                "Rebalancing", "Rule Flags", "Investment Theses", "Data Quality", "Scorecard",
                "Stop-Loss Backtests", "Definitions"}
    assert expected <= set(wb.sheetnames), f"missing sheets: {expected - set(wb.sheetnames)}"
    defs = {row[0].value for row in wb["Definitions"].iter_rows(min_row=4)}
    assert set(GLOSSARY) <= defs


def test_no_silent_nan_in_reported_tables(results):
    res, _ = results
    for name in ("comparison_sheet", "risk_sheet", "glide_impact_sheet", "sensitivity_sheet",
                 "rebalance_sheet", "stress_sheet", "hypothetical_sheet", "holdings_sheet"):
        df = res[name]
        numeric = df.select_dtypes(include=[np.number])
        bad = int(numeric.isna().sum().sum())
        assert bad == 0, f"{name} contains {bad} NaN cells that would render blank in the workbook"


def test_data_quality_flags_explain_provenance(results):
    res, _ = results
    dq = res["dq_sheet"]
    text = " ".join(str(v) for v in dq["detail"].tolist())
    assert "source=" in text, "data provenance rows are missing from the Data Quality sheet"
    assert "survivorship" in text.lower()
    assert "adjusted close" in text.lower() or "total-return" in text.lower()
