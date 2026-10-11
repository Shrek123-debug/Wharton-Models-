"""Sensitivity analysis engine (spec sections 25-29)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..monte_carlo.mc import generate_returns, month_index, simulate_paths


def run_sensitivity(mu_m: np.ndarray, cov_m: np.ndarray, ctx, return_shifts: list[float],
                    vol_multipliers: list[float], n_sims: int, seed: int,
                    total_contributions: float) -> pd.DataFrame:
    rows = []
    rng_master = np.random.default_rng(seed)
    T = (ctx.reserve_end_year - ctx.start_year + 1) * 12
    for rs in return_shifts:
        for vm in vol_multipliers:
            mu = mu_m + rs / 12
            cov = cov_m * (vm ** 2)
            R = generate_returns("gaussian", mu, cov, n_sims, T, rng_master)
            res = simulate_paths(R, ctx)
            term = res["terminal_2033"]
            dd = res["max_drawdown_growth"]
            years = max(ctx.glide_end_year - ctx.start_year, 1)
            # annualised outcome per simulation: (terminal / contributions)^(1/years) - 1
            ann_ret = (term / total_contributions) ** (1 / years) - 1
            vol_ann = float(np.std(ann_ret))          # dispersion of outcomes across simulations
            tr = term / total_contributions - 1
            q95 = np.quantile(tr, 0.05)
            rows.append({
                "return_shift": rs,
                "vol_multiplier": vm,
                "median_terminal": float(np.median(term)),
                "p5_terminal": float(np.percentile(term, 5)),
                "prob_success": float((term > total_contributions).mean()),
                "prob_all_payments_funded": float(res["all_payments_funded"].mean()),
                "median_max_dd": float(np.median(dd)),
                "var_95": float(-q95),
                "cvar_95": float(-tr[tr <= q95].mean()),
                # return/vol of the simulated outcome distribution (not a traded Sharpe)
                "sharpe_proxy": float(np.mean(ann_ret) / max(vol_ann, 1e-9)),
            })
    return pd.DataFrame(rows)


def pivot_grid(df: pd.DataFrame, value: str) -> pd.DataFrame:
    return df.pivot(index="return_shift", columns="vol_multiplier", values=value)


def interpret_grid(df: pd.DataFrame, target_success: float = 0.90) -> dict:
    base = df[(df.return_shift == 0) & (df.vol_multiplier == 1.0)]
    out = {"base_case": base.iloc[0].to_dict() if len(base) else {}}
    ok = df[df.prob_success >= target_success]
    out["min_return_for_success"] = float(ok.return_shift.min()) if len(ok) else None

    # Fragility is read at the BASE return assumption: the smallest volatility multiplier
    # (>= 1.0) at which success probability drops below 75%. Reading it across every return
    # shift would report the left edge of the grid instead of real fragility.
    at_base = df[(df.return_shift == 0) & (df.vol_multiplier >= 1.0)]
    fragile = at_base[at_base.prob_success < 0.75]
    out["fragile_vol_threshold"] = float(fragile.vol_multiplier.min()) if len(fragile) else None

    out["optimistic_region"] = df.nlargest(3, "median_terminal")[["return_shift", "vol_multiplier"]].to_dict("records")
    out["pessimistic_region"] = df.nsmallest(3, "median_terminal")[["return_shift", "vol_multiplier"]].to_dict("records")
    return out
