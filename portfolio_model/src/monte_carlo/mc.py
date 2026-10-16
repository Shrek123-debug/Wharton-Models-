"""Monte Carlo engine (spec sections 10-14) + shared path simulation core.

Timeline modeled (driven by src/cashflows/schedule.py, validated against the case rules):
  contributions / withdrawals   at the start of the years in the schedule (case: $300k 2027, $150k 2028)
  growth phase                  glide path until the reserve set-up year (case: 2033)
  checkpoint year               sponsor range = projected facility-contribution range (case: 2031)
  reserve set-up year, month 0  split: reserve (PV of the operating payments) + facility contribution (surplus)
  reserve phase                 fixed payment at the start of each year; success = every payment funded
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

MONTHS_PER_YEAR = 12


@dataclass
class SimContext:
    start_year: int
    glide_end_year: int
    reserve_end_year: int
    equity_idx: list[int]
    bond_idx: list[int]
    cash_idx: list[int]
    glide_targets: pd.DataFrame      # index=year, cols=equity/bond/cash target weights
    contributions: dict[int, float]  # month index -> amount
    required_reserve: float
    payment_months: list[int]
    payment_amount: float
    band: float | None
    band_mode: str
    transaction_cost: float
    inflation: float
    bond_blend: np.ndarray           # weights across bond assets for reserve phase
    class_base: np.ndarray           # per-asset relative weight within its asset class (sums to 1 per class)
    withdrawals: dict[int, float] = field(default_factory=dict)  # month index -> amount (before the reserve split)
    checkpoint_year: int = 2031      # year the co-sponsor range is communicated
    schedule: object = None          # the validated CashflowSchedule that produced the flows above


def month_index(ctx: SimContext, year: int, month: int = 1) -> int:
    return (year - ctx.start_year) * MONTHS_PER_YEAR + (month - 1)


def n_months(ctx: SimContext) -> int:
    return (ctx.reserve_end_year - ctx.start_year + 1) * MONTHS_PER_YEAR


def required_reserve_pv(payment: float, first_year: int, last_year: int, rate: float) -> float:
    n = last_year - first_year + 1
    if rate <= 0:
        return payment * n
    return payment * (1 - (1 + rate) ** -n) / rate * (1 + rate)


# ------------------------------------------------------------------ return models
def generate_returns(model: str, mu_m: np.ndarray, cov_m: np.ndarray, n_sims: int,
                     n_steps: int, rng: np.random.Generator, dof: int = 5,
                     factor_idx: int = 0) -> np.ndarray:
    """Return (n_sims, n_steps, n_assets) monthly simple returns."""
    n = len(mu_m)
    L = np.linalg.cholesky(cov_m + 1e-12 * np.eye(n))
    if model == "gaussian":
        Z = rng.standard_normal((n_sims, n_steps, n))
        R = mu_m + Z @ L.T
    elif model == "lognormal":
        sig = np.sqrt(np.diag(cov_m))
        mu_log = np.log1p(mu_m) - 0.5 * np.log1p(sig ** 2)
        Z = rng.standard_normal((n_sims, n_steps, n))
        R = np.expm1(mu_log + Z @ L.T)
    elif model == "student_t":
        Z = rng.standard_normal((n_sims, n_steps, n))
        chi = rng.chisquare(dof, (n_sims, n_steps, 1))
        R = mu_m + (Z @ L.T) * np.sqrt(dof / chi)
    elif model == "historical_residual":
        # systematic factor = asset `factor_idx`; residuals resampled iid normal
        beta = cov_m[:, factor_idx] / max(cov_m[factor_idx, factor_idx], 1e-12)
        resid_var = np.maximum(np.diag(cov_m) - beta ** 2 * cov_m[factor_idx, factor_idx], 1e-10)
        f = rng.normal(mu_m[factor_idx], np.sqrt(cov_m[factor_idx, factor_idx]), (n_sims, n_steps))
        R = np.empty((n_sims, n_steps, n))
        for i in range(n):
            if i == factor_idx:
                R[:, :, i] = f
            else:
                R[:, :, i] = mu_m[i] + beta[i] * (f - mu_m[factor_idx]) + rng.normal(0, np.sqrt(resid_var[i]), (n_sims, n_steps))
    else:
        raise ValueError(f"Unknown model {model}")
    return np.clip(R, -0.99, 5.0)


# ------------------------------------------------------------------ simulation core
def simulate_paths(asset_returns: np.ndarray, ctx: SimContext) -> dict:
    """asset_returns: (n_sims, n_months, n_assets) monthly simple returns."""
    n_sims, T, n_assets = asset_returns.shape
    values = np.zeros((n_sims, n_assets))
    port = np.zeros((n_sims, T))
    turnover_total = np.zeros(n_sims)
    rebalances = np.zeros(n_sims, dtype=int)
    reserve_bal = np.zeros(n_sims)
    facility = np.zeros(n_sims)
    min_reserve_after_pay = np.full(n_sims, np.inf)
    payments_funded = np.ones(n_sims, dtype=bool)
    withdrawals_unfunded = np.zeros(n_sims, dtype=bool)
    split_month = month_index(ctx, ctx.glide_end_year)
    target = ctx.glide_targets[["equity", "bond", "cash"]].values  # rows: years from start

    def class_weights(vals):
        total = vals.sum(axis=1)
        total = np.where(total <= 0, 1, total)
        return vals / total[:, None]

    def rebalance_to(vals, w_target):
        total = vals.sum(axis=1)
        new_vals = total[:, None] * w_target[None, :]
        traded = np.abs(new_vals - vals).sum(axis=1)
        cost = traded * ctx.transaction_cost
        frac = new_vals / np.maximum(total, 1e-12)[:, None]
        return np.maximum(new_vals - cost[:, None] * frac, 0), traded

    blend_row = np.zeros(n_assets)
    if ctx.bond_idx:
        blend_row[ctx.bond_idx] = ctx.bond_blend
    flat_reserve = blend_row.sum() <= 0  # no bond assets: reserve held as flat cash

    for m in range(T):
        yr_row = min(m // MONTHS_PER_YEAR, len(target) - 1)
        eq_t, bd_t, csh_t = target[yr_row]
        tgt = np.zeros(n_assets)
        tgt[ctx.equity_idx] = eq_t * ctx.class_base[ctx.equity_idx]
        tgt[ctx.bond_idx] = bd_t * ctx.class_base[ctx.bond_idx]
        tgt[ctx.cash_idx] = csh_t * ctx.class_base[ctx.cash_idx]

        if m in ctx.contributions:
            c = ctx.contributions[m]
            values += c * tgt

        if m in ctx.withdrawals and m < split_month:
            w = ctx.withdrawals[m]
            total = values.sum(axis=1)
            take = np.minimum(w, total)
            withdrawals_unfunded |= total < w - 1e-9
            values = values * (1 - take / np.maximum(total, 1e-12))[:, None]

        if m == split_month:
            v = values.sum(axis=1)
            reserve_bal = np.minimum(v, ctx.required_reserve)
            facility = v - ctx.required_reserve
            values = reserve_bal[:, None] * blend_row[None, :]

        if m in ctx.payment_months:
            base = reserve_bal if flat_reserve else values.sum(axis=1)
            reserve_bal = base - ctx.payment_amount
            payments_funded &= reserve_bal >= -1e-9
            min_reserve_after_pay = np.minimum(min_reserve_after_pay, reserve_bal)
            if not flat_reserve:
                values = np.maximum(reserve_bal, 0)[:, None] * blend_row[None, :]

        if m % MONTHS_PER_YEAR == 0 and 0 < m < split_month:
            values, tr = rebalance_to(values, tgt)
            turnover_total += tr
            rebalances += tr > 1e-9

        R = asset_returns[:, m, :]
        values = np.maximum(values * (1 + R), 0)
        port[:, m] = values.sum(axis=1)

        if m < split_month and m % MONTHS_PER_YEAR == MONTHS_PER_YEAR - 1 and ctx.band is not None:
            cw = class_weights(values)
            cls_dev = np.stack([
                cw[:, ctx.equity_idx].sum(axis=1) - eq_t,
                cw[:, ctx.bond_idx].sum(axis=1) - bd_t,
                cw[:, ctx.cash_idx].sum(axis=1) - csh_t,
            ])
            if ctx.band_mode == "relative":
                base = np.array([eq_t, bd_t, csh_t])
                breach = np.abs(cls_dev) > ctx.band * np.maximum(base, 1e-9)
            else:
                breach = np.abs(cls_dev) > ctx.band
            do = breach.any(axis=0)
            if do.any():
                sub_new, tr = rebalance_to(values[do], tgt)
                values[do] = sub_new
                turnover_total[do] += tr
                rebalances[do] += tr > 1e-9
                port[do, m] = values[do].sum(axis=1)

    growth_end = split_month
    growth_port = port[:, :growth_end]
    running_max = np.maximum.accumulate(growth_port, axis=1)
    dd_growth = np.where(running_max > 0, growth_port / np.maximum(running_max, 1e-12) - 1, 0)
    max_dd = dd_growth.min(axis=1)

    return {
        "portfolio_paths": port,
        "terminal_2033": port[:, growth_end - 1],
        "facility_contribution": facility,
        "reserve_balance_end": reserve_bal,
        "min_reserve_after_payment": min_reserve_after_pay,
        "all_payments_funded": payments_funded,
        "withdrawals_unfunded": withdrawals_unfunded,
        "max_drawdown_growth": max_dd,
        "turnover": turnover_total,
        "n_rebalances": rebalances,
        "split_month": split_month,
    }


# ------------------------------------------------------------------ driver
def run_monte_carlo(returns_gen: dict, ctx: SimContext, n_sims: int, seed: int,
                    model: str = "gaussian", batch: int = 2000, dof: int = 5) -> dict:
    rng = np.random.default_rng(seed)
    T = n_months(ctx)
    parts = []
    done = 0
    while done < n_sims:
        b = min(batch, n_sims - done)
        R = generate_returns(model, returns_gen["mu"], returns_gen["cov"], b, T, rng, dof)
        parts.append(simulate_paths(R, ctx))
        done += b
    out = {}
    for k in parts[0]:
        if isinstance(parts[0][k], np.ndarray):
            out[k] = np.concatenate([p[k] for p in parts])
        else:
            out[k] = parts[0][k]
    out["n_sims"] = n_sims
    out["model"] = model
    return out


def summarize_simulation(res: dict, ctx: SimContext, total_contributions: float) -> dict:
    term = res["terminal_2033"]
    paths = res["portfolio_paths"]
    split = res["split_month"]
    infl = ctx.inflation
    years_to_2033 = ctx.glide_end_year - ctx.start_year
    real_contrib = total_contributions * (1 + infl) ** years_to_2033
    pcts = [5, 10, 25, 50, 75, 90, 95]
    out = {
        "median_terminal": float(np.median(term)),
        "mean_terminal": float(term.mean()),
        "terminal_percentiles": {f"p{p}": float(np.percentile(term, p)) for p in pcts},
        "prob_terminal_gt_start": float((term > total_contributions).mean()),
        "prob_terminal_gt_real_start": float((term > real_contrib).mean()),
        "prob_withdrawals_unfunded": float(res["withdrawals_unfunded"].mean()),
        "prob_capital_depletion": float((term <= 1e-6).mean()),
        "prob_all_payments_funded": float(res["all_payments_funded"].mean()),
        "prob_dd_gt_10": float((res["max_drawdown_growth"] <= -0.10).mean()),
        "prob_dd_gt_20": float((res["max_drawdown_growth"] <= -0.20).mean()),
        "prob_dd_gt_30": float((res["max_drawdown_growth"] <= -0.30).mean()),
        "prob_dd_gt_40": float((res["max_drawdown_growth"] <= -0.40).mean()),
        "median_max_drawdown": float(np.median(res["max_drawdown_growth"])),
        "worst_max_drawdown": float(res["max_drawdown_growth"].min()),
        "facility_percentiles": {f"p{p}": float(np.percentile(res["facility_contribution"], p)) for p in pcts},
        "median_facility": float(np.median(res["facility_contribution"])),
        "prob_facility_negative": float((res["facility_contribution"] < 0).mean()),
        "cagr_money_weighted": float((np.median(term) / total_contributions) ** (1 / years_to_2033) - 1),
        "mean_turnover": float(res["turnover"].mean()),
        "mean_rebalances": float(res["n_rebalances"].mean()),
    }
    # capital-floor success (terminal real value above floor x inflation-adjusted contributions)
    for f in (1.0, 0.9, 0.8, 0.7):
        out[f"prob_floor_{int(f * 100)}"] = float((term >= f * real_contrib).mean())
    # fan percentiles over time
    fan = {p: np.percentile(paths[:, :split], p, axis=0) for p in (5, 10, 25, 50, 75, 90, 95)}
    out["fan"] = fan
    # sponsor checkpoint (case: 2031): value at the start of that year and the facility range it implies
    mck = month_index(ctx, ctx.checkpoint_year)
    vck = paths[:, mck - 1] if mck > 0 else paths[:, 0]
    out["checkpoint_year"] = ctx.checkpoint_year
    out["v_checkpoint_percentiles"] = {f"p{p}": float(np.percentile(vck, p)) for p in pcts}
    out["projected_facility_checkpoint"] = {f"p{p}": float(np.percentile(vck - ctx.required_reserve, p)) for p in pcts}
    out["v2031_percentiles"] = out["v_checkpoint_percentiles"]            # legacy keys
    out["projected_facility_2031"] = out["projected_facility_checkpoint"]
    # terminal VaR/CVaR on simulated terminal returns
    tr = term / total_contributions - 1
    q95, q99 = np.quantile(tr, 0.05), np.quantile(tr, 0.01)
    out["mc_var_95"] = float(-q95)
    out["mc_var_99"] = float(-q99)
    out["mc_cvar_95"] = float(-tr[tr <= q95].mean())
    out["mc_cvar_99"] = float(-tr[tr <= q99].mean())
    return out
