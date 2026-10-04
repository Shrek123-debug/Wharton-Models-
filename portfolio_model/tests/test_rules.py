"""Tests for the deterministic rule-flag engine. No network access required."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.rules.rule_engine import SEVERITY_ORDER, build_rule_flags

CFG = {
    "risk": {"max_position_weight": 0.25, "max_sector_weight": 0.35,
             "max_correlated_group_weight": 0.30, "min_cash_weight": 0.05,
             "correlation_threshold": 0.70},
    "rebalancing": {"enabled": True, "method": "absolute", "band": 0.05},
    "glide_path": {"enabled": True},
    "sector_targets": {"Information Technology": 0.25},
}


def _inputs():
    holdings = pd.DataFrame({
        "ticker": ["ADBE", "DUOL", "DIS", "VOO", "IEF", "CASH"],
        "weight": [0.20, 0.18, 0.10, 0.30, 0.12, 0.10],
        "asset_class": ["US Equity", "US Equity", "US Equity", "ETF", "Treasury", "Cash"],
        "sector": ["Information Technology", "Information Technology", "Communication Services",
                   "Broad Market (ETF)", "Bonds", "Cash"],
        "correlation_group": ["Growth/Consumer-Tech", "Growth/Consumer-Tech", "Growth/Consumer-Tech",
                              None, None, None],
        "target_weight": [0.14, np.nan, np.nan, np.nan, np.nan, np.nan],
        "thesis": ["a" * 30, None, "a" * 30, "a" * 30, "a" * 30, "a" * 30],
    })
    sec_tbl = pd.DataFrame({
        "weight": [0.38, 0.10, 0.30, 0.12, 0.10],
        "holdings": ["ADBE, DUOL", "DIS", "VOO", "IEF", "CASH"],
    }, index=["Information Technology", "Communication Services", "Broad Market (ETF)", "Bonds", "Cash"])
    conc = {"largest": ("VOO", 0.30), "top3": 0.68, "top5": 0.90, "top10": 1.0,
            "hhi": {"raw": 0.2068, "normalized": 0.46, "effective_n": 4.84, "n_holdings": 6}}
    corr_flags = [{"a": "ADBE", "b": "DUOL", "correlation": 0.78, "issue": "HIGH CORRELATION"}]
    mc_sum = {"prob_dd_gt_20": 0.30, "mc_cvar_95": 0.22, "prob_all_payments_funded": 0.95,
              "prob_terminal_gt_start": 0.92, "median_max_drawdown": -0.14}
    bs_sum = {"prob_dd_gt_20": 0.42, "mc_cvar_95": 0.35, "prob_all_payments_funded": 0.86,
              "prob_terminal_gt_start": 0.80, "median_max_drawdown": -0.21}
    mk_sum = {}
    disagreement = pd.DataFrame([{"metric": "reserve funded", "difference": "9.0%", "flag": "Engines broadly agree"}])
    confidence = {"ADBE": "High", "DUOL": "Low", "DIS": "High", "VOO": "High", "IEF": "High", "CASH": "High"}
    reb_df = pd.DataFrame([
        {"class": "Equity", "current_weight": 0.78, "target": 0.70, "lower_band": 0.65,
         "upper_band": 0.75, "trigger": True, "suggested_trade": 0.0, "turnover": 0.08},
        {"class": "Bonds", "current_weight": 0.12, "target": 0.175, "lower_band": 0.125,
         "upper_band": 0.225, "trigger": True, "suggested_trade": 0.055, "turnover": 0.055},
    ])
    sens_interp = {"fragile_vol_threshold": 1.3}
    return holdings, sec_tbl, conc, corr_flags, mc_sum, bs_sum, mk_sum, disagreement, confidence, reb_df, sens_interp


def _flags():
    return build_rule_flags(CFG, *_inputs())


def test_every_flag_has_required_fields():
    for f in _flags():
        for key in ("id", "severity", "category", "metric", "current_value", "threshold",
                    "rule", "action", "evidence"):
            assert key in f and f[key] is not None, f"flag {f.get('id')} missing {key}"
        assert f["severity"] in SEVERITY_ORDER


def test_position_cap_flag():
    flags = _flags()
    pos = [f for f in flags if f["id"].startswith("POS")]
    assert any(f["metric"].startswith("VOO") and np.isclose(f["current_value"], 0.30)
               and np.isclose(f["threshold"], 0.25) for f in pos)


def test_group_cap_flag():
    flags = _flags()
    grp = [f for f in flags if f["id"].startswith("GRP")]
    assert any("Growth/Consumer-Tech" in f["metric"] and np.isclose(f["current_value"], 0.48)
               and np.isclose(f["threshold"], 0.30) for f in grp)


def test_sector_target_band_flag():
    flags = _flags()
    sec = [f for f in flags if f["id"].startswith("SBND")]
    assert any("Information Technology" in f["metric"] and np.isclose(f["current_value"], 0.38)
               and np.isclose(f["threshold"], 0.30) for f in sec)  # target 0.25 + 5pp band


def test_target_drift_flag():
    flags = _flags()
    drf = [f for f in flags if f["id"].startswith("DRF")]
    assert any("ADBE" in f["metric"] and np.isclose(f["current_value"], 0.06) for f in drf)


def test_correlation_drawdown_tail_reserve_flags():
    flags = _flags()
    assert any(f["id"].startswith("CORR") and np.isclose(f["current_value"], 0.78) for f in flags)
    assert any(f["id"].startswith("DD") and f["category"] == "Drawdown" for f in flags)
    tail = [f for f in flags if f["id"].startswith("TAIL")]
    assert any(np.isclose(f["current_value"], 0.35) for f in tail)  # bootstrap CVaR 35% > 30%
    assert any(f["id"].startswith("RESV") and np.isclose(f["current_value"], 0.86) for f in flags)


def test_confidence_thesis_rebalance_flags():
    flags = _flags()
    assert any(f["id"].startswith("CONF") and "DUOL" in f["metric"] for f in flags)
    assert any(f["id"].startswith("THESIS") and "DUOL" in f["evidence"] for f in flags)
    reb = [f for f in flags if f["id"].startswith("REBAL")]
    assert len(reb) == 2


def test_clean_portfolio_triggers_no_flags():
    holdings, sec_tbl, conc, corr_flags, mc_sum, bs_sum, mk_sum, disagreement, confidence, reb_df, sens_interp = _inputs()
    holdings = holdings.copy()
    holdings["weight"] = [0.15, 0.10, 0.15, 0.25, 0.25, 0.10]
    holdings["target_weight"] = np.nan
    holdings["correlation_group"] = None
    holdings["thesis"] = ["solid thesis text"] * 6
    sec_tbl = pd.DataFrame({"weight": [0.25, 0.15, 0.25, 0.25, 0.10],
                            "holdings": ["ADBE, DUOL", "DIS", "VOO", "IEF", "CASH"]},
                           index=sec_tbl.index)
    conc = {"largest": ("VOO", 0.25), "top3": 0.65, "top5": 0.90, "top10": 1.0,
            "hhi": {"raw": 0.19, "normalized": 0.028, "effective_n": 5.26, "n_holdings": 6}}
    mc_sum = {**mc_sum, "prob_dd_gt_20": 0.10, "mc_cvar_95": 0.15,
              "prob_all_payments_funded": 0.97, "prob_terminal_gt_start": 0.95}
    bs_sum = {**bs_sum, "prob_dd_gt_20": 0.15, "mc_cvar_95": 0.20,
              "prob_all_payments_funded": 0.95, "prob_terminal_gt_start": 0.90}
    confidence = {t: "High" for t in holdings["ticker"]}
    reb_df = reb_df.assign(trigger=False)
    flags = build_rule_flags(CFG, holdings, sec_tbl, conc, [], mc_sum, bs_sum, mk_sum,
                             disagreement, confidence, reb_df, {"fragile_vol_threshold": 1.5})
    # HHI effective bets 5.26 of 6 = 88% > 60% -> no HHI flag; everything else clean
    assert flags == []


def test_flags_sorted_by_severity():
    flags = _flags()
    ranks = [SEVERITY_ORDER[f["severity"]] for f in flags]
    assert ranks == sorted(ranks)
