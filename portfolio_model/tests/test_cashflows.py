"""The cash-flow schedule must match the Gao case rules exactly, and the simulator must obey it."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cashflows.schedule import CashflowError, build_schedule, validated_schedule  # noqa: E402
from src.config import load_config  # noqa: E402
from src.monte_carlo.mc import SimContext, required_reserve_pv, simulate_paths, summarize_simulation  # noqa: E402


@pytest.fixture
def cfg():
    return load_config()


def _break(cfg, fn):
    c = copy.deepcopy(cfg)
    fn(c)
    return c


# ----------------------------------------------------------------- the case, as written
def test_shipped_config_is_exactly_the_case(cfg):
    s = validated_schedule(cfg)
    assert s.contribution_months == {0: 300_000, 12: 150_000}           # start of 2027, start of 2028
    assert s.withdrawal_months == {}                                    # no withdrawals before 2033
    assert s.payment_amount == 50_000 and len(s.payments) == 10
    assert (s.first_payment_year, s.last_payment_year) == (2033, 2042)
    assert s.payment_months == [(y - 2027) * 12 for y in range(2033, 2043)]   # one year apart
    assert s.reserve_setup_year == 2033 and s.checkpoint_year == 2031
    assert s.net_invested == 450_000


def test_year_numbers_follow_the_case(cfg):
    s = validated_schedule(cfg)
    by_year = {e.year: e.year_number(s.year_zero) for e in s.contributions}
    assert by_year == {2027: 1, 2028: 2}
    assert s.checkpoint_year - s.year_zero == 5 and s.reserve_setup_year - s.year_zero == 7


# ----------------------------------------------------------------- anything else is refused
@pytest.mark.parametrize("mutate,needle", [
    (lambda c: c["cashflows"]["contributions"][0].update(amount=250_000), "contribution 2027"),
    (lambda c: c["cashflows"]["contributions"][1].update(year=2029), "contribution 2029"),
    (lambda c: c["cashflows"]["contributions"].append({"year": 2030, "amount": 10_000}), "contribution 2030"),
    (lambda c: c["cashflows"].update(withdrawals=[{"year": 2030, "amount": 5_000}]), "withdrawal"),
    (lambda c: c["cashflows"]["reserve_payments"].update(amount=60_000), "operating payment"),
    (lambda c: (c["cashflows"]["reserve_payments"].update(last_year=2041),
                c["simulation"].update(reserve_end_year=2041)), "9 operating payments"),
    (lambda c: c["cashflows"].update(sponsor_checkpoint_year=2030), "sponsor checkpoint"),
    (lambda c: c["cashflows"].update(year_zero=2027), "year_zero"),
])
def test_deviations_from_the_case_are_refused(cfg, mutate, needle):
    with pytest.raises(CashflowError) as e:
        validated_schedule(_break(cfg, mutate))
    assert needle in str(e.value)


def test_enforce_false_allows_what_if_runs(cfg):
    c = _break(cfg, lambda c: (c["cashflows"].update(withdrawals=[{"year": 2030, "amount": 5_000}]),
                               c["case_rules"].update(enforce=False)))
    s = validated_schedule(c)
    assert s.withdrawal_months == {36: 5_000} and s.net_invested == 445_000


@pytest.mark.parametrize("mutate", [
    lambda c: c["cashflows"]["contributions"][0].update(timing="end"),         # must be start of year
    lambda c: c["cashflows"]["reserve_payments"].update(timing="end"),
    lambda c: c["cashflows"]["contributions"][0].update(amount=-1),
    lambda c: c["cashflows"].update(withdrawals=[{"year": 2033, "amount": 1}]),   # not modelled after set-up
    lambda c: c["cashflows"].update(reserve_setup_year=2032),
    lambda c: c["cashflows"].update(contributions=[]),
])
def test_malformed_schedules_fail_structurally_even_without_enforcement(cfg, mutate):
    c = _break(cfg, mutate)
    c["case_rules"]["enforce"] = False
    with pytest.raises(CashflowError):
        validated_schedule(c)


def test_describe_restates_the_schedule(cfg):
    text = " | ".join(build_schedule(cfg).describe())
    for part in ("$300,000", "2027 (Year 1)", "$150,000", "2028 (Year 2)", "no withdrawals",
                 "2033 (Year 7)", "10 operating payments of $50,000", "not inflation-adjusted", "2033-2042"):
        assert part in text


# ----------------------------------------------------------------- simulator obeys the schedule
def _ctx(cfg, **over):
    s = build_schedule(cfg)
    targets = pd.DataFrame({"equity": [0.7] * 7, "bond": [0.175] * 7, "cash": [0.125] * 7}, index=range(2027, 2034))
    base = np.array([0.5, 0.5, 1.0, 1.0])
    kw = dict(withdrawals=s.withdrawal_months, checkpoint_year=s.checkpoint_year, schedule=s)
    kw.update(over)
    return SimContext(2027, 2033, 2042, [0, 1], [2], [3], targets, s.contribution_months,
                      required_reserve_pv(50_000, 2033, 2042, 0.029), s.payment_months, 50_000,
                      None, "absolute", 0.0, 0.02, np.array([1.0]), base, **kw)


def test_zero_return_portfolio_equals_net_cash_in(cfg):
    res = simulate_paths(np.zeros((3, 192, 4)), _ctx(cfg))
    assert res["terminal_2033"] == pytest.approx([450_000] * 3)         # exactly the case's $450k
    assert res["facility_contribution"] == pytest.approx(450_000 - required_reserve_pv(50_000, 2033, 2042, 0.029))
    assert res["withdrawals_unfunded"].sum() == 0


def test_withdrawal_leaves_the_portfolio_at_the_right_time(cfg):
    c = _break(cfg, lambda c: (c["cashflows"].update(withdrawals=[{"year": 2030, "amount": 20_000}]),
                               c["case_rules"].update(enforce=False)))
    res = simulate_paths(np.zeros((2, 192, 4)), _ctx(c))
    assert res["terminal_2033"] == pytest.approx([430_000] * 2)         # 450k - 20k, zero returns
    # before the withdrawal month (Jan 2030 = month 36) the balance is still 450k, after it 430k
    assert res["portfolio_paths"][0, 35] == pytest.approx(450_000)
    assert res["portfolio_paths"][0, 36] == pytest.approx(430_000)


def test_withdrawal_larger_than_balance_is_flagged_not_negative(cfg):
    c = _break(cfg, lambda c: (c["cashflows"].update(withdrawals=[{"year": 2029, "amount": 900_000}]),
                               c["case_rules"].update(enforce=False)))
    res = simulate_paths(np.zeros((2, 192, 4)), _ctx(c))
    assert res["withdrawals_unfunded"].all()
    assert (res["portfolio_paths"] >= 0).all()


def test_checkpoint_year_comes_from_the_schedule(cfg):
    ctx = _ctx(cfg)
    res = simulate_paths(np.zeros((4, 192, 4)), ctx)
    s = summarize_simulation(res, ctx, 450_000)
    assert s["checkpoint_year"] == 2031
    # value at the start of 2031 (zero returns) is all $450k; range = 450k - reserve
    assert s["projected_facility_checkpoint"]["p50"] == pytest.approx(450_000 - ctx.required_reserve)
