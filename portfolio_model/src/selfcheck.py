"""Environment + data self-test: `python main.py --check`.

Answers one question before you waste ten minutes on a simulation: *can this machine run
the models?* It verifies the Python version, the required third-party packages, the input
workbook, the local price data (cache and bundled offline snapshots), the config file, and
the output directory. Every failure prints a fix you can copy-paste.
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


def _ok(msg: str) -> None:
    print(f"  [ok]   {msg}")


def _warn(msg: str) -> None:
    print(f"  [warn] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def run_selfcheck(config_path: str | None = None, input_path: str | None = None) -> bool:
    from .config import PACKAGE_ROOT, load_config, resolve

    print("\n=== Portfolio Model Self-Test ===")
    problems = 0

    # 1. python version -----------------------------------------------------
    v = sys.version_info
    if (v.major, v.minor) >= MIN_PYTHON:
        _ok(f"Python {v.major}.{v.minor}.{v.micro} (needs {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+)")
    else:
        _fail(f"Python {v.major}.{v.minor} is too old; install Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+")
        problems += 1

    # 2. packages ------------------------------------------------------------
    for mod, why in REQUIRED_PACKAGES:
        try:
            importlib.import_module(mod)
            _ok(f"{mod} installed ({why})")
        except ImportError:
            pip_name = {"docx": "python-docx", "yaml": "PyYAML"}.get(mod, mod)
            _fail(f"{mod} missing — pip install {pip_name}  ({why})")
            problems += 1
    for mod, why in OPTIONAL_PACKAGES:
        try:
            importlib.import_module(mod)
            _ok(f"{mod} installed ({why})")
        except ImportError:
            _warn(f"{mod} not installed — {why}")

    # 3. runtime caches ------------------------------------------------------
    from .runtime_env import CACHE_ROOT, configure_local_runtime

    set_vars = configure_local_runtime()
    if set_vars:
        _ok(f"writable cache root: {CACHE_ROOT} ({', '.join(sorted(set_vars))})")
    else:
        _fail(f"no writable cache directory (tried {CACHE_ROOT}); set MPLCONFIGDIR yourself")
        problems += 1

    # 4. config --------------------------------------------------------------
    try:
        cfg = load_config(config_path)
        _ok(f"config loaded: {config_path or PACKAGE_ROOT / 'config' / 'model_config.yaml'}")
    except Exception as exc:
        _fail(f"config could not be read: {exc}")
        return False

    # 5. input workbook ------------------------------------------------------
    inp = Path(input_path or resolve(cfg["input"]["spreadsheet"]))
    if inp.exists():
        try:
            from .ingestion.ingest import ingest

            res = ingest(str(inp), cfg["input"].get("sheet"))
            _ok(f"input workbook readable: {inp} ({len(res.holdings)} holdings: "
                f"{', '.join(res.holdings['ticker'].head(12))})")
        except Exception as exc:
            _fail(f"input workbook {inp} could not be parsed: {exc}")
            problems += 1
    else:
        _fail(f"input workbook not found: {inp} (set input.spreadsheet in the config or pass --input)")
        problems += 1

    # 6. price data ----------------------------------------------------------
    cache = resolve(cfg["historical_data"]["cache_dir"])
    bundled = resolve(cfg["historical_data"].get("bundled_dir") or "data/offline")
    try:
        from .ingestion.ingest import ingest as _ing

        held = [t.upper() for t in _ing(str(inp), cfg["input"].get("sheet")).holdings["ticker"]]
    except Exception:
        held = []
    wanted = held + [cfg["historical_data"]["benchmarks"]["equity"], cfg["historical_data"]["benchmarks"]["bonds"]]
    wanted = [t for t in dict.fromkeys(wanted) if t and t != "CASH"]

    def _available(t: str) -> str | None:
        if list(cache.glob(f"{t}__*")):
            return "cache"
        if (bundled / f"{t}.parquet").exists() or (bundled / f"{t}.csv").exists():
            return "bundled"
        return None

    if not cache.exists():
        _warn(f"price cache directory does not exist yet: {cache}")
    if bundled.exists():
        n_bundled = len(list(bundled.glob("*.parquet")))
        _ok(f"offline dataset present: {bundled} ({n_bundled} tickers)")
    else:
        _warn(f"no offline dataset directory ({bundled}); offline runs will need --refresh while online")

    missing = [t for t in wanted if _available(t) is None]
    covered = [t for t in wanted if _available(t)]
    if covered:
        _ok(f"local price data available for: {', '.join(covered)}")
    if missing:
        _warn(f"no local data for: {', '.join(missing)} — run online once, or "
              f"python scripts/build_offline_dataset.py --tickers {' '.join(missing)}")

    # 7. outputs writable -----------------------------------------------------
    out = PACKAGE_ROOT / "outputs"
    try:
        (out / "figures").mkdir(parents=True, exist_ok=True)
        probe = out / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        _ok(f"output directory writable: {out}")
    except Exception as exc:
        _fail(f"output directory not writable ({out}): {exc}")
        problems += 1

    print(f"\nSelf-test {'PASSED' if problems == 0 else f'found {problems} blocking problem(s)'}")
    if problems == 0:
        print("Next: python main.py            (full run)   |   python run_web.py   (interactive UI)")
    return problems == 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(0 if run_selfcheck() else 1)
