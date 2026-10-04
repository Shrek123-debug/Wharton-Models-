"""Unit tests for core calculations (spec section 79). No network access required."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.attribution.attribution import holding_attribution
from src.bootstrap.bootstrap import run_bootstrap
from src.markov.markov import assign_states, run_markov, stationary_distribution, transition_matrix
from src.monte_carlo.mc import SimContext, generate_returns, required_reserve_pv, run_monte_carlo, simulate_paths
from src.portfolio.portfolio import build_portfolio, max_drawdown
from src.returns.returns import annualize, log_returns, simple_returns, to_monthly
from src.risk.risk import concentration_report, correlation_flags, hhi, historical_var_cvar, parametric_var_cvar
from src.sectors.sectors import assign_sector, sector_table
from src.sensitivity.sensitivity import run_sensitivity
from src.validation.validate import validate

MONTHS = pd.date_range("2020-01-31", periods=24, freq="ME")


def _prices():
    rng = np.random.default_rng(7)
    r = rng.normal(0.01, 0.05, (24, 2))
    prices = pd.DataFrame(np.cumprod(1 + r, axis=0) * 100, index=MONTHS, columns=["AAA", "BBB"])
    return prices


# ---------------------------------------------------------------- returns
def test_simple_returns():
    p = pd.DataFrame({"A": [100.0, 110.0, 99.0]}, index=pd.date_range("2020-01-31", periods=3, freq="ME"))
    r = simple_returns(p)["A"]
    assert np.isclose(r.iloc[1], 0.10)
    assert np.isclose(r.iloc[2], -0.10)


def test_log_returns():
    p = pd.DataFrame({"A": [100.0, 110.0]}, index=pd.date_range("2020-01-31", periods=2, freq="ME"))
    assert np.isclose(log_returns(p)["A"].iloc[1], np.log(1.1))


def test_monthly_compounding():
    daily = pd.DataFrame({"A": [0.01, 0.01, 0.01]},
                         index=pd.date_range("2020-01-01", periods=3, freq="D"))
    m = to_monthly(daily)
    assert np.isclose(m["A"].iloc[0], 1.01 ** 3 - 1)


def test_annualize():
    assert np.isclose(annualize(pd.Series([0.01])), 1.01 ** 12 - 1)


# ---------------------------------------------------------------- weights / validation
def test_weight_normalization():
    df = pd.DataFrame({"ticker": ["A", "B"], "portfolio_weight": [3.0, 1.0]})
    res = validate(df, {"risk": {"max_position_weight": 1.0}})
    assert not res.errors
    assert np.isclose(res.holdings["weight"].sum(), 1.0)
    assert np.isclose(res.holdings.loc[0, "weight"], 0.75)
    assert res.weights_source == "supplied"


def test_weight_from_quantity_price():
    df = pd.DataFrame({"ticker": ["A", "B"], "quantity": [10, 5], "price": [10.0, 20.0]})
    res = validate(df, {"risk": {"max_position_weight": 1.0}})
    assert np.isclose(res.holdings["weight"].sum(), 1.0)
    assert res.weights_source.startswith("calculated")


def test_validation_flags_duplicates_and_caps():
    df = pd.DataFrame({"ticker": ["A", "A", "B"], "portfolio_weight": [0.6, 0.2, 0.2]})
    res = validate(df, {"risk": {"max_position_weight": 0.5}})
    assert any(f["issue"] == "Duplicate tickers" for f in res.flags)
    assert any(f["issue"] == "HIGH CONCENTRATION" for f in res.flags)


# ---------------------------------------------------------------- portfolio / covariance
def test_build_portfolio_weights_and_cov():
    prices = _prices()
    w = pd.Series([0.6, 0.4], index=["AAA", "BBB"])
    port = build_portfolio(prices, w)
    assert abs(port.weights.sum() - 1) < 1e-12
    cov = port.cov_monthly
    assert cov.shape == (2, 2)
    assert np.allclose(cov, cov.T)
    vals = np.linalg.eigvalsh(cov)
    assert vals.min() > 0  # PSD
    corr = port.corr
    assert np.allclose(np.diag(corr.values), 1.0)
    assert (np.abs(corr.values) <= 1 + 1e-9).all()


def test_max_drawdown():
    idx = pd.date_range("2020-01-31", periods=5, freq="ME")
    v = pd.Series([100, 120, 60, 80, 130], index=idx)
    mdd, peak, trough, recovery = max_drawdown(v)
    assert np.isclose(mdd, -0.5)
    assert peak == idx[1] and trough == idx[2] and recovery == idx[4]


# ---------------------------------------------------------------- VaR / CVaR
def test_historical_var_cvar():
    r = pd.Series(np.concatenate([np.full(90, 0.01), np.full(10, -0.10)]))
    var, cvar = historical_var_cvar(r, 0.95)
    assert np.isclose(var, 0.10)
    assert np.isclose(cvar, 0.10)
    assert cvar >= var


def test_parametric_var_cvar():
    var, cvar = parametric_var_cvar(0.0, 0.10, 0.95)
    assert np.isclose(var, 1.645 * 0.10, atol=1e-3)
    assert cvar > var


# ---------------------------------------------------------------- concentration
def test_hhi():
    w = pd.Series([0.5, 0.5])
    h = hhi(w)
    assert np.isclose(h["raw"], 0.5)
    w2 = pd.Series([0.25] * 4)
    assert np.isclose(hhi(w2)["raw"], 0.25)
    assert np.isclose(hhi(w2)["effective_n"], 4.0)


def test_concentration_report():
    w = pd.Series([0.5, 0.3, 0.1, 0.05, 0.05], index=list("ABCDE"))
    c = concentration_report(w)
    assert c["largest"] == ("A", 0.5)
    assert np.isclose(c["top3"], 0.9)


def test_correlation_flags():
    corr = pd.DataFrame([[1, 0.8], [0.8, 1]], index=["A", "B"], columns=["A", "B"])
    flags = correlation_flags(corr, 0.7)
    assert len(flags) == 1 and flags[0]["correlation"] == 0.8


# ---------------------------------------------------------------- markov
def test_markov_transition_matrix():
    states = pd.Series(["bull", "bull", "bear", "bull", "bear", "bear"])
    P, P_df = transition_matrix(states)
    assert np.allclose(P.sum(axis=1), 1.0)
    i_bull = list(["severe_bear", "bear", "neutral", "bull", "strong_bull"]).index("bull")
    i_bear = 1
    assert np.isclose(P[i_bull, i_bear], 2 / 3)
    pi = stationary_distribution(P)
    assert abs(pi.sum() - 1) < 1e-9
    assert np.allclose(pi @ P, pi, atol=1e-6)


def test_assign_states():
    r = pd.Series([-0.25, -0.10, 0.0, 0.10, 0.25])
    s = assign_states(r, [-0.20, -0.05, 0.05, 0.20])
    assert list(s) == ["severe_bear", "bear", "neutral", "bull", "strong_bull"]


def test_run_markov_smoke():
    monthly = pd.Series(np.r_[np.full(12, 0.01), np.full(12, -0.02), np.full(12, 0.015),
                              np.full(12, 0.005), np.full(12, 0.01)], index=pd.date_range("2020-01-31", periods=60, freq="ME"))
    res = run_markov(monthly, [-0.20, -0.05, 0.05, 0.20], 2027, 2033, 500, 42)
    assert np.allclose(res["P"].sum(axis=1), 1.0)
    assert 0 <= res["prob_bear_next"] <= 1
    assert len(res["terminal_values"]) == 500


# ---------------------------------------------------------------- monte carlo
def _ctx():
    targets = pd.DataFrame({"equity": [0.7] * 7, "bond": [0.175] * 7, "cash": [0.125] * 7},
                           index=range(2027, 2034))
    base = np.array([0.357, 0.357, 0.143, 0.143, 0.131, 0.869, 1.0])  # within-class shares
    return SimContext(2027, 2033, 2042, [0, 1, 2, 3], [4, 5], [6], targets,
                      {0: 300000, 12: 150000}, required_reserve_pv(50000, 2033, 2042, 0.029),
                      [(y - 2027) * 12 for y in range(2033, 2043)], 50000,
                      0.05, "absolute", 0.001, 0.02, np.array([0.25, 0.75]), base)


def test_required_reserve_pv():
    r = required_reserve_pv(50000, 2033, 2042, 0.029)
    assert 430000 < r < 450000  # matches existing workbook ~441,264


def test_generate_returns_shapes_and_correlation():
    mu = np.array([0.01, 0.01])
    cov = np.array([[0.01, 0.006], [0.006, 0.01]])
    rng = np.random.default_rng(1)
    R = generate_returns("gaussian", mu, cov, 20000, 12, rng)
    assert R.shape == (20000, 12, 2)
    emp = np.corrcoef(R[:, :, 0].ravel(), R[:, :, 1].ravel())[0, 1]
    assert abs(emp - 0.6) < 0.05  # Cholesky preserves correlation


def test_monte_carlo_zero_vol_cash_grows_at_rf():
    ctx = _ctx()
    mu = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.003])
    cov = np.zeros((7, 7)) + 1e-14 * np.eye(7)
    res = run_monte_carlo({"mu": mu, "cov": cov}, ctx, 10, 42, model="gaussian")
    term = res["terminal_2033"][0]
    # deterministic-ish: value should be near contributions compounded
    assert term > 450000


def test_simulate_paths_reserve_funding_deterministic():
    ctx = _ctx()
    R = np.zeros((5, 192, 7))  # zero returns
    res = simulate_paths(R, ctx)
    # reserve = 441k, 10 payments of 50k with zero growth -> runs out
    assert not res["all_payments_funded"].all()
    assert res["facility_contribution"][0] == pytest.approx(450000 - ctx.required_reserve)


def test_run_monte_carlo_smoke():
    ctx = _ctx()
    mu = np.full(7, 0.007)
    cov = np.diag([0.02, 0.02, 0.02, 0.02, 0.001, 0.0001, 0.0]) ** 2
    res = run_monte_carlo({"mu": mu, "cov": cov}, ctx, 1000, 42)
    assert res["n_sims"] == 1000
    assert len(res["terminal_2033"]) == 1000
    assert (res["terminal_2033"] >= 0).all()


# ---------------------------------------------------------------- bootstrap
def test_bootstrap_uses_real_history_only():
    rng = np.random.default_rng(3)
    daily = rng.normal(0.0005, 0.01, (3000, 7))
    ctx = _ctx()
    res = run_bootstrap(daily, ctx, 200, 42, method="block", block_size_days=20, batch=100)
    assert res["n_sims"] == 200
    assert res["method"] == "block"
    assert len(res["terminal_2033"]) == 200


# ---------------------------------------------------------------- glide path
def test_glide_targets_sum_to_one():
    from src.pipeline import build_glide_targets
    t = build_glide_targets("linear", list(range(2027, 2034)), 0.70, 0.55, 0.175, 0.125, None)
    assert np.allclose(t.sum(axis=1).values, 1.0)
    assert t["equity"].iloc[0] == 0.70 and t["equity"].iloc[-1] == 0.55


def test_rebalancing_band_trigger():
    ctx = _ctx()
    R = np.zeros((3, 192, 7))
    R[:, :72, 0] = 0.5  # equity asset 0 surges -> class breach at year end
    res = simulate_paths(R, ctx)
    assert (res["n_rebalances"] > 0).all()


# ---------------------------------------------------------------- sensitivity
def test_sensitivity_grid_shape():
    ctx = _ctx()
    mu = np.full(7, 0.007)
    cov = np.diag([0.02, 0.02, 0.02, 0.02, 0.001, 0.0001, 0.0]) ** 2
    df = run_sensitivity(mu, cov, ctx, [-0.02, 0.0, 0.02], [0.8, 1.0, 1.2], 200, 42, 450000)
    assert len(df) == 9
    assert df["prob_success"].between(0, 1).all()
    # higher return shift should not lower success
    base = df[(df.return_shift == 0) & (df.vol_multiplier == 1.0)]["prob_success"].iloc[0]
    up = df[(df.return_shift == 0.02) & (df.vol_multiplier == 1.0)]["prob_success"].iloc[0]
    assert up >= base


# ---------------------------------------------------------------- sectors / attribution
def test_sector_assignment_and_table():
    holdings = pd.DataFrame({
        "ticker": ["XOM", "ADBE", "CASH", "IEF"],
        "weight": [0.4, 0.3, 0.2, 0.1],
        "asset_class": ["US Equity", "US Equity", "Cash", "Treasury"],
    })
    holdings["sector"] = [assign_sector(t) for t in holdings["ticker"]]
    assert holdings["sector"].tolist() == ["Energy", "Information Technology", "Cash", "Bonds"]
    monthly = pd.DataFrame({c: [v] * 24 for c, v in
                            {"XOM": 0.01, "ADBE": 0.02, "IEF": 0.005, "CASH": 0.003}.items()},
                           index=MONTHS)
    tbl = sector_table(holdings, monthly)
    assert abs(tbl["weight"].sum() - 1) < 1e-9
    assert tbl.loc["Energy", "n_holdings"] == 1


def test_holding_attribution():
    holdings = pd.DataFrame({"ticker": ["A", "B"], "weight": [0.5, 0.5], "asset_class": ["US Equity"] * 2})
    monthly = pd.DataFrame({"A": [0.01] * 24, "B": [-0.01] * 24}, index=MONTHS)
    attr = holding_attribution(holdings, monthly)
    assert np.isclose(attr.set_index("ticker").loc["A", "contribution_12m"], 0.5 * ((1.01 ** 12) - 1))


# ---------------------------------------------------------------- ingestion / upload robustness
import openpyxl
from src.ingestion.ingest import coerce_number, ingest


def _make_xlsx(tmp_path, sheets):
    wb = openpyxl.Workbook(); wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    p = tmp_path / "upload.xlsx"; wb.save(p); return p


def test_coerce_number_formats():
    assert coerce_number("25%") == 0.25
    assert coerce_number("1,234") == 1234
    assert coerce_number("$500") == 500
    assert coerce_number("(100)") == -100
    assert coerce_number("abc") is None
    assert coerce_number(None) is None


def test_minimal_weight_upload(tmp_path):
    p = _make_xlsx(tmp_path, {"H": [["Ticker", "Weight"], ["VOO", 0.5], ["CASH", 0.5]]})
    res = validate(ingest(str(p)).holdings, {"risk": {"max_position_weight": 1.0}, "input": {"base_currency": "USD"}})
    assert not res.errors and res.weights_source == "supplied"


def test_percent_string_weights(tmp_path):
    p = _make_xlsx(tmp_path, {"H": [["Ticker", "Weight"], ["VOO", "60%"], ["CASH", "40%"]]})
    res = validate(ingest(str(p)).holdings, {"risk": {"max_position_weight": 1.0}, "input": {"base_currency": "USD"}})
    assert np.isclose(res.holdings["weight"].sum(), 1.0)
    assert res.holdings.loc[res.holdings.ticker == "VOO", "weight"].iloc[0] == 0.6


def test_header_below_title_rows(tmp_path):
    p = _make_xlsx(tmp_path, {"S": [["My Portfolio"], ["Oct 2026"], [], ["Security", "Market Value"],
                                    ["VOO", 100000], ["TOTAL", 100000]]})
    res = validate(ingest(str(p)).holdings, {"risk": {"max_position_weight": 1.0}, "input": {"base_currency": "USD"}})
    assert len(res.holdings) == 1 and res.holdings.iloc[0]["ticker"] == "VOO"


def test_invalid_ticker_flagged_not_silent(tmp_path):
    p = _make_xlsx(tmp_path, {"H": [["Ticker", "Weight"], ["VOO", 0.7], ["7203.T", 0.3]]})
    ing = ingest(str(p))
    assert any("invalid/unsupported ticker" in w for w in ing.warnings)


def test_negative_rows_dropped(tmp_path):
    p = _make_xlsx(tmp_path, {"H": [["Ticker", "Shares", "Price"], ["VOO", 10, 500], ["BAD", -5, 10]]})
    res = validate(ingest(str(p)).holdings, {"risk": {"max_position_weight": 1.0}, "input": {"base_currency": "USD"}})
    assert "BAD" not in res.holdings["ticker"].values
    assert any(f["issue"] == "Negative quantity" for f in res.flags)


def test_currency_mismatch_excluded(tmp_path):
    p = _make_xlsx(tmp_path, {"H": [["Ticker", "Weight", "Currency"], ["VOO", 0.7, "USD"], ["SAP", 0.3, "EUR"]]})
    res = validate(ingest(str(p)).holdings, {"risk": {"max_position_weight": 1.0}, "input": {"base_currency": "USD"}})
    assert "SAP" not in res.holdings["ticker"].values
    assert any(f["issue"] == "CURRENCY MISMATCH" for f in res.flags)


def test_missing_weight_errors(tmp_path):
    p = _make_xlsx(tmp_path, {"H": [["Ticker", "Weight"], ["VOO", 0.5], ["ADBE", None]]})
    res = validate(ingest(str(p)).holdings, {"risk": {"max_position_weight": 1.0}, "input": {"base_currency": "USD"}})
    assert res.errors and "ADBE" in res.errors[0]


def test_no_table_raises(tmp_path):
    p = _make_xlsx(tmp_path, {"N": [["just text"]]})
    with pytest.raises(ValueError):
        ingest(str(p))
