#!/usr/bin/env python
"""Build (or refresh) the committed offline price dataset in portfolio_model/data/offline.

Why this exists
---------------
The models need daily price history. If that history can only come from Yahoo Finance at
run time, the project breaks the moment the network is unavailable, rate-limited, or the
machine is behind a proxy — which is exactly how "the models won't run locally" starts.

This script downloads the history ONCE, while you are online, and stores a compact
Close-only snapshot per ticker in ``data/offline/``. Those snapshots are committed to git,
so a fresh clone on any machine can run every model with ``--offline`` and zero network.

Usage:
  python scripts/build_offline_dataset.py                 # default universe
  python scripts/build_offline_dataset.py --tickers AAPL MSFT AGG
  python scripts/build_offline_dataset.py --from-workbook data/input/example_portfolio_full.xlsx
  python scripts/build_offline_dataset.py --start 2000-01-01 --end 2026-01-01
  python scripts/build_offline_dataset.py --list          # show what is already bundled
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from src.config import PACKAGE_ROOT, load_config, resolve  # noqa: E402
from src.market_data.fetch import BUNDLED_DIR  # noqa: E402
from src.runtime_env import configure_local_runtime  # noqa: E402

# Core universe: benchmarks used by the pipeline + the example portfolios + a broad set of
# liquid ETFs and large-cap stocks so a typical competition spreadsheet resolves offline.
DEFAULT_UNIVERSE = [
    # benchmarks & core ETFs
    "SPY", "VOO", "IVV", "VTI", "ITOT", "QQQ", "IWM", "RSP",
    "AGG", "BND", "VBND", "IEF", "SHY", "TLT", "LQD", "SPTL",
    "GLD", "SLV", "DBC", "VNQ", "EFA", "EEM", "VWO", "VXUS", "MUB",
    # sector ETFs
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLRE", "SMH",
    # mega-cap / common holdings
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA", "AVGO",
    "ADBE", "CRM", "ORCL", "NOW", "AMD", "INTC", "CSCO", "IBM", "QCOM", "TXN",
    "DIS", "CMCSA", "NFLX", "DUOL", "UBER", "ABNB", "SPOT",
    "JPM", "BAC", "WFC", "GS", "MS", "V", "MA", "PYPL", "COIN",
    "KO", "PEP", "WMT", "COST", "PG", "MRK", "PFE", "UNH", "JNJ", "ABT", "LLY", "TMO",
    "XOM", "CVX", "COP", "CAT", "DE", "BA", "GE", "LIN", "NEE", "T", "VZ",
]


def _download(ticker: str, start: str, end: str | None) -> pd.DataFrame | None:
    import yfinance as yf

    try:
        df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False, threads=False)
    except Exception as exc:
        print(f"  [skip] {ticker}: download error: {exc}")
        return None
    if df is None or len(df) == 0:
        print(f"  [skip] {ticker}: no data returned (bad ticker or rate-limited)")
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if "Close" not in df.columns:
        print(f"  [skip] {ticker}: response had no Close column")
        return None
    out = df[["Close"]].dropna().copy()
    out.index = pd.to_datetime(out.index).tz_localize(None)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out.index.name = "Date"
    out.columns.name = None
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the committed offline price snapshots")
    ap.add_argument("--tickers", nargs="*", help="Explicit ticker list (overrides the default universe)")
    ap.add_argument("--from-workbook", help="Add every ticker found in this workbook to the universe")
    ap.add_argument("--start", default="2000-01-01")
    ap.add_argument("--end", default=None, help="Defaults to today")
    ap.add_argument("--out", default=str(BUNDLED_DIR))
    ap.add_argument("--list", action="store_true", help="List existing snapshots and exit")
    args = ap.parse_args()

    out_dir = Path(args.out)
    if args.list:
        files = sorted(out_dir.glob("*.parquet"))
        print(f"{out_dir}: {len(files)} snapshots")
        for p in files:
            df = pd.read_parquet(p)
            print(f"  {p.stem:<8} {len(df):>6} rows  {df.index.min().date()} .. {df.index.max().date()}")
        return 0

    configure_local_runtime()
    tickers = list(dict.fromkeys([t.upper() for t in (args.tickers or DEFAULT_UNIVERSE)]))
    if args.from_workbook:
        from src.ingestion.ingest import ingest

        found = [str(t).upper() for t in ingest(args.from_workbook).holdings["ticker"]]
        added = [t for t in found if t not in tickers and t != "CASH"]
        tickers += added
        print(f"Added {len(added)} ticker(s) from {args.from_workbook}: {', '.join(added)}")

    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Building offline dataset -> {out_dir}  ({len(tickers)} tickers, {args.start}..{args.end or 'today'})")
    written, failed = [], []
    for t in tickers:
        df = _download(t, args.start, args.end)
        if df is None or not len(df):
            failed.append(t)
            continue
        df.to_parquet(out_dir / f"{t}.parquet")
        written.append(t)
        print(f"  [ok]   {t:<8} {len(df):>6} rows  {df.index.min().date()} .. {df.index.max().date()}")

    manifest = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "start_date": args.start,
        "end_date": args.end or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "basis": "adjusted close (total-return basis: dividends reinvested)",
        "tickers": sorted(written),
        "failed": sorted(failed),
        "note": ("Committed snapshots used by src/market_data/fetch.py when the network is "
                 "unavailable or --offline is set. Refresh with scripts/build_offline_dataset.py."),
    }
    try:
        import yaml

        (out_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    except ImportError:
        (out_dir / "manifest.json").write_text(pd.Series(manifest).to_json(indent=2), encoding="utf-8")

    total_kb = sum(p.stat().st_size for p in out_dir.glob("*.parquet")) / 1024
    print(f"\nWrote {len(written)} snapshots ({total_kb:,.0f} KB total); {len(failed)} failed: {', '.join(failed) or '-'}")
    print("Verify a fully offline run with:  python main.py --offline --sims 2000 --no-charts")
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
