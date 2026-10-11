"""Historical market data retrieval with a three-tier, offline-first resolution order.

Resolution order for every ticker (spec section 7, hardened for local/offline runs):

  1. project cache hit      portfolio_model/data/cache/          (previous run, still fresh)
  2. network fetch          yfinance                             (only when allowed and reachable)
  3. bundled dataset        portfolio_model/data/offline/        (committed snapshot, zero network)
  4. unavailable            explicit provenance record + rule flag

Design rules
------------
* Cache keys are stable. The old key embedded "today's date", so every new day forced a
  full re-download and the pipeline broke the moment the network was unavailable.
  Keys are now ``TICKER__<start>__<end>.parquet`` where ``<end>`` is the configured
  end date, or ``live`` when the config asks for the latest available data.
* Freshness is explicit (``max_cache_age_days``). A stale cache is reused when the network
  fails, with a visible "stale cache" note instead of a crash.
* ``yfinance`` is imported lazily, so the offline path works even when it is not installed.
* Every ticker carries provenance (source, rows, inception, as-of date) which the pipeline
  surfaces on the Data Quality sheet and in the web UI.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import PACKAGE_ROOT

log = logging.getLogger(__name__)

LIVE = "live"
OFFLINE_ENV = "PORTFOLIO_OFFLINE"
BUNDLED_DIR = PACKAGE_ROOT / "data" / "offline"
_PRICE_COLS = ("Close", "Open", "High", "Low", "Volume")


@dataclass
class FetchResult:
    """frames[ticker] = OHLC frame (possibly Close-only); provenance[ticker] = audit record."""

    frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    provenance: dict[str, dict] = field(default_factory=dict)

    def missing(self) -> list[str]:
        return [t for t, p in self.provenance.items() if p["status"] != "ok"]

    def as_rows(self) -> list[dict]:
        rows = []
        for t, p in self.provenance.items():
            rows.append({
                "ticker": t,
                "status": p["status"],
                "source": p.get("source", "-"),
                "rows": p.get("rows", 0),
                "inception": p.get("inception") or "-",
                "data_as_of": p.get("data_as_of") or "-",
                "fetched_utc": p.get("fetched_utc") or "-",
                "note": p.get("note", ""),
            })
        return rows


def _cache_path(cache_dir: Path, ticker: str, start: str, end_key: str) -> Path:
    return cache_dir / f"{ticker}__{start}__{end_key}.parquet"


def _cache_age_days(path: Path) -> float:
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return (datetime.now(timezone.utc) - mtime).total_seconds() / 86400.0


def _normalise(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Flatten yfinance MultiIndex, keep price columns only, drop empty rows."""
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    keep = [c for c in _PRICE_COLS if c in df.columns]
    if not keep:
        return pd.DataFrame()
    df = df[keep]
    if "Close" not in df.columns:
        return pd.DataFrame()
    df = df.dropna(subset=["Close"])
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def _slice(df: pd.DataFrame, start: str, end: str | None) -> pd.DataFrame:
    """Restrict a frame to [start, end] so a wider snapshot can serve a narrower request."""
    if not len(df):
        return df
    out = df.loc[pd.to_datetime(start):]
    if end and end != LIVE:
        out = out.loc[:pd.to_datetime(end)]
    return out


def _read_parquet(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def _read_cached(path: Path, start: str, end: str | None) -> pd.DataFrame:
    try:
        return _slice(_read_parquet(path), start, end)
    except Exception as exc:
        log.warning("Cache file %s unreadable (%s)", path, exc)
        return pd.DataFrame()


def _record(result: FetchResult, ticker: str, df: pd.DataFrame, source: str,
            now_utc: str, note: str) -> None:
    result.frames[ticker] = df
    result.provenance[ticker] = {
        "status": "ok", "source": source, "rows": len(df),
        "inception": df.index.min().strftime("%Y-%m-%d"),
        "data_as_of": df.index.max().strftime("%Y-%m-%d"),
        "fetched_utc": now_utc, "note": note,
    }


def _bundled_candidates(bundled_dir: Path, ticker: str) -> list[Path]:
    if not bundled_dir or not bundled_dir.exists():
        return []
    out = []
    for name in (f"{ticker}.parquet", f"{ticker}.csv"):
        p = bundled_dir / name
        if p.exists():
            out.append(p)
    return out


def _load_bundled(bundled_dir: Path, ticker: str) -> pd.DataFrame:
    for p in _bundled_candidates(bundled_dir, ticker):
        try:
            df = _read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p, parse_dates=[0], index_col=0)
            df = _normalise(df, ticker)
            if len(df):
                return df
        except Exception as exc:  # corrupt snapshot must not take the whole run down
            log.warning("Bundled snapshot %s unreadable (%s); trying next candidate", p, exc)
    return pd.DataFrame()


def _network_fetch(ticker: str, start: str, end: str | None) -> pd.DataFrame:
    """Fetch from Yahoo Finance. Returns an empty frame on any failure (never raises)."""
    try:
        import yfinance as yf  # lazy: offline runs must not require yfinance
    except ImportError:
        log.info("yfinance is not installed; using local data for %s", ticker)
        return pd.DataFrame()
    try:
        df = yf.download(ticker, start=start, end=end if end else None,
                         auto_adjust=True, progress=False, threads=False)
    except Exception as exc:
        log.warning("Network fetch failed for %s: %s", ticker, exc)
        return pd.DataFrame()
    if df is None or len(df) == 0:
        return pd.DataFrame()
    return _normalise(df, ticker)


def _offline_mode(offline: str | None) -> str:
    """Resolve offline mode: explicit arg > env var > 'auto'."""
    mode = offline or os.environ.get(OFFLINE_ENV) or "auto"
    mode = str(mode).strip().lower()
    if mode in {"1", "true", "yes", "always", "off", "no-network"}:
        return "always"
    if mode in {"0", "false", "no", "never", "online"}:
        return "never"
    return "auto"


def fetch_history(tickers: list[str], start: str, end: str | None,
                  cache_dir: str | Path, *, offline: str | None = None,
                  bundled_dir: str | Path | None = None, max_age_days: float = 7.0,
                  allow_stale_cache: bool = True) -> FetchResult:
    """Return a FetchResult for every requested ticker with explicit provenance."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    bundled_dir = Path(bundled_dir) if bundled_dir else BUNDLED_DIR
    mode = _offline_mode(offline)
    end_key = end or LIVE
    now_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")

    result = FetchResult()
    network_ok: bool | None = None

    for t in tickers:
        # ---- tier 1: project cache -------------------------------------------------
        exact = _cache_path(cache_dir, t, start, end_key)
        candidate: tuple[Path, str, float] | None = None
        if exact.exists():
            candidate = (exact, end_key, _cache_age_days(exact))
        else:
            # a wider cached window can serve a narrower request
            # (e.g. ACME__2000-01-01__live.parquet answers 2015-01-01..2020-01-01)
            best: tuple[float, Path, str] | None = None
            for p in cache_dir.glob(f"{t}__*.parquet"):
                parts = p.name[: -len(".parquet")].split("__")
                if len(parts) != 3:
                    continue
                c_start, c_end = parts[1], parts[2]
                if c_start > start:
                    continue
                if c_end != LIVE and end and c_end < end:
                    continue
                age = _cache_age_days(p)
                if best is None or age < best[0]:
                    best = (age, p, c_end)
            if best:
                candidate = (best[1], best[2], best[0])

        stale_fallback: tuple[Path, str, float] | None = None
        if candidate:
            path, key, age = candidate
            if age <= max_age_days:
                df = _read_cached(path, start, end)
                if len(df):
                    _record(result, t, df, "cache", now_utc, f"cache hit ({key}, {age:.1f}d old)")
                    continue
                candidate = None
            elif allow_stale_cache:
                # keep it as a fallback: a stale cache is still better than nothing
                stale_fallback = candidate

        # ---- tier 2: network -------------------------------------------------------
        df = pd.DataFrame()
        if mode != "always":
            try:
                df = _network_fetch(t, start, end)
            except Exception as exc:  # a broken network stack must not break the run
                log.warning("Network fetch raised for %s: %s", t, exc)
                df = pd.DataFrame()
            if len(df):
                network_ok = True
                try:
                    df.to_parquet(exact)
                except Exception as exc:
                    log.warning("Could not write cache file for %s: %s", t, exc)
            else:
                network_ok = False

        # ---- tier 2b: stale cache (better than a bundled snapshot) ------------------
        if not len(df) and stale_fallback:
            path, key, age = stale_fallback
            df = _read_cached(path, start, end)
            if len(df):
                _record(result, t, df, "cache", now_utc,
                        f"stale cache reused ({key}, {age:.1f}d old) because the network was unavailable")
                continue

        # ---- tier 3: bundled snapshot ----------------------------------------------
        if not len(df):
            df = _slice(_load_bundled(bundled_dir, t), start, end)
            if len(df):
                if mode == "always":
                    note = "offline mode: committed snapshot in data/offline/"
                elif network_ok is False:
                    note = "network unavailable: committed snapshot in data/offline/"
                else:
                    note = "committed snapshot in data/offline/"
                # promote the snapshot into the project cache so later runs are cache hits
                try:
                    df.to_parquet(exact)
                except Exception as exc:
                    log.debug("Could not promote bundled snapshot for %s into cache: %s", t, exc)
                _record(result, t, df, "bundled snapshot", now_utc, note)
                continue

        if len(df):
            _record(result, t, df, "network", now_utc, "downloaded from Yahoo Finance")
        else:
            result.frames[t] = pd.DataFrame()
            result.provenance[t] = {"status": "unavailable", "source": "none", "rows": 0,
                                    "inception": None, "data_as_of": None, "fetched_utc": now_utc,
                                    "note": ("no cache, no network and no bundled snapshot for this ticker; "
                                             f"run `python scripts/build_offline_dataset.py --tickers {t}` "
                                             "while online, or place a snapshot in data/offline/")}

    # one consolidated audit trail per run
    try:
        pd.DataFrame(result.as_rows()).set_index("ticker").to_csv(cache_dir / "_fetch_meta.csv")
    except Exception as exc:
        log.warning("Could not write %s: %s", cache_dir / "_fetch_meta.csv", exc)

    if mode == "always":
        log.info("Offline mode: %d/%d tickers resolved from local data",
                 sum(1 for p in result.provenance.values() if p["status"] == "ok"), len(tickers))
    return result


def align_price_frames(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Union-index adjusted closes; never fill with zeros (spec section 112)."""
    closes = pd.DataFrame({t: f["Close"] for t, f in frames.items() if len(f) and "Close" in f})
    return closes.sort_index()
