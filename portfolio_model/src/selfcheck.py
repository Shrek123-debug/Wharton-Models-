"""Environment + data self-test: `python main.py --check` and the web UI health panel.

Answers one question before you waste ten minutes on a simulation: *can this machine run
the models?* It verifies the Python version, the required third-party packages, the input
workbook, the local price data (cache and bundled offline snapshots), the config file and
the output directory. Every failure prints a fix you can copy-paste.

`collect_checks()` returns the same findings as structured data so the web UI can show
them before you press Run.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

MIN_PYTHON = (3, 10)

REQUIRED_PACKAGES = [
    ("numpy", "array math for the simulation engines"),
    ("pandas", "tables, time series and return calculations"),
    ("scipy", "optimisation and distribution helpers"),
    ("openpyxl", "reading your input workbook and writing the output workbook"),
    ("docx", "writing the Word report (package python-docx)"),
    ("yaml", "reading config/model_config.yaml (package PyYAML)"),
    ("matplotlib", "rendering the PNG figures"),
]
OPTIONAL_PACKAGES = [
    ("yfinance", "downloads live market history; not needed when data/offline has the tickers"),
    ("fastapi", "serves the web UI (run_web.py)"),
    ("uvicorn", "runs the web UI server"),
]


def collect_checks(config_path: str | None = None, input_path: str | None = None) -> list[dict]:
    """Run every environment check and return [{area, status: ok|warn|fail, message, fix}]."""
    from .config import PACKAGE_ROOT, ConfigError, load_config, resolve

    checks: list[dict] = []

    def add(area: str, status: str, message: str, fix: str = "") -> None:
        checks.append({"area": area, "status": status, "message": message, "fix": fix})

    # 1. python version -----------------------------------------------------
    v = sys.version_info
    if (v.major, v.minor) >= MIN_PYTHON:
        add("python", "ok", f"Python {v.major}.{v.minor}.{v.micro} (needs {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+)")
    else:
        add("python", "fail", f"Python {v.major}.{v.minor} is too old",
            f"install Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+")

    # 2. packages ------------------------------------------------------------
    for mod, why in REQUIRED_PACKAGES:
        try:
            importlib.import_module(mod)
            add("packages", "ok", f"{mod} installed ({why})")
        except ImportError:
            pip_name = {"docx": "python-docx", "yaml": "PyYAML"}.get(mod, mod)
            add("packages", "fail", f"{mod} missing", f"pip install {pip_name}")
    for mod, why in OPTIONAL_PACKAGES:
        try:
            importlib.import_module(mod)
            add("packages", "ok", f"{mod} installed ({why})")
        except ImportError:
            add("packages", "warn", f"{mod} not installed ({why})", f"pip install {mod}")

    # 3. runtime caches ------------------------------------------------------
    from .runtime_env import CACHE_ROOT, configure_local_runtime

    set_vars = configure_local_runtime()
    if set_vars:
        add("caches", "ok", f"writable cache root: {CACHE_ROOT}")
    else:
        add("caches", "fail", f"no writable cache directory (tried {CACHE_ROOT})",
            "set MPLCONFIGDIR to a writable directory")

    # 4. config --------------------------------------------------------------
    try:
        cfg = load_config(config_path)
        add("config", "ok", f"config loaded and validated: "
                            f"{config_path or PACKAGE_ROOT / 'config' / 'model_config.yaml'}")
    except ConfigError as exc:
        add("config", "fail", str(exc).replace("\n", " ").strip(),
            "fix the named key(s) in config/model_config.yaml, or restore the shipped config")
        return checks
    except Exception as exc:
        add("config", "fail", f"config could not be read: {exc}", "fix config/model_config.yaml (YAML syntax)")
        return checks

    # 5. input workbook ------------------------------------------------------
    inp = Path(input_path or resolve(cfg["input"]["spreadsheet"]))
    holdings = []
    if inp.exists():
        try:
            from .ingestion.ingest import ingest

            holdings = [str(t).upper() for t in ingest(str(inp), cfg["input"].get("sheet")).holdings["ticker"]]
            add("input", "ok", f"input workbook readable: {inp} ({len(holdings)} holdings: "
                               f"{', '.join(holdings[:12])})")
        except Exception as exc:
            add("input", "fail", f"input workbook {inp} could not be parsed: {exc}",
                "needs a header row with a ticker column plus weights, market values, or shares x price")
    else:
        add("input", "fail", f"input workbook not found: {inp}",
            "set input.spreadsheet in the config or pass --input")

    # 6. price data ----------------------------------------------------------
    cache = resolve(cfg["historical_data"]["cache_dir"])
    bundled = resolve(cfg["historical_data"].get("bundled_dir") or "data/offline")
    wanted = [t for t in dict.fromkeys(holdings + [cfg["historical_data"]["benchmarks"]["equity"],
                                                   cfg["historical_data"]["benchmarks"]["bonds"]])
              if t and t != "CASH"]

    def _available(t: str) -> str | None:
        if list(cache.glob(f"{t}__*")):
            return "cache"
        if (bundled / f"{t}.parquet").exists() or (bundled / f"{t}.csv").exists():
            return "bundled"
        return None

    if bundled.exists():
        add("data", "ok", f"offline dataset present: {bundled} ({len(list(bundled.glob('*.parquet')))} tickers)")
    else:
        add("data", "warn", f"no offline dataset directory ({bundled})",
            "python scripts/build_offline_dataset.py (while online)")

    covered = [t for t in wanted if _available(t)]
    missing = [t for t in wanted if not _available(t)]
    if covered:
        add("data", "ok", f"local price data available for: {', '.join(covered)}")
    if missing:
        add("data", "warn", f"no local data for: {', '.join(missing)}",
            f"python scripts/build_offline_dataset.py --tickers {' '.join(missing)} (while online)")

    # 7. outputs writable -----------------------------------------------------
    out = PACKAGE_ROOT / "outputs"
    try:
        (out / "figures").mkdir(parents=True, exist_ok=True)
        probe = out / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        add("outputs", "ok", f"output directory writable: {out}")
    except Exception as exc:
        add("outputs", "fail", f"output directory not writable ({out}): {exc}",
            "run from a writable location or pass --out")

    return checks


def run_selfcheck(config_path: str | None = None, input_path: str | None = None) -> bool:
    checks = collect_checks(config_path, input_path)
    print("\n=== Portfolio Model Self-Test ===")
    marks = {"ok": "[ok]  ", "warn": "[warn]", "fail": "[FAIL]"}
    for c in checks:
        line = f"  {marks[c['status']]} {c['message']}"
        if c["fix"]:
            line += f"  ->  {c['fix']}"
        print(line)

    problems = sum(1 for c in checks if c["status"] == "fail")
    print(f"\nSelf-test {'PASSED' if problems == 0 else f'found {problems} blocking problem(s)'}")
    if problems == 0:
        print("Next: python main.py            (full run)   |   python run_web.py   (interactive UI)")
    return problems == 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(0 if run_selfcheck() else 1)
