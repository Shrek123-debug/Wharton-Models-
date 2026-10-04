"""Sector classification and sector-level analysis (spec sections 6, 49-52)."""
from __future__ import annotations

import pandas as pd

# Documented static GICS mapping for known tickers (spec section 6: consistent classification).
GICS_STATIC = {
    "VOO": "Broad Market (ETF)",
    "SPY": "Broad Market (ETF)",
    "QQQ": "Broad Market (ETF)",
    "ADBE": "Information Technology",
    "DUOL": "Information Technology",
    "AAPL": "Information Technology",
    "MSFT": "Information Technology",
    "NVDA": "Information Technology",
    "DIS": "Communication Services",
    "NFLX": "Communication Services",
    "CMCSA": "Communication Services",
    "XOM": "Energy",
    "CVX": "Energy",
    "COP": "Energy",
    "EOG": "Energy",
    "JPM": "Financials",
    "BRK-B": "Financials",
    "V": "Financials",
    "MA": "Financials",
    "UNH": "Health Care",
    "JNJ": "Health Care",
    "PFE": "Health Care",
    "LLY": "Health Care",
    "CAT": "Industrials",
    "BA": "Industrials",
    "HON": "Industrials",
    "AMZN": "Consumer Discretionary",
    "TSLA": "Consumer Discretionary",
    "NKE": "Consumer Discretionary",
    "MCD": "Consumer Discretionary",
    "PG": "Consumer Staples",
    "KO": "Consumer Staples",
    "WMT": "Consumer Staples",
    "COST": "Consumer Staples",
    "LIN": "Materials",
    "FCX": "Materials",
    "NEE": "Utilities",
    "PGN": "Utilities",
    "O": "Real Estate",
    "AMT": "Real Estate",
    "IEF": "Bonds",
    "SHY": "Bonds",
    "AGG": "Bonds",
    "BND": "Bonds",
    "TLT": "Bonds",
    "LQD": "Bonds",
    "CASH": "Cash",
    "GLD": "Commodity",
    "SLV": "Commodity",
}

SECTOR_ORDER = ["Energy", "Information Technology", "Health Care", "Financials", "Industrials",
                "Consumer Discretionary", "Consumer Staples", "Communication Services",
                "Materials", "Utilities", "Real Estate", "Broad Market (ETF)",
                "Bonds", "Cash", "Commodity", "Alternative", "Unknown"]

CYCLICAL = {"Consumer Discretionary", "Information Technology", "Industrials", "Energy",
            "Materials", "Communication Services"}
DEFENSIVE = {"Health Care", "Consumer Staples", "Utilities", "Real Estate"}


def assign_sector(ticker: str, existing: str | None = None) -> str:
    if existing and str(existing).strip() and str(existing).lower() not in {"nan", "none", "unknown"}:
        return str(existing).strip()
    return GICS_STATIC.get(ticker.upper(), "Unknown")


def sector_table(holdings: pd.DataFrame, monthly_returns: pd.DataFrame,
                 lookback_months: int = 12) -> pd.DataFrame:
    """Sector weights, 12-month return, contribution, holdings count, concentration."""
    h = holdings.copy()
    rows = []
    total_w = h["weight"].sum()
    for sector, grp in h.groupby("sector"):
        w = grp["weight"].sum()
        tickers = [t for t in grp["ticker"] if t in monthly_returns.columns]
        sec_ret = float("nan")
        if tickers:
            sub = monthly_returns[tickers].fillna(0)
            sub_w = grp.set_index("ticker").loc[tickers, "weight"]
            sub_w = sub_w / sub_w.sum() if sub_w.sum() > 0 else sub_w
            sec_monthly = sub.mul(sub_w, axis=1).sum(axis=1).tail(lookback_months)
            sec_ret = float((1 + sec_monthly).prod() - 1)
        rows.append({
            "sector": sector,
            "weight": float(w / total_w),
            "n_holdings": len(grp),
            "holdings": ", ".join(grp["ticker"]),
            "largest_holding": grp.loc[grp["weight"].idxmax(), "ticker"],
            "sector_return_12m": sec_ret,
            "contribution_12m": sec_ret * float(w / total_w) if sec_ret == sec_ret else float("nan"),
            "sector_hhi": float(((grp["weight"] / w) ** 2).sum()) if w > 0 else float("nan"),
            "cyclical_defensive": "Cyclical" if sector in CYCLICAL else ("Defensive" if sector in DEFENSIVE else "Other"),
        })
    df = pd.DataFrame(rows).set_index("sector")
    return df.reindex([s for s in SECTOR_ORDER if s in df.index] + [s for s in df.index if s not in SECTOR_ORDER])


def sector_correlations(holdings: pd.DataFrame, monthly_returns: pd.DataFrame) -> pd.DataFrame:
    h = holdings.copy()
    series = {}
    for sector, grp in h.groupby("sector"):
        tickers = [t for t in grp["ticker"] if t in monthly_returns.columns]
        if not tickers:
            continue
        sub = monthly_returns[tickers].fillna(0)
        sub_w = grp.set_index("ticker").loc[tickers, "weight"]
        sub_w = sub_w / sub_w.sum()
        series[sector] = sub.mul(sub_w, axis=1).sum(axis=1)
    return pd.DataFrame(series).corr()
