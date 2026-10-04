"""Stop-loss framework + backtesting (spec sections 43-44).

Modes compared per holding on historical daily prices:
  none | hard stop (X% below entry) | trailing stop (X% below running peak)
Convention (no look-ahead): exit at close when the stop triggers; re-enter
after `reentry_days` trading days. Results are historical backtests, not advice.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _stats(returns: pd.Series) -> dict:
    ann = returns.mean() * 252
    vol = returns.std() * np.sqrt(252)
    value = (1 + returns).cumprod()
    dd = float((value / value.cummax() - 1).min())
    downside = returns[returns < 0]
    ddev = downside.std() * np.sqrt(252) if len(downside) > 1 else np.nan
    years = len(returns) / 252
    cagr = value.iloc[-1] ** (1 / years) - 1 if years > 0 and value.iloc[-1] > 0 else np.nan
    return {"cagr": float(cagr), "vol": float(vol), "sharpe": float(ann / vol) if vol > 0 else np.nan,
            "sortino": float(ann / ddev) if ddev and ddev > 0 else np.nan,
            "max_drawdown": dd, "total_return": float(value.iloc[-1] - 1)}


def backtest_stop(prices: pd.Series, mode: str, level: float, reentry_days: int = 21) -> dict:
    p = prices.dropna()
    if len(p) < 300:
        return {"mode": mode, "level": level, "note": "insufficient history"}
    returns = p.pct_change().fillna(0)
    if mode == "none":
        st = _stats(returns)
        return {"mode": "none", "level": None, **st, "exits": 0, "turnover": 0.0,
                "missed_upside": 0.0, "reentry_days": 0}

    pos = 1.0
    entry = p.iloc[0]
    peak = p.iloc[0]
    out_returns = []
    exits = 0
    turnover = 0.0
    missed = 0.0
    cooldown = 0
    prev_pos = 1.0
    for i in range(1, len(p)):
        price = p.iloc[i]
        r = returns.iloc[i]
        if cooldown > 0:
            cooldown -= 1
            out_returns.append(0.0)
            pos = 0.0
            if cooldown == 0:
                pos = 1.0
                entry = price
                peak = price
                turnover += 1.0
            continue
        peak = max(peak, price)
        trigger = (mode == "hard" and price <= entry * (1 - level)) or \
                  (mode == "trailing" and price <= peak * (1 - level))
        if trigger:
            out_returns.append(r)
            pos = 0.0
            exits += 1
            turnover += 1.0
            cooldown = reentry_days
        else:
            out_returns.append(r if pos else 0.0)
    ret = pd.Series(out_returns, index=p.index[1:])
    st = _stats(ret)
    return {"mode": mode, "level": level, **st, "exits": exits, "turnover": turnover,
            "missed_upside": float(returns.iloc[1:].sum() - ret.sum()), "reentry_days": reentry_days}


def run_stop_backtests(prices: pd.DataFrame, tickers: list[str],
                       hard_levels: list[float], trailing_levels: list[float]) -> pd.DataFrame:
    rows = []
    for t in tickers:
        if t not in prices.columns or t == "CASH":
            continue
        s = prices[t]
        rows.append({"ticker": t, **backtest_stop(s, "none", None)})
        for lv in hard_levels:
            rows.append({"ticker": t, **backtest_stop(s, "hard", lv)})
        for lv in trailing_levels:
            rows.append({"ticker": t, **backtest_stop(s, "trailing", lv)})
    df = pd.DataFrame(rows)
    df["note"] = "Historical backtest on adjusted prices; re-entry after 21 trading days. Not a recommendation to adopt any stop."
    return df
