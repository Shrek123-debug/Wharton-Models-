"""Risk metrics: VaR/CVaR, concentration, HHI, correlation flags (spec sections 31-36, 67-71)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from ..portfolio.portfolio import drawdown_series


def historical_var_cvar(returns: pd.Series, confidence: float) -> tuple[float, float]:
    r = returns.dropna()
    if r.empty:
        return float("nan"), float("nan")
    var = -np.quantile(r, 1 - confidence)
    tail = r[r <= np.quantile(r, 1 - confidence)]
    cvar = -tail.mean()
    return float(var), float(cvar)


def parametric_var_cvar(mean: float, std: float, confidence: float) -> tuple[float, float]:
    if not np.isfinite(std) or std <= 0:
        return float("nan"), float("nan")
    z = stats.norm.ppf(1 - confidence)
    var = -(mean + z * std)
    # E[X | X <= q] for normal = mu - sigma * phi(z)/Phi(z)
    cvar_mean = mean - std * stats.norm.pdf(z) / stats.norm.cdf(z)
    cvar = -cvar_mean
    return float(var), float(cvar)


def var_cvar_table(returns: pd.Series, mean: float, std: float, confidences=(0.95, 0.99)) -> pd.DataFrame:
    rows = []
    for c in confidences:
        hv, hc = historical_var_cvar(returns, c)
        pv, pc = parametric_var_cvar(mean, std, c)
        rows.append({"confidence": c, "historical_VaR": hv, "historical_CVaR": hc,
                     "parametric_VaR": pv, "parametric_CVaR": pc})
    return pd.DataFrame(rows)


def hhi(weights: pd.Series) -> dict:
    w = weights[weights > 0]
    n = len(w)
    raw = float((w ** 2).sum())
    normalized = float((raw - 1 / n) / (1 - 1 / n)) if n > 1 else 1.0
    return {"raw": raw, "normalized": normalized, "effective_n": 1 / raw, "n_holdings": n}


def concentration_report(weights: pd.Series) -> dict:
    w = weights.sort_values(ascending=False)
    return {
        "largest": (w.index[0], float(w.iloc[0])),
        "top3": float(w.iloc[:3].sum()),
        "top5": float(w.iloc[:5].sum()),
        "top10": float(w.iloc[:10].sum()),
        "hhi": hhi(w),
    }


def correlation_flags(corr: pd.DataFrame, threshold: float) -> list[dict]:
    flags = []
    cols = list(corr.columns)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            c = corr.iloc[i, j]
            if np.isfinite(c) and abs(c) > threshold:
                flags.append({"a": cols[i], "b": cols[j], "correlation": float(c),
                              "issue": "HIGH CORRELATION"})
    return flags


def correlation_clusters(corr: pd.DataFrame, threshold: float) -> dict[str, int]:
    """Single-linkage clusters on |corr| > threshold."""
    cols = list(corr.columns)
    parent = {c: c for c in cols}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            c = corr.iloc[i, j]
            if np.isfinite(c) and c > threshold:
                a, b = find(cols[i]), find(cols[j])
                if a != b:
                    parent[b] = a
    clusters: dict[str, int] = {}
    groups: dict[str, list[str]] = {}
    for c in cols:
        groups.setdefault(find(c), []).append(c)
    for k, members in enumerate(groups.values()):
        members[0] if len(members) == 1 else "cluster:" + ",".join(sorted(members))
        for m in members:
            clusters[m] = k
    return clusters


def drawdown_distribution(paths: np.ndarray) -> dict:
    """paths: (n_sims, n_steps) value paths -> max drawdown distribution."""
    running_max = np.maximum.accumulate(paths, axis=1)
    dd = (paths / running_max - 1).min(axis=1)
    pcts = [5, 10, 25, 50, 75, 90, 95]
    out = {f"p{p}": float(np.percentile(dd, p)) for p in pcts}
    out["median"] = out["p50"]
    out["worst"] = float(dd.min())
    for th in (10, 20, 30, 40):
        out[f"prob_gt_{th}pct"] = float((dd <= -th / 100).mean())
    out["_dd_array"] = dd
    return out


def recovery_analysis(value_index: pd.Series) -> pd.DataFrame:
    dd = drawdown_series(value_index)
    events = []
    in_dd = False
    peak = trough = None
    trough_val = 0.0
    for dt, v in dd.items():
        if not in_dd and v < -0.05:
            in_dd = True
            peak = value_index.loc[:dt].idxmax()
            trough, trough_val = dt, v
        elif in_dd:
            if v < trough_val:
                trough, trough_val = dt, v
            elif v >= 0:
                events.append({"peak": peak, "trough": trough, "drawdown": trough_val,
                               "recovery": dt, "days_to_recover": (dt - trough).days})
                in_dd = False
    if in_dd:
        events.append({"peak": peak, "trough": trough, "drawdown": trough_val,
                       "recovery": None, "days_to_recover": None})
    return pd.DataFrame(events)
