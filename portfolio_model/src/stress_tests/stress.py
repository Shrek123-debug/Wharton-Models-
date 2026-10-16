"""Historical crisis + hypothetical stress testing (spec sections 45-48)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..portfolio.portfolio import drawdown_series

SECTOR_SHOCK_MAP = {
    "severe_equity_crash": {"equity": "equity", "bonds": "bonds", "cash": "cash"},
    "stagflation": {"equity": "equity", "bonds": "bonds", "cash": "cash"},
    "recession": {"equity": "equity", "bonds": "bonds", "cash": "cash"},
    "inflation_shock": {"equity": "equity", "bonds": "bonds", "cash": "cash"},
}


def crisis_test(name: str, start: str, end: str, port_daily: pd.Series,
                asset_daily: pd.DataFrame, weights: pd.Series,
                holdings: pd.DataFrame, benchmarks: dict[str, pd.Series]) -> dict:
    win = port_daily.loc[start:end]
    if win.empty:
        return {"crisis": name, "error": "no data in window"}
    value = (1 + win).cumprod()
    dd = drawdown_series(value)
    peak_to_trough = float(dd.min())
    trough_date = dd.idxmin()
    # recovery: extend beyond window until prior peak regained
    peak_val = value.loc[:trough_date].max()
    after = port_daily.loc[trough_date:].copy()
    cum_after = (1 + after).cumprod()
    scale = value.loc[trough_date] / cum_after.iloc[0] if len(cum_after) else np.nan
    rec = cum_after * scale
    rec = rec[rec >= peak_val]
    recovery_date = rec.index[0] if len(rec) else None

    worst_day = float(win.min())
    weekly = win.resample("W").apply(lambda x: (1 + x).prod() - 1)
    monthly = win.resample("ME").apply(lambda x: (1 + x).prod() - 1)
    worst_week = float(weekly.min()) if len(weekly) else float("nan")
    worst_month = float(monthly.min()) if len(monthly) else float("nan")

    per_asset = {}
    for t in weights.index:
        if t in asset_daily.columns:
            a = asset_daily[t].loc[start:end].fillna(0)
            per_asset[t] = float((1 + a).prod() - 1)
        else:
            per_asset[t] = 0.0
    {t: weights[t] * r for t, r in per_asset.items()}
    worst_t = min(per_asset, key=per_asset.get)
    best_t = max(per_asset, key=per_asset.get)

    bench = {}
    for bname, series in benchmarks.items():
        b = series.loc[start:end]
        if len(b):
            bench[bname] = float(b.iloc[-1] / b.iloc[0] - 1)

    sector_perf = {}
    for _, h in holdings.iterrows():
        s = h["sector"]
        sector_perf.setdefault(s, 0.0)
        sector_perf[s] += weights[h["ticker"]] * per_asset.get(h["ticker"], 0.0)

    return {
        "crisis": name,
        "window": f"{start} to {end}",
        "portfolio_return": float(value.iloc[-1] - 1),
        "max_drawdown": peak_to_trough,
        "trough_date": str(trough_date.date()) if hasattr(trough_date, "date") else str(trough_date),
        "recovery_date": str(recovery_date.date()) if recovery_date is not None and hasattr(recovery_date, "date") else (str(recovery_date) if recovery_date is not None else "Not recovered"),
        "days_to_recovery": (recovery_date - trough_date).days if recovery_date is not None else "Not recovered",
        "worst_day": worst_day,
        "worst_week": worst_week,
        "worst_month": worst_month,
        "worst_holding": worst_t,
        "worst_holding_return": per_asset[worst_t],
        "best_holding": best_t,
        "best_holding_return": per_asset[best_t],
        "holding_returns": per_asset,
        "sector_contributions": sector_perf,
        "benchmarks": bench,
    }


def hypothetical_test(name: str, shocks: dict, holdings: pd.DataFrame,
                      asset_class_of: dict, sector_of: dict) -> dict:
    """Apply assumption shocks by asset class / sector tag. Clearly labeled assumptions."""
    rows = []
    total = 0.0
    for _, h in holdings.iterrows():
        t, w, ac = h["ticker"], h["weight"], asset_class_of[h["ticker"]]
        sec = sector_of[h["ticker"]]
        r = 0.0
        if ac == "Cash":
            r = shocks.get("cash", 0.0)
        elif ac in ("Treasury", "Corporate Bond"):
            if "long_duration_bonds" in shocks and t in ("IEF", "TLT"):
                r = shocks["long_duration_bonds"]
            elif "short_duration_bonds" in shocks and t in ("SHY",):
                r = shocks["short_duration_bonds"]
            else:
                r = shocks.get("bonds", 0.0)
        else:
            if "energy" in shocks and sec == "Energy":
                r = shocks["energy"]
            elif "cyclicals" in shocks and sec in {"Consumer Discretionary", "Information Technology", "Industrials", "Materials", "Communication Services"}:
                r = shocks["cyclicals"]
            elif "defensives" in shocks and sec in {"Health Care", "Consumer Staples", "Utilities", "Real Estate"}:
                r = shocks["defensives"]
            elif "commodities" in shocks and ac == "Commodity":
                r = shocks["commodities"]
            else:
                r = shocks.get("equity", 0.0)
        rows.append({"ticker": t, "weight": w, "shock_return": r, "contribution": w * r})
        total += w * r
    return {"scenario": name, "portfolio_return": total, "detail": rows,
            "note": "Hypothetical assumption scenario, not a forecast."}
