"""Portfolio construction: historical series, stats, covariance (spec sections 9, 13, 35, 67-69)."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..returns.returns import cagr, simple_returns, to_monthly

EQUITY_CLASSES = {"US Equity", "International Equity", "Emerging Market Equity", "ETF", "REIT"}
DEFENSIVE_SECTORS = {"Health Care", "Consumer Staples", "Utilities"}
CYCLICAL_SECTORS = {"Consumer Discretionary", "Information Technology", "Industrials", "Energy", "Materials", "Communication Services"}


@dataclass
class PortfolioData:
    tickers: list[str]
    weights: pd.Series                 # canonical current weights (sum = 1)
    prices: pd.DataFrame               # daily adjusted closes
    daily_returns: pd.DataFrame        # daily simple returns (assets)
    monthly_returns: pd.DataFrame      # monthly simple returns (assets)
    portfolio_daily: pd.Series         # current-weight portfolio daily returns
    portfolio_monthly: pd.Series
    portfolio_value_index: pd.Series   # rebalanced index (starts 1.0)
    cov_monthly: np.ndarray
    corr: pd.DataFrame
    stats: dict = field(default_factory=dict)
    benchmarks: dict[str, pd.Series] = field(default_factory=dict)


def build_portfolio(prices: pd.DataFrame, weights: pd.Series) -> PortfolioData:
    tickers = list(prices.columns)
    w = weights.reindex(tickers).fillna(0.0)
    w = w / w.sum()
    daily = simple_returns(prices)
    # cash-like assets (zero variance) produce NaN-free rows already
    daily = daily.dropna(how="all")
    monthly = to_monthly(daily)
    port_daily = daily.mul(w, axis=1).sum(axis=1)
    port_monthly = monthly.mul(w, axis=1).sum(axis=1)
    value_index = (1 + port_daily).cumprod()

    cov = np.atleast_2d(monthly.cov().values)
    cov = _nearest_psd(cov)
    corr = monthly.corr()

    pd_obj = PortfolioData(tickers, w, prices, daily, monthly, port_daily, port_monthly,
                           value_index, cov, corr)
    pd_obj.stats = portfolio_stats(port_daily, port_monthly, value_index)
    return pd_obj


def _nearest_psd(A: np.ndarray) -> np.ndarray:
    sym = (A + A.T) / 2
    vals, vecs = np.linalg.eigh(sym)
    eps = max(1e-12, abs(vals).max() * 1e-10)
    vals = np.clip(vals, eps, None)
    return vecs @ np.diag(vals) @ vecs.T


def portfolio_stats(daily: pd.Series, monthly: pd.Series, value_index: pd.Series) -> dict:
    ann_ret = float((1 + monthly.mean()) ** 12 - 1)
    ann_vol = float(monthly.std() * np.sqrt(12))
    sharpe = ann_ret / ann_vol if ann_vol > 0 else float("nan")
    downside = monthly[monthly < 0]
    ddev = float(downside.std() * np.sqrt(12)) if len(downside) > 1 else float("nan")
    sortino = ann_ret / ddev if ddev and ddev > 0 else float("nan")
    mdd, peak_date, trough_date, recovery_date = max_drawdown(value_index)
    return {
        "cagr_historical": cagr(value_index),
        "mean_annual_return": ann_ret,
        "annual_volatility": ann_vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "downside_deviation": ddev,
        "max_drawdown": mdd,
        "drawdown_peak": peak_date,
        "drawdown_trough": trough_date,
        "drawdown_recovery": recovery_date,
        "n_years": (value_index.index[-1] - value_index.index[0]).days / 365.25,
    }


def max_drawdown(value_index: pd.Series) -> tuple[float, object, object, object]:
    running_max = value_index.cummax()
    dd = value_index / running_max - 1
    trough = dd.idxmin()
    mdd = float(dd.min())
    peak = value_index.loc[:trough].idxmax()
    after = value_index.loc[trough:]
    recovered = after[after >= value_index.loc[peak]]
    recovery = recovered.index[0] if len(recovered) else None
    return mdd, peak, trough, recovery


def drawdown_series(value_index: pd.Series) -> pd.Series:
    return value_index / value_index.cummax() - 1


def benchmark_series(bench_prices: pd.DataFrame, equity: str, bonds: str) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    for name, tick in [("S&P 500 (SPY)", equity), ("US Agg Bond (AGG)", bonds)]:
        if tick in bench_prices.columns:
            out[name] = (1 + simple_returns(bench_prices[tick]).fillna(0)).cumprod()
    if equity in bench_prices.columns and bonds in bench_prices.columns:
        er = simple_returns(bench_prices[equity]).fillna(0)
        br = simple_returns(bench_prices[bonds]).fillna(0)
        blended = 0.6 * er + 0.4 * br
        out["60/40 Benchmark"] = (1 + blended).cumprod()
    return out


def sector_of(asset_class: str, sector: str | None) -> str:
    if asset_class == "Cash":
        return "Cash"
    if asset_class in ("Treasury", "Corporate Bond"):
        return "Bonds"
    if asset_class == "ETF":
        return "Broad Market (ETF)"
    return sector or "Unknown"
