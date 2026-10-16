"""Local-runtime setup so the models run the same way on every machine.

Three problems repeatedly break "runs on my machine" for this project:

1. Matplotlib writes a font cache into ``~/.matplotlib``. On locked-down or container
   machines that path is not writable and the run dies with
   ``... is not a writable directory`` / ``Fontconfig error: No writable cache directories``.
2. yfinance writes a timezone/cookie cache into ``~/Library/Caches/py-yfinance`` with the
   same failure mode.
3. Relative paths (``data/cache``, ``../models/...``) resolve against the *current working
   directory*, so running ``python portfolio_model/main.py`` from the repo root looks for
   ``portfolio_model/portfolio_model/data/cache``.

``configure_local_runtime()`` fixes 1 and 2 by pointing every cache at a writable directory
inside the package, and ``resolve()`` in config.py already anchors relative paths to the
package root, which fixes 3. Call it once at process start (CLI, web server, tests).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .config import PACKAGE_ROOT

CACHE_ROOT = PACKAGE_ROOT / ".cache"


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def configure_local_runtime() -> dict[str, str]:
    """Point matplotlib / yfinance caches at writable package-local directories.

    Returns the environment variables that were set (useful for the run manifest).
    """
    set_vars: dict[str, str] = {}

    candidates = [CACHE_ROOT, Path(sys.prefix) / ".cache", Path(os.getcwd()) / ".cache"]
    chosen = next((c for c in candidates if _writable(c)), None)
    if chosen is None:
        return set_vars

    mpl = chosen / "matplotlib"
    mpl.mkdir(parents=True, exist_ok=True)
    current = os.environ.get("MPLCONFIGDIR")
    # Respect a user-set MPLCONFIGDIR only when it is actually usable.
    if not current or not _writable(Path(current.split(os.pathsep)[0])):
        os.environ["MPLCONFIGDIR"] = str(mpl)
    os.environ.setdefault("XDG_CACHE_HOME", str(chosen))
    set_vars["MPLCONFIGDIR"] = os.environ["MPLCONFIGDIR"]
    set_vars["XDG_CACHE_HOME"] = os.environ["XDG_CACHE_HOME"]

    # Headless-safe backend: never try to open a GUI window during a batch run.
    os.environ.setdefault("MPLBACKEND", "Agg")
    set_vars["MPLBACKEND"] = os.environ["MPLBACKEND"]

    yf_cache = chosen / "yfinance"
    yf_cache.mkdir(parents=True, exist_ok=True)
    try:
        import yfinance as yf  # optional dependency: offline runs work without it
        yf.set_tz_cache_location(str(yf_cache))
    except Exception:
        pass
    return set_vars
