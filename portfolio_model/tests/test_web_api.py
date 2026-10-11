"""Web API contract tests.

The dashboard is the surface most people actually use, so its routes are tested as an API:
what it returns, what it rejects, and that a completed run carries everything the UI needs to
render an interpretable page (captions, cluster table, rule flags, exports).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PKG_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG_ROOT))

from src.metric_glossary import ALIASES, GLOSSARY  # noqa: E402
from web import app as webapp  # noqa: E402

client = TestClient(webapp.app)


@pytest.fixture(scope="module")
def completed_job():
    """One real offline analysis, reused by the tests that need a finished job."""
    resp = client.post("/api/analyze", data={"options": '{"sims":400,"sensitivity_sims":200,"offline":"always"}'})
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]

    deadline = time.time() + 240
    while time.time() < deadline:
        status = client.get(f"/api/job/{job_id}").json()
        if status["status"] == "done":
            return job_id
        if status["status"] == "error":
            pytest.fail(f"analysis job failed: {status.get('error')}")
        time.sleep(1)
    pytest.fail("analysis job did not finish in time")


def test_glossary_route_serves_the_single_source_of_truth():
    body = client.get("/api/glossary").json()
    assert set(body["entries"]) == set(GLOSSARY)
    assert set(body["aliases"]) == set(ALIASES)


def test_selfcheck_route_reports_every_area():
    body = client.get("/api/selfcheck").json()
    areas = {c["area"] for c in body["checks"]}
    assert {"python", "packages", "caches", "config", "input", "data", "outputs"} <= areas
    assert body["ok"] is True, [c for c in body["checks"] if c["status"] != "ok"]


def test_guide_route_returns_both_documents():
    body = client.get("/api/guide").json()
    assert len(body["tutorial"]) > 4000
    assert len(body["metric_definitions"]) > 10000


def test_config_route_exposes_the_data_controls_the_ui_offers():
    body = client.get("/api/config").json()
    for key in ("offline", "start_date", "end_date"):
        assert key in body, f"/api/config is missing {key}"


def test_invalid_options_payload_is_rejected_before_any_simulation():
    assert client.post("/api/analyze", data={"options": "not json"}).status_code == 400
    assert client.post("/api/analyze", data={"options": '[1,2,3]'}).status_code == 400


def test_non_xlsx_upload_is_rejected():
    resp = client.post("/api/analyze", files={"file": ("notes.txt", b"hello", "text/plain")},
                       data={"options": "{}"})
    assert resp.status_code == 400
    assert "xlsx" in resp.json()["detail"]


def test_export_endpoints_and_their_error_paths(completed_job):
    assert client.get(f"/api/export/{completed_job}/xlsx").status_code == 200
    assert client.get(f"/api/export/{completed_job}/docx").status_code == 200
    assert client.get(f"/api/export/{completed_job}/pdf").status_code == 400
    assert client.get("/api/export/doesnotexist/xlsx").status_code == 404


def test_results_payload_carries_everything_the_ui_renders(completed_job):
    payload = client.get(f"/api/results/{completed_job}").json()
    for key in ("meta", "dashboard", "charts", "chart_notes", "tables", "texts", "rule_flags"):
        assert key in payload, f"payload missing {key}"
    assert set(payload["charts"]) == set(payload["chart_notes"]), "a chart shipped without a caption"
    assert "clusters" in payload["tables"]
    assert payload["meta"]["data_sources"], "payload must report where the prices came from"
    assert payload["meta"]["offline_mode"] == "always"


def test_job_table_stays_bounded():
    """A long-lived server must not accumulate jobs forever."""
    webapp.JOBS.clear()
    for i in range(webapp.MAX_JOBS + 5):
        webapp.JOBS[f"job{i}"] = {"id": f"job{i}", "status": "done", "started": 1000 + i}
    webapp._prune_jobs()
    assert len(webapp.JOBS) == webapp.MAX_JOBS
    kept = {j for j in webapp.JOBS}
    assert "job0" not in kept and f"job{webapp.MAX_JOBS + 4}" in kept
    webapp.JOBS.clear()


def test_a_broken_config_returns_400_naming_the_key_not_a_500(monkeypatch):
    from src.config import ConfigError

    def boom(*a, **k):
        raise ConfigError("Configuration problem in model_config.yaml:\n"
                          "  - risk.max_sector_weight is missing (number).")

    monkeypatch.setattr(webapp, "load_config", boom)
    resp = client.get("/api/config")
    assert resp.status_code == 400, resp.text
    assert "risk.max_sector_weight is missing" in resp.json()["detail"]


def test_ui_surfaces_a_config_problem_instead_of_silently_using_defaults():
    js = (PKG_ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "showConfigProblem" in js
    assert 'if (!res.ok)' in js
    css = (PKG_ROOT / "web" / "static" / "styles.css").read_text(encoding="utf-8")
    assert ".env-config-problem" in css


def test_df_records_accepts_a_plain_list_of_dicts():
    """flag_deltas returns rows, not a DataFrame; df_records must handle both."""
    from web.serialize import df_records

    rows = [{"flag": "DD-04", "severity": "WARNING", "metric": "P(>20% dd)", "value": 0.27}]
    out = df_records(rows)
    assert out == rows
    assert df_records([]) == [] and df_records(None) == []


def test_variant_comparison_is_attached_to_the_results_payload():
    resp = client.post("/api/analyze", data={"options": '{"sims":400,"sensitivity_sims":200,"offline":"always"}',
                                             "variant": "glide_end_equity=0.35"})
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]
    deadline = time.time() + 240
    payload = None
    while time.time() < deadline:
        status = client.get(f"/api/job/{job_id}").json()
        if status["status"] == "done":
            payload = client.get(f"/api/results/{job_id}").json()
            break
        if status["status"] == "error":
            pytest.fail(f"variant run failed: {status.get('error')}")
        time.sleep(1)
    assert payload is not None, "variant run did not finish"

    comp = payload.get("comparison")
    assert comp, "no comparison attached when a variant was requested"
    assert comp["variant_overrides"] == {"glide_end_equity": 0.35}
    assert len(comp["table"]) > 8
    row = next(r for r in comp["table"] if r["metric"].startswith("Median terminal value"))
    assert {"baseline", "variant", "change", "moves"} <= set(row)
    assert row["moves"] in ("better", "worse", "unchanged")


def test_malformed_variant_is_rejected_before_any_simulation():
    resp = client.post("/api/analyze", data={"options": "{}", "variant": "glide_end_equity"})
    assert resp.status_code == 400
    assert "KEY=VALUE" in resp.json()["detail"]


def test_what_if_tab_exists_in_the_ui():
    js = (PKG_ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'id: "whatif"' in js and "renderWhatIf" in js
    html = (PKG_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="opt-variant"' in html
