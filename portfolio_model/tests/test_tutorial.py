"""Tests for the tutorial layer: example workbooks, docs, and the web UI's interpretability routes."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parent.parent
DOCS = PKG_ROOT.parent / "docs"
sys.path.insert(0, str(PKG_ROOT))

from src.ingestion.ingest import ingest  # noqa: E402
from src.validation.validate import validate  # noqa: E402
from src.config import load_config  # noqa: E402

EXAMPLES = {
    "example_portfolio_minimal.xlsx": {"CASH", "IEF", "VOO", "XOM"},
    "example_portfolio_full.xlsx": {"ADBE", "CASH", "DIS", "DUOL", "IEF", "SHY", "VOO", "XOM"},
}


@pytest.mark.parametrize("name,expected", sorted(EXAMPLES.items()))
def test_example_workbooks_ingest_and_validate(name, expected):
    path = PKG_ROOT / "data" / "input" / name
    assert path.exists(), f"{name} is missing from data/input"
    res = ingest(str(path))
    assert set(res.holdings["ticker"]) == expected
    val = validate(res.holdings, load_config())
    assert not val.errors, f"{name} failed validation: {val.errors}"
    assert abs(val.holdings["weight"].sum() - 1.0) < 1e-9


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_example_workbooks_carry_an_instructions_sheet(name):
    from openpyxl import load_workbook

    wb = load_workbook(PKG_ROOT / "data" / "input" / name)
    assert "Instructions" in wb.sheetnames, f"{name} has no Instructions sheet"
    text = " ".join(str(c.value) for row in wb["Instructions"].iter_rows() for c in row if c.value)
    for must in ("Ticker", "Weight", "python main.py", "METRIC_DEFINITIONS"):
        assert must in text, f"Instructions sheet in {name} does not mention {must}"


def test_example_workbook_builder_is_reproducible(tmp_path):
    """The example workbooks are generated from a spec, so regenerating must not change holdings."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_example_workbooks", PKG_ROOT / "scripts" / "build_example_workbooks.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.build(tmp_path)
    for name, expected in EXAMPLES.items():
        assert set(ingest(str(tmp_path / name)).holdings["ticker"]) == expected


def test_tutorial_and_definitions_pages_exist():
    tutorial = DOCS / "TUTORIAL.md"
    definitions = DOCS / "METRIC_DEFINITIONS.md"
    assert tutorial.exists() and definitions.exists()
    text = tutorial.read_text(encoding="utf-8")
    for must in ("--check", "--offline", "requirements.txt", "METRIC_DEFINITIONS.md",
                 "example_portfolio_full.xlsx", "Troubleshooting"):
        assert must in text, f"TUTORIAL.md does not cover {must}"
    assert len(text) > 4000, "the tutorial is too thin to be a tutorial"


def test_web_ui_exposes_interpretability_routes():
    from web.app import app

    paths = {r.path for r in app.routes}
    for route in ("/api/glossary", "/api/selfcheck", "/api/guide", "/api/analyze",
                  "/api/results/{job_id}", "/api/export/{job_id}/{kind}"):
        assert route in paths, f"missing route {route}"


def test_web_ui_renders_definitions_and_tutorial_tabs():
    js = (PKG_ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
    html = (PKG_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id: "defs"' in js and 'id: "guide"' in js
    assert "defKeyFor" in js and "infoBtn" in js and "renderDefs" in js
    assert "/api/glossary" in js and "/api/selfcheck" in js and "/api/guide" in js
    assert 'id="opt-offline"' in html and 'id="env-panel"' in html


def test_glossary_lookup_maps_ui_labels():
    from src.metric_glossary import GLOSSARY, lookup

    assert lookup("MC Success") == "prob_terminal_gt_start"
    assert lookup("VaR 95% (monthly, historical)") == "var"
    assert lookup("Effective number of independent bets") == "effective_n"
    assert lookup("prob_all_payments_funded") == "prob_all_payments_funded"
    assert lookup("something not in the report at all") is None
    for key in list(GLOSSARY)[:10]:
        assert lookup(GLOSSARY[key]["label"]) == key
