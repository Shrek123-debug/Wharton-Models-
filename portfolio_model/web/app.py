"""Local portfolio-analysis web UI (FastAPI).

Runs the deterministic pipeline on uploaded spreadsheets entirely on this machine.
No LLM / AI API / cloud inference is used anywhere in this application.
"""
from __future__ import annotations

import json
import math
import re
import sys
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

WEB_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = WEB_DIR.parent
sys.path.insert(0, str(PACKAGE_ROOT))

from src.compare import compare_metric_maps, compare_runs, flag_deltas, headline_metrics  # noqa: E402
from src.config import ConfigError, load_config, resolve  # noqa: E402
from src.metric_glossary import ALIASES, GLOSSARY  # noqa: E402
from src.pipeline import PipelineError, run  # noqa: E402
from src.selfcheck import collect_checks  # noqa: E402

from .serialize import build_payload, df_records  # noqa: E402

UPLOAD_DIR = PACKAGE_ROOT / "data" / "input" / "uploads"
OUT_DIR = PACKAGE_ROOT / "outputs" / "web"
RUNS_DIR = OUT_DIR / "runs"
RUNS_INDEX = RUNS_DIR / "index.json"
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_JOBS = 8
MAX_RUNS = 50

app = FastAPI(title="Portfolio Analysis — Local Web UI")
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")


@app.exception_handler(ConfigError)
async def _config_error(_: Request, exc: ConfigError) -> JSONResponse:
    """A broken config is a client-side fix, not a server crash: say which key."""
    return JSONResponse(status_code=400, content={"detail": str(exc)})

JOBS: dict[str, dict] = {}
LOCK = threading.Lock()
LAST_INPUT: Path | None = None


def _prune_jobs() -> None:
    """Keep the in-memory job table bounded (a long-lived server must not grow forever)."""
    if len(JOBS) <= MAX_JOBS:
        return
    for job_id in sorted(JOBS, key=lambda j: JOBS[j]["started"])[: len(JOBS) - MAX_JOBS]:
        JOBS.pop(job_id, None)


def _running_job() -> dict | None:
    for j in JOBS.values():
        if j["status"] == "running":
            return j
    return None


# ---- saved runs ---------------------------------------------------------------------------
# A dashboard session is disposable; the numbers you made a decision on should not be. Every
# completed run is written to disk as a headline summary plus its full payload, so history
# survives a restart and two saved runs can be compared with the same semantics as a what-if.

def _load_runs() -> list[dict]:
    if not RUNS_INDEX.exists():
        return []
    try:
        data = json.loads(RUNS_INDEX.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def _save_runs(runs: list[dict]) -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    runs = runs[-MAX_RUNS:]
    RUNS_INDEX.write_text(json.dumps(runs, indent=2), encoding="utf-8")
    # drop payload files for runs that have aged out of the index
    keep = {r["id"] for r in runs}
    for path in RUNS_DIR.glob("*.json"):
        if path.name == RUNS_INDEX.name or path.stem in keep:
            continue
        path.unlink(missing_ok=True)


def _record_run(job: dict, input_path: Path, overrides: dict, variant: dict | None,
                results: dict) -> None:
    headline = {k: float(v) for k, v in headline_metrics(results).items()
                if v is not None and math.isfinite(float(v))}
    summary = {
        "id": job["id"],
        "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "input": Path(input_path).name,
        "overrides": overrides or {},
        "variant": variant or {},
        "seed": results["meta"].get("seed"),
        "sims": results["meta"].get("n_sims"),
        "data_sources": results["meta"].get("data_sources"),
        "data_as_of": results["meta"].get("data_as_of"),
        # elapsed is only assigned in the caller's finally block, so measure it here
        "elapsed_s": round(time.time() - job["started"], 1),
        "headline": headline,
    }
    runs = [r for r in _load_runs() if r.get("id") != job["id"]] + [summary]
    _save_runs(runs)
    payload_path = RUNS_DIR / f"{job['id']}.json"
    payload_path.write_text(json.dumps(job["payload"], default=str), encoding="utf-8")


def _execute(job: dict, input_path: Path, overrides: dict, variant: dict | None = None) -> None:
    try:
        results = run(input_path=str(input_path), out_dir=str(OUT_DIR), overrides=overrides or None)
        job["payload"] = build_payload(results)
        job["xlsx"] = str(OUT_DIR / "spreadsheet" / "portfolio_analysis.xlsx")
        job["docx"] = str(OUT_DIR / "report" / "portfolio_analysis_report.docx")
        if variant:
            # Same portfolio, different assumption: the diff is what teaches the metrics.
            alt = run(input_path=str(input_path), out_dir=str(OUT_DIR / "variant"),
                      overrides=variant, render_charts=False)
            job["payload"]["comparison"] = {
                "variant_overrides": variant,
                "table": df_records(compare_runs(results, alt, "baseline", "variant")),
                "flags": df_records(flag_deltas(results, alt)),
            }
        job["status"] = "done"
        _record_run(job, input_path, overrides, variant, results)
    except PipelineError as exc:
        job["status"] = "error"
        job["error"] = f"Run option problem: {exc}"
    except ConfigError as exc:
        job["status"] = "error"
        job["error"] = f"Config problem: {exc}"
    except SystemExit as exc:
        job["status"] = "error"
        job["error"] = f"Input problem: {exc}"
    except ValueError as exc:
        job["status"] = "error"
        job["error"] = f"Input problem: {exc}"
    except Exception as exc:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        job["elapsed"] = time.time() - job["started"]


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "local_only": True, "no_ai": True}


@app.get("/api/glossary")
def glossary() -> dict:
    """Metric definitions (single source of truth) plus label -> definition mapping."""
    return {"entries": GLOSSARY, "aliases": ALIASES}


@app.get("/api/selfcheck")
def selfcheck() -> dict:
    """Environment/data readiness report shown in the UI before a run."""
    checks = collect_checks()
    return {
        "ok": not any(c["status"] == "fail" for c in checks),
        "checks": checks,
        "blocking": [c for c in checks if c["status"] == "fail"],
        "warnings": [c for c in checks if c["status"] == "warn"],
    }


@app.get("/api/guide")
def guide() -> dict:
    """The tutorial and the metric-definitions page, as markdown, for the Guide tab."""
    docs = PACKAGE_ROOT.parent / "docs"
    out: dict[str, str] = {}
    for name in ("TUTORIAL.md", "METRIC_DEFINITIONS.md"):
        p = docs / name
        out[name[:-3].lower()] = p.read_text(encoding="utf-8") if p.exists() else ""
    return out


@app.get("/api/config")
def get_config() -> dict:
    cfg = load_config()
    return {
        "sims": cfg["simulation"]["n_simulations"],
        "seed": cfg["simulation"]["random_seed"],
        "model": cfg["simulation"]["model"],
        "glide_method": cfg["glide_path"]["method"],
        "glide_end_equity": cfg["glide_path"]["end_equity"],
        "band": cfg["rebalancing"]["band"],
        "rebalancing_enabled": cfg["rebalancing"]["enabled"],
        "transaction_cost": cfg["rebalancing"]["transaction_cost"],
        "corr_threshold": cfg["risk"]["correlation_threshold"],
        "max_position": cfg["risk"]["max_position_weight"],
        "max_sector": cfg["risk"]["max_sector_weight"],
        "max_group": cfg["risk"]["max_correlated_group_weight"],
        "min_cash": cfg["risk"]["min_cash_weight"],
        "risk_free_rate": cfg["risk"]["risk_free_rate"],
        "inflation_base": cfg["risk"]["inflation_base"],
        "bootstrap_method": cfg["bootstrap"]["method"],
        "block_size_days": cfg["bootstrap"]["block_size_days"],
        "sensitivity_sims": cfg["sensitivity"]["n_simulations"],
        "default_input": cfg["input"]["spreadsheet"],
        "offline": cfg["historical_data"].get("offline") or "auto",
        "start_date": cfg["historical_data"]["start_date"],
        "end_date": cfg["historical_data"].get("end_date"),
        "data_as_of_note": "prices resolve from data/cache then data/offline snapshots",
    }


@app.post("/api/analyze")
async def analyze(file: UploadFile | None = File(None), options: str = Form("{}"),
                  variant: str = Form("")) -> dict:
    global LAST_INPUT
    with LOCK:
        if _running_job() is not None:
            raise HTTPException(status_code=409, detail="An analysis is already running. Wait for it to finish.")

    try:
        overrides = json.loads(options or "{}")
        if not isinstance(overrides, dict):
            raise ValueError
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid options payload.") from None

    variant_overrides: dict | None = None
    if variant and variant.strip():
        variant_overrides = {}
        for pair in variant.split(","):
            if not pair.strip():
                continue
            if "=" not in pair:
                raise HTTPException(status_code=400,
                                    detail=f"Variant {pair.strip()!r} must be KEY=VALUE.")
            key, raw = pair.split("=", 1)
            key = key.strip()
            raw = raw.strip()
            if raw.lower() in ("true", "false"):
                value: object = raw.lower() == "true"
            try:
                value = int(raw)
            except ValueError:
                try:
                    value = float(raw)
                except ValueError:
                    value = raw
            variant_overrides[key] = value
        if not variant_overrides:
            variant_overrides = None

    input_path = LAST_INPUT
    if file is not None and file.filename:
        name = file.filename
        if not name.lower().endswith(".xlsx"):
            raise HTTPException(status_code=400, detail="Only .xlsx spreadsheets are supported.")
        data = await file.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=400, detail="File too large (max 15 MB).")
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", name)
        input_path = UPLOAD_DIR / f"{int(time.time())}_{safe}"
        input_path.write_bytes(data)
        LAST_INPUT = input_path

    if input_path is None:
        cfg = load_config()
        candidate = resolve(cfg["input"]["spreadsheet"])
        if not candidate.exists():
            raise HTTPException(status_code=400,
                                detail="Upload a portfolio .xlsx first (configured default input not found).")
        input_path = candidate

    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "status": "running", "started": time.time(), "elapsed": None,
           "input": str(input_path), "overrides": overrides, "error": None,
           "payload": None, "xlsx": None, "docx": None}
    with LOCK:
        JOBS[job_id] = job
        _prune_jobs()
    threading.Thread(target=_execute, args=(job, input_path, overrides, variant_overrides),
                     daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/job/{job_id}")
def job_status(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job.")
    return {"id": job["id"], "status": job["status"], "elapsed": job["elapsed"],
            "error": job["error"], "input": job["input"]}


@app.get("/api/results/{job_id}")
def job_results(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job.")
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail=f"Job is {job['status']}.")
    return job["payload"]


@app.get("/api/latest")
def latest() -> dict:
    done = [j for j in JOBS.values() if j["status"] == "done"]
    if not done:
        raise HTTPException(status_code=404, detail="No completed analysis yet.")
    job = max(done, key=lambda j: j["started"])
    return {"id": job["id"], "payload": job["payload"]}


@app.get("/api/runs")
def saved_runs() -> dict:
    """Every completed run this machine has produced, newest first."""
    return {"runs": sorted(_load_runs(), key=lambda r: r.get("finished_utc", ""), reverse=True),
            "limit": MAX_RUNS}


@app.get("/api/runs/compare")
def compare_saved_runs(a: str, b: str) -> dict:
    """Compare two saved runs by their headline numbers."""
    runs = {r["id"]: r for r in _load_runs()}
    for run_id in (a, b):
        if run_id not in runs:
            raise HTTPException(status_code=404, detail=f"Unknown saved run: {run_id}")
    ra, rb = runs[a], runs[b]
    table = compare_metric_maps(ra["headline"], rb["headline"],
                                label_a=f"A · {ra['finished_utc']}",
                                label_b=f"B · {rb['finished_utc']}")
    return {"a": ra, "b": rb, "table": df_records(table)}


@app.get("/api/runs/{run_id}")
def saved_run(run_id: str) -> dict:
    """The full payload of a saved run, if its file is still on disk."""
    path = RUNS_DIR / f"{run_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="That run's full results are no longer stored.")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise HTTPException(status_code=500, detail=f"Saved run could not be read: {exc}") from exc


@app.get("/api/export/{job_id}/{kind}")
def export(job_id: str, kind: str) -> FileResponse:
    job = JOBS.get(job_id)
    if job is None or job["status"] != "done":
        raise HTTPException(status_code=404, detail="No completed analysis for this job.")
    if kind == "xlsx":
        path = Path(job["xlsx"])
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif kind == "docx":
        path = Path(job["docx"])
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        raise HTTPException(status_code=400, detail="kind must be xlsx or docx.")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Export file missing.")
    return FileResponse(path, media_type=media, filename=path.name)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "static" / "index.html")
