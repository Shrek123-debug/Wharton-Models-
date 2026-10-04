"""Historical market data retrieval with local cache (spec section 7)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

from ..config import resolve

log = logging.getLogger(__name__)


def _cache_path(cache_dir: Path, ticker: str, start: str, end: str) -> Path:
    return cache_dir / f"{ticker}_{start}_{end}.parquet"


def fetch_history(tickers: list[str], start: str, end: str | None, cache_dir: str | Path) -> dict[str, pd.DataFrame]:
    """Return {ticker: daily OHLC-adjusted DataFrame} using adjusted close (total-return basis)."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    end = end or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out: dict[str, pd.DataFrame] = {}
    meta: dict[str, dict] = {}

    for t in tickers:
        cp = _cache_path(cache_dir, t, start, end)
        if cp.exists():
            df = pd.read_parquet(cp)
        else:
            log.info("Downloading %s %s..%s", t, start, end)
            df = yf.download(t, start=start, end=end, auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if df.empty:
                out[t] = pd.DataFrame()
                meta[t] = {"status": "unavailable", "inception": None}
                continue
            df.to_parquet(cp)
        df = df.dropna(how="all")
        inception = df.index.min().strftime("%Y-%m-%d") if len(df) else None
        out[t] = df
        meta[t] = {"status": "ok", "inception": inception, "rows": len(df),
                   "fetched_utc": datetime.now(timezone.utc).isoformat()}
    pd.DataFrame(meta).T.to_csv(cache_dir / "_fetch_meta.csv")
    return out


def align_price_frames(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Union-index adjusted closes; never fill with zeros (spec section 112)."""
    closes = pd.DataFrame({t: f["Close"] for t, f in frames.items() if len(f)})
    return closes.sort_index()
