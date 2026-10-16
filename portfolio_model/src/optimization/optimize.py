"""Diagnostic portfolio optimization (spec sections 56-57). Suggested, not mandatory."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import optimize


def max_sharpe_weights(mu: np.ndarray, cov: np.ndarray, bounds: list[tuple],
                       constraints: list[dict], init: np.ndarray) -> np.ndarray:
    len(mu)

    def neg_sharpe(w):
        ret = w @ mu
        vol = np.sqrt(w @ cov @ w)
        return -(ret - 0.0) / max(vol, 1e-12)

    res = optimize.minimize(neg_sharpe, init, method="SLSQP", bounds=bounds,
                            constraints=constraints, options={"maxiter": 500, "ftol": 1e-10})
    w = np.clip(res.x, 0, None)
    return w / w.sum()


def suggest_allocation(holdings: pd.DataFrame, mu_annual: np.ndarray, cov_annual: np.ndarray,
                       config: dict) -> dict:
    tickers = list(holdings["ticker"])
    n = len(tickers)
    current = holdings["weight"].values.astype(float)
    max_pos = config.get("risk", {}).get("max_position_weight", 0.25)
    min_cash = config.get("risk", {}).get("min_cash_weight", 0.05)
    group_cap = config.get("risk", {}).get("max_correlated_group_weight", 0.30)

    bounds = [(0.0, max_pos)] * n
    constraints = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
    cash_idx = [i for i, t in enumerate(tickers) if t == "CASH"]
    if cash_idx:
        constraints.append({"type": "ineq", "fun": lambda w, ci=cash_idx[0]: w[ci] - min_cash})
    groups: dict[str, list[int]] = {}
    if "correlation_group" in holdings.columns:
        for i, g in enumerate(holdings["correlation_group"]):
            if isinstance(g, str) and g.strip():
                groups.setdefault(g, []).append(i)
    for g, idxs in groups.items():
        constraints.append({"type": "ineq",
                            "fun": (lambda w, ix=idxs, cap=group_cap: cap - sum(w[i] for i in ix))})

    suggested = max_sharpe_weights(mu_annual, cov_annual, bounds, constraints, current)
    turnover = float(np.abs(suggested - current).sum() / 2)
    table = pd.DataFrame({
        "ticker": tickers,
        "current_weight": current,
        "suggested_weight": suggested,
        "difference": suggested - current,
    })
    return {"table": table, "turnover": turnover,
            "note": "Diagnostic max-Sharpe suggestion under position/group/cash constraints; not a mandatory allocation."}
