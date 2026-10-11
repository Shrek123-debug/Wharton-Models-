"""Tests for the interpretability layer: glossary completeness, generated docs, workbook sheet.

The point of these tests is that the *explanations* cannot silently drift away from the code.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG_ROOT))

from src.metric_glossary import GLOSSARY  # noqa: E402

FIELDS = ("label", "unit", "formula", "meaning", "read_as", "action", "caveat")
SUBSTANTIVE = ("formula", "meaning", "read_as", "action", "caveat")


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "build_definitions_doc", PKG_ROOT / "scripts" / "build_definitions_doc.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_glossary_entry_is_complete():
    assert len(GLOSSARY) >= 40, "the glossary should cover the whole output surface"
    for key, entry in GLOSSARY.items():
        for f in FIELDS:
            value = entry.get(f)
            assert isinstance(value, str) and value.strip(), f"{key} is missing '{f}'"
            if f in SUBSTANTIVE:
                assert len(value) > 15, f"{key}.{f} is too thin to be useful"
        assert entry["unit"] in {"pct", "money", "ratio", "count", "years", "days", "text", "score"}, \
            f"{key} has an unsupported unit"


def test_definitions_markdown_is_generated_and_up_to_date(tmp_path):
    gen = _load_generator()
    doc = gen.build_doc()
    for key, entry in GLOSSARY.items():
        assert f"`{key}`" in doc, f"{key} is missing from the generated definitions page"
        assert entry["label"] in doc
    assert "misreading" in doc.lower()

    out = tmp_path / "METRIC_DEFINITIONS.md"
    out.write_text(doc, encoding="utf-8")
    assert out.read_text(encoding="utf-8") == gen.build_doc()


def test_committed_definitions_page_matches_the_glossary():
    """docs/METRIC_DEFINITIONS.md must not drift from src/metric_glossary.py."""
    committed = PKG_ROOT.parent / "docs" / "METRIC_DEFINITIONS.md"
    assert committed.exists(), "docs/METRIC_DEFINITIONS.md is missing"
    text = committed.read_text(encoding="utf-8")
    missing = [k for k in GLOSSARY if f"`{k}`" not in text]
    assert not missing, f"definitions page is out of date, missing: {missing}"


def test_workbook_contains_definitions_sheet_with_every_metric(tmp_path):
    from src.reporting.excel import build_workbook

    results = {
        "meta": {"generated_utc": "x", "seed": 1, "n_sims": 10, "version": "t",
                 "portfolio_name": "t", "input": "t", "python": "3", "platform": "t",
                 "weights_source": "supplied", "data_as_of": "2026-01-01",
                 "data_sources": "bundled snapshot", "offline_mode": "auto"},
        "dashboard": [("Metric", 1.0, "0.0")],
        "holdings_sheet": __import__("pandas").DataFrame({"ticker": ["A"], "weight": [1.0]}),
        "sector_sheet": __import__("pandas").DataFrame({"weight": [1.0], "n_holdings": [1]}),
        "corr": __import__("pandas").DataFrame({"A": [1.0]}, index=["A"]),
        "history_sheet": __import__("pandas").DataFrame({"a": [1]}),
        "mc": {"model": "gaussian", "n_sims": 10}, "mc_sheet": __import__("pandas").DataFrame({"a": [1]}),
        "mc_percentiles": __import__("pandas").DataFrame({"a": [1]}),
        "markov_states": __import__("pandas").DataFrame({"a": [1]}),
        "markov_P": __import__("pandas").DataFrame({"a": [1]}),
        "markov_misc": __import__("pandas").DataFrame({"a": [1]}),
        "bs": {"method": "block", "block_size_days": 20, "n_sims": 10},
        "bs_sheet": __import__("pandas").DataFrame({"a": [1]}),
        "comparison_sheet": __import__("pandas").DataFrame({"a": [1]}),
        "disagreement_sheet": __import__("pandas").DataFrame({"a": [1]}),
        "sensitivity_sheet": __import__("pandas").DataFrame({"a": [1]}),
        "risk_sheet": __import__("pandas").DataFrame({"a": [1]}),
        "recovery_sheet": __import__("pandas").DataFrame({"a": [1]}),
        "stress_sheet": __import__("pandas").DataFrame({"a": [1]}),
        "hypothetical_sheet": __import__("pandas").DataFrame({"a": [1]}),
        "glide_sheet": __import__("pandas").DataFrame({"a": [1]}),
        "glide_impact_sheet": __import__("pandas").DataFrame({"a": [1]}),
        "rebalance_sheet": __import__("pandas").DataFrame({"a": [1]}),
        "rule_flags": [], "thesis_sheet": __import__("pandas").DataFrame({"a": [1]}),
        "dq_sheet": __import__("pandas").DataFrame({"a": [1]}),
        "scorecard": __import__("pandas").DataFrame({"a": [1]}),
        "decision_matrix": __import__("pandas").DataFrame({"a": [1]}),
        "stop_sheet": __import__("pandas").DataFrame({"a": [1]}),
    }
    path = build_workbook(tmp_path / "defs_check.xlsx", results)
    from openpyxl import load_workbook

    ws = load_workbook(path)["Definitions"]
    keys = {row[0].value for row in ws.iter_rows(min_row=4)}
    assert set(GLOSSARY) <= keys, f"workbook Definitions sheet is missing {set(GLOSSARY) - keys}"


def test_sensitivity_fragility_threshold_is_read_at_the_base_return_assumption():
    import pandas as pd

    from src.sensitivity.sensitivity import interpret_grid

    rows = []
    for vm, succ in ((0.7, 0.99), (0.8, 0.97), (0.9, 0.95), (1.0, 0.92), (1.1, 0.90),
                     (1.2, 0.85), (1.3, 0.74), (1.4, 0.70), (1.5, 0.65)):
        for rs in (-0.04, -0.02, 0.0, 0.02, 0.04):
            # pessimistic return shifts fail early; the fragility read must ignore them
            s = succ if rs == 0.0 else max(0.2, succ - 0.25)
            rows.append({"return_shift": rs, "vol_multiplier": vm, "prob_success": s,
                         "median_terminal": 1000.0})
    out = interpret_grid(pd.DataFrame(rows))
    assert out["fragile_vol_threshold"] == 1.3, out
