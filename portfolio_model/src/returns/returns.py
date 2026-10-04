"""Return calculations (spec section 8)."""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


def simple_returns(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.pct_change(fill_method=None)


def log_returns(prices: pd.DataFrame) -> pd.DataFrame:
    return np.log(prices / prices.shift(1))


def to_monthly(daily_simple: pd.DataFrame) -> pd.DataFrame:
    """Compound daily simple returns into month-end simple returns."""
    return (1 + daily_simple).resample("ME").prod(min_count=1) - 1


def annualize(monthly_mean: pd.Series) -> pd.Series:
    return (1 + monthly_mean) ** 12 - 1


def annual_vol(daily: pd.DataFrame) -> pd.Series:
    return daily.std() * np.sqrt(TRADING_DAYS_PER_YEAR)


def annual_vol_monthly(monthly: pd.DataFrame) -> pd.Series:
    return monthly.std() * np.sqrt(12)


def cagr(prices_or_values: pd.Series) -> float:
    s = prices_or_values.dropna()
    if len(s) < 2 or s.iloc[0] <= 0:
        return float("nan")
    years = (s.index[-1] - s.index[0]).days / 365.25
    if years <= 0:
        return float("nan")
    return float((s.iloc[-1] / s.iloc[0]) ** (1 / years) - 1)
