"""Chart guide coverage: every dashboard figure has a caption, and every caption is defined.

The chart captions in the web UI and the "Reading the charts" section of the docs page are
generated from `src/metric_glossary.py:CHART_GUIDE`. These tests fail if a chart is added to
the dashboard without a caption, or if a caption references a metric that has no definition.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG_ROOT))

from src.metric_glossary import CHART_GUIDE, GLOSSARY  # noqa: E402


def _payload_charts():
    from src.pipeline import run
    from web.serialize import build_payload

    res = run(input_path=str(PKG_ROOT / "data" / "input" / "example_portfolio_minimal.xlsx"),
              out_dir=str(Path(tempfile.mkdtemp())),
              overrides={"sims": 300, "sensitivity_sims": 200, "offline": "always"},
              render_charts=False)
    return build_payload(res)


def test_every_dashboard_chart_has_a_caption():
    payload = _payload_charts()
    built = set(payload["charts"])
    guided = set(CHART_GUIDE)
    assert built == guided, f"charts without captions: {sorted(built - guided)}; captions with no chart: {sorted(guided - built)}"
    assert payload["chart_notes"] == CHART_GUIDE


def test_captions_only_reference_defined_metrics():
    dangling = [(chart, key) for chart, entry in CHART_GUIDE.items() for key in entry["keys"] if key not in GLOSSARY]
    assert not dangling, f"chart captions reference undefined metrics: {dangling}"


def test_captions_are_substantive():
    for chart, entry in CHART_GUIDE.items():
        assert str(entry["title"]).strip(), f"{chart}.title is empty"
        for field in ("shows", "read", "watch"):
            assert len(str(entry[field])) > 40, f"{chart}.{field} is too thin to teach anything"
        assert entry["keys"], f"{chart} links to no metric definitions"


def test_docs_page_renders_the_chart_section():
    doc = (PKG_ROOT.parent / "docs" / "METRIC_DEFINITIONS.md").read_text(encoding="utf-8")
    assert "## Reading the charts" in doc
    for entry in CHART_GUIDE.values():
        assert f"### {entry['title']}" in doc, f"docs page is missing the caption for {entry['title']}"


def test_web_ui_renders_captions_from_the_payload():
    js = (PKG_ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "chart_notes" in js
    assert "chart-note" in js
    css = (PKG_ROOT / "web" / "static" / "styles.css").read_text(encoding="utf-8")
    assert ".chart-note" in css
