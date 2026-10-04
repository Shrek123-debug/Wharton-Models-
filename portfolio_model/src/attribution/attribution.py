"""Return attribution for holdings and sectors (spec sections 50, 19)."""
from __future__ import annotations

import pandas as pd


def holding_attribution(holdings: pd.DataFrame, monthly_returns: pd.DataFrame,
                        lookback_months: int = 12) -> pd.DataFrame:
    rows = []
    for _, h in holdings.iterrows():
        t = h["ticker"]
        if t in monthly_returns.columns:
            r = monthly_returns[t].tail(lookback_months).fillna(0)
            ret = float((1 + r).prod() - 1)
        else:
            ret = 0.0  # cash earns rf separately
        rows.append({
            "ticker": t,
            "weight": float(h["weight"]),
            "return_12m": ret,
            "contribution_12m": ret * float(h["weight"]),
        })
    df = pd.DataFrame(rows)
    df["share_of_portfolio_return"] = df["contribution_12m"] / df["contribution_12m"].sum()
    return df.sort_values("contribution_12m", ascending=False)


def pl_note(holdings: pd.DataFrame) -> str:
    if "cost_basis" in holdings.columns and holdings["cost_basis"].notna().any():
        return "P&L computed from supplied cost basis."
    return ("Dollar P&L is not computed because no cost basis / purchase price was supplied "
            "in the input spreadsheet. Return-based attribution is used instead "
            "(spec section 64: do not invent data).")
