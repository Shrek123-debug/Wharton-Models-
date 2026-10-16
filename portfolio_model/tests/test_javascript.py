"""Every JavaScript file in the repo must at least parse.

`apps-script/` holds Google Apps Script helpers and `web/static/` holds the dashboard's own
JavaScript. Neither is imported by Python, so a syntax error in them is invisible to the rest
of the suite until someone pastes the file into a spreadsheet or opens the dashboard.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PKG_ROOT.parent

JS_DIRS = [PKG_ROOT / "web" / "static", REPO_ROOT / "apps-script"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize("js_file", sorted(
    p for d in JS_DIRS for p in d.glob("*.js")), ids=lambda p: p.name)
def test_javascript_files_parse(js_file: Path):
    proc = subprocess.run(["node", "--check", str(js_file)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, f"{js_file.name} does not parse:\n{proc.stderr}"


def test_dashboard_has_a_script_and_a_stylesheet():
    static = PKG_ROOT / "web" / "static"
    assert (static / "app.js").exists()
    assert (static / "styles.css").exists()
    html = (PKG_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert "app.js" in html and "styles.css" in html
    # no CDN: the dashboard must work with the network off
    assert "cdn." not in html and "https://" not in html.split("<script")[1].split(">")[0]
