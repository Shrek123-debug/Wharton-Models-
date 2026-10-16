"""Markov regime model (spec sections 15-18)."""
from __future__ import annotations

import numpy as np
import pandas as pd

STATE_NAMES = ["severe_bear", "bear", "neutral", "bull", "strong_bull"]


def assign_states(annual_returns: pd.Series, thresholds: list[float]) -> pd.Series:
    th = np.asarray(thresholds)
    labels = np.array(STATE_NAMES)
    idx = np.searchsorted(th, annual_returns.values, side="right")
    return pd.Series(labels[idx], index=annual_returns.index)


def annual_portfolio_returns(portfolio_monthly: pd.Series) -> pd.Series:
    """Full calendar-year returns only (partial final year excluded)."""
    g = portfolio_monthly.groupby(portfolio_monthly.index.year)
    out = {}
    for y, grp in g:
        if len(grp) == 12:
            out[y] = float((1 + grp).prod() - 1)
    return pd.Series(out)


def transition_matrix(states: pd.Series) -> tuple[np.ndarray, pd.DataFrame]:
    n = len(STATE_NAMES)
    counts = np.zeros((n, n))
    idx = {s: i for i, s in enumerate(STATE_NAMES)}
    vals = states.values
    for a, b in zip(vals[:-1], vals[1:]):
        counts[idx[a], idx[b]] += 1
    P = np.zeros((n, n))
    row_counts = counts.sum(axis=1)
    for i in range(n):
        if row_counts[i] > 0:
            P[i] = counts[i] / row_counts[i]
        else:
            P[i, i] = 1.0  # unobserved state: assume persistence (flagged upstream)
    df = pd.DataFrame(P, index=STATE_NAMES, columns=STATE_NAMES)
    return P, df


def stationary_distribution(P: np.ndarray) -> np.ndarray:
    vals, vecs = np.linalg.eig(P.T)
    k = int(np.argmin(np.abs(vals - 1.0)))
    pi = np.real(vecs[:, k])
    pi = np.abs(pi)
    return pi / pi.sum()


def expected_durations(P: np.ndarray) -> pd.Series:
    diag = np.diag(P)
    return pd.Series([1 / max(1e-12, 1 - d) for d in diag], index=STATE_NAMES)


def state_stats(annual_returns: pd.Series, states: pd.Series) -> pd.DataFrame:
    rows = []
    for s in STATE_NAMES:
        r = annual_returns[states == s]
        rows.append({"state": s, "n_years": len(r),
                     "mean_return": float(r.mean()) if len(r) else float("nan"),
                     "std_return": float(r.std()) if len(r) > 1 else float("nan")})
    return pd.DataFrame(rows).set_index("state")


def run_markov(portfolio_monthly: pd.Series, thresholds: list[float],
               start_year: int, end_year: int, n_sims: int, seed: int) -> dict:
    annual = annual_portfolio_returns(portfolio_monthly)
    states = assign_states(annual, thresholds)
    P, P_df = transition_matrix(states)
    pi = stationary_distribution(P)
    stats_df = state_stats(annual, states)
    durations = expected_durations(P)

    current_state = states.iloc[-1]
    current_idx = STATE_NAMES.index(current_state)

    # year-by-year state distribution from current state (2025 -> 2027 is 2 steps)
    dist_by_year = {}
    v = np.zeros(len(STATE_NAMES))
    v[current_idx] = 1.0
    for y in range(start_year, end_year + 1):
        steps = y - annual.index[-1]
        v_k = v @ np.linalg.matrix_power(P, steps)
        dist_by_year[y] = v_k

    prob_bear_next = float(dist_by_year[start_year][0] + dist_by_year[start_year][1])
    prob_stay_bear = float(P[current_idx, current_idx]) if current_idx <= 1 else 0.0
    expected_annual_return = {y: float(dist_by_year[y] @ stats_df["mean_return"].values)
                              for y in dist_by_year}

    # Markov-driven simulation of the growth phase (regime paths + within-state bootstrap)
    rng = np.random.default_rng(seed)
    state_returns = {s: annual[states == s].values for s in STATE_NAMES}
    for s in STATE_NAMES:
        if len(state_returns[s]) == 0:
            state_returns[s] = np.array([stats_df.loc[s, "mean_return"] if np.isfinite(stats_df.loc[s, "mean_return"]) else 0.0])
    years = list(range(start_year, end_year))  # growth years 2027..2032
    terminal = np.ones(n_sims)
    state_paths = np.zeros((n_sims, len(years)), dtype=int)
    cur = np.full(n_sims, current_idx)
    cumP = np.cumsum(P, axis=1)
    pool = np.concatenate([state_returns[s] for s in STATE_NAMES])
    offsets = np.concatenate([[0], np.cumsum([len(state_returns[s]) for s in STATE_NAMES])])
    counts = np.array([len(state_returns[s]) for s in STATE_NAMES])
    for t, y in enumerate(years):
        u = rng.random((n_sims, 1))
        nxt = np.clip((u > cumP[cur][:, :-1]).sum(axis=1), 0, len(STATE_NAMES) - 1)
        state_paths[:, t] = nxt
        pick = offsets[nxt] + rng.integers(1, counts[nxt] + 1) - 1
        terminal *= 1 + pool[pick]
        cur = nxt

    bear_ever = ((state_paths <= 1).any(axis=1)).mean()
    bull_by_2032 = (state_paths[:, -1] >= 3).mean()

    return {
        "annual_returns": annual,
        "states": states,
        "P": P,
        "P_df": P_df,
        "stationary": pi,
        "state_stats": stats_df,
        "durations": durations,
        "current_state": current_state,
        "dist_by_year": dist_by_year,
        "prob_bear_next": prob_bear_next,
        "prob_stay_bear": prob_stay_bear,
        "expected_annual_return": expected_annual_return,
        "terminal_values": terminal,
        "bear_ever_prob": float(bear_ever),
        "bull_by_end_prob": float(bull_by_2032),
        "transition_counts_note": "Transitions estimated from full calendar years of the current-weight portfolio.",
    }


def markov_summary(res: dict, total_contributions: float, required_reserve: float) -> dict:
    term = res["terminal_values"] * total_contributions
    pcts = [5, 10, 25, 50, 75, 90, 95]
    facility = term - required_reserve
    out = {
        "median_terminal": float(np.median(term)),
        "mean_terminal": float(term.mean()),
        "terminal_percentiles": {f"p{p}": float(np.percentile(term, p)) for p in pcts},
        "prob_terminal_gt_start": float((term > total_contributions).mean()),
        "prob_facility_negative": float((facility < 0).mean()),
        # Markov simulates the growth phase only, so reserve funding is inferred from the
        # 2033 split: the reserve is fully funded exactly when the facility is not negative.
        "prob_all_payments_funded": float((facility >= 0).mean()),
        "facility_percentiles": {f"p{p}": float(np.percentile(facility, p)) for p in pcts},
        "prob_bear_next": res["prob_bear_next"],
        "bear_ever_prob": res["bear_ever_prob"],
        "bull_by_end_prob": res["bull_by_end_prob"],
        "stationary": dict(zip(STATE_NAMES, res["stationary"])),
        "expected_durations": res["durations"].to_dict(),
    }
    tr = term / total_contributions - 1
    q95, q99 = np.quantile(tr, 0.05), np.quantile(tr, 0.01)
    out["mc_var_95"] = float(-q95)
    out["mc_var_99"] = float(-q99)
    out["mc_cvar_95"] = float(-tr[tr <= q95].mean())
    out["mc_cvar_99"] = float(-tr[tr <= q99].mean())
    return out
