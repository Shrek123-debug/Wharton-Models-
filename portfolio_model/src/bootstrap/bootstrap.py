"""Historical bootstrap engine (spec sections 19-22).

Resamples REAL historical joint daily returns (no synthetic distributions).
Block bootstrap preserves serial dependence and cross-asset correlation:
contiguous blocks of `block_size_days` trading days are drawn from the
historical joint return matrix and concatenated to span the simulation horizon,
then compounded to monthly returns for the shared simulation core.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..monte_carlo.mc import n_months, simulate_paths

TRADING_DAYS_PER_MONTH = 21


def run_bootstrap(daily_joint: np.ndarray, ctx, n_sims: int, seed: int,
                  method: str = "block", block_size_days: int = 20, batch: int = 250) -> dict:
    """daily_joint: (n_days, n_assets) historical daily simple returns (assets aligned to ctx)."""
    rng = np.random.default_rng(seed)
    n_days, n_assets = daily_joint.shape
    T = n_months(ctx)
    horizon_days = T * TRADING_DAYS_PER_MONTH
    block = max(1, block_size_days) if method == "block" else 1
    n_blocks = int(np.ceil(horizon_days / block))
    max_start = n_days - block

    parts = []
    done = 0
    while done < n_sims:
        b = min(batch, n_sims - done)
        starts = rng.integers(0, max_start + 1, (b, n_blocks))
        idx = starts[:, :, None] + np.arange(block)[None, None, :]
        sampled = daily_joint[idx.reshape(b, -1)][:, :horizon_days]      # (b, horizon_days, n_assets)
        monthly = (1 + sampled.reshape(b, T, TRADING_DAYS_PER_MONTH, n_assets)).prod(axis=2) - 1
        parts.append(simulate_paths(monthly, ctx))
        done += b

    out = {}
    for k in parts[0]:
        if isinstance(parts[0][k], np.ndarray):
            out[k] = np.concatenate([p[k] for p in parts])
        else:
            out[k] = parts[0][k]
    out["n_sims"] = n_sims
    out["method"] = method
    out["block_size_days"] = block
    return out
