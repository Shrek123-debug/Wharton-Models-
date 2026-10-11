"""Run comparison: the assumption-change experiment, made reproducible from the CLI."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

PKG_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG_ROOT))

from src.compare import _is_money, compare_runs, flag_deltas, format_comparison, headline_metrics  # noqa: E402


def _fake_run(median: float, funded: float, flags: list[dict]) -> dict:
    return {
        "comparison_sheet": pd.DataFrame([
            {"metric": "Median terminal value (2033)", "Monte Carlo": median,
             "Historical Bootstrap": median * 1.01},
            {"metric": "Probability reserve fully funded", "Monte Carlo": funded,
             "Historical Bootstrap": funded * 0.5},
            {"metric": "CVaR 95% (terminal)", "Monte Carlo": 0.05, "Historical Bootstrap": 0.06},
        ]),
        "mc_sum": {"median_facility": 200000.0, "prob_facility_negative": 0.1,
                   "median_max_drawdown": -0.16},
        "conc": {"hhi": {"normalized": 0.04, "effective_n": 5.0}, "largest": ("VOO", 0.25),
                 "top3": 0.6},
        "rule_flags": flags,
    }


def test_headline_metrics_covers_engines_concentration_and_flags():
    res = _fake_run(700000.0, 0.8, [{"id": "RESV-01", "severity": "HIGH", "metric": "m",
                                     "rule": "r", "current_value": 0.1, "action": "a"}])
    metrics = headline_metrics(res)
    assert metrics["Median terminal value (2033) [Monte Carlo]"] == 700000.0
    assert metrics["Effective number of independent bets"] == 5.0
    assert metrics["Rule flags: HIGH"] == 1.0
    assert metrics["Rule flags: CRITICAL"] == 0.0


def test_compare_runs_reports_absolute_and_relative_change():
    a = _fake_run(700000.0, 0.80, [])
    b = _fake_run(650000.0, 0.65, [])
    df = compare_runs(a, b, "baseline", "variant")
    row = df[df["metric"] == "Median terminal value (2033) [Monte Carlo]"].iloc[0]
    assert row["change"] == pytest.approx(-50000.0)
    assert row["change_%"] == pytest.approx(-50000.0 / 700000.0)
    assert row["moves"] == "worse"

    funded = df[df["metric"] == "Probability reserve fully funded [Monte Carlo]"].iloc[0]
    assert funded["moves"] == "worse"

    # CVaR improves when it gets smaller
    c = _fake_run(700000.0, 0.8, [])
    c["comparison_sheet"].loc[
        c["comparison_sheet"]["metric"] == "CVaR 95% (terminal)", "Monte Carlo"] = 0.03
    df2 = compare_runs(a, c, "a", "b")
    tail = df2[df2["metric"] == "CVaR 95% (terminal) [Monte Carlo]"].iloc[0]
    assert tail["change"] == pytest.approx(-0.02)
    assert tail["moves"] == "better"


def test_flag_deltas_match_a_flag_that_was_renumbered_between_runs():
    """Flag ids are sequence numbers: the same rule can be RESV-05 in one run and RESV-04 in the next."""
    a = _fake_run(1.0, 1.0, [{"id": "RESV-05", "severity": "HIGH", "metric": "Prob funded",
                              "rule": "p < 0.9", "current_value": 0.18, "action": "buffer"}])
    b = _fake_run(1.0, 1.0, [{"id": "RESV-04", "severity": "HIGH", "metric": "Prob funded",
                              "rule": "p < 0.9", "current_value": 0.19, "action": "buffer"}])
    assert flag_deltas(a, b) == [], "a renumbered flag must not look like it appeared and vanished"

    b["rule_flags"].append({"id": "DD-04", "severity": "WARNING", "metric": "P(>20% dd)",
                            "rule": "p > 0.2", "current_value": 0.28, "action": "review"})
    deltas = flag_deltas(a, b)
    assert len(deltas) == 1 and deltas[0]["change"] == "only in run B" and deltas[0]["flag"] == "DD-04"


def test_money_and_probability_metrics_are_formatted_differently():
    assert _is_money("Median terminal value (2033) [Monte Carlo]")
    assert _is_money("Median facility value 2033 [Monte Carlo]")
    assert not _is_money("Probability the facility gets nothing [Monte Carlo]")
    assert not _is_money("Largest position weight")
    assert not _is_money("CVaR 95% (terminal) [Monte Carlo]")

    text = format_comparison(compare_runs(_fake_run(700000.0, 0.8, []),
                                          _fake_run(650000.0, 0.65, []), "baseline", "variant"),
                             [], "baseline", "variant")
    assert "$700,000" in text
    assert "$0.800" not in text, "a probability was formatted as money"


def test_cli_variant_comparison_writes_a_csv():
    import subprocess

    out = Path(tempfile.mkdtemp())
    proc = subprocess.run(
        [sys.executable, str(PKG_ROOT / "main.py"), "--offline", "--quiet",
         "--input", str(PKG_ROOT / "data" / "input" / "example_portfolio_minimal.xlsx"),
         "--out", str(out), "--sims", "300", "--variant",
         "glide_end_equity=0.40"],
        capture_output=True, text=True, timeout=600, cwd=str(PKG_ROOT))
    assert proc.returncode == 0, proc.stdout[-800:] + proc.stderr[-800:]
    assert "Baseline versus variant" in proc.stdout
    csv = out / "compare" / "run_comparison.csv"
    assert csv.exists(), "no comparison CSV was written"
    df = pd.read_csv(csv)
    assert {"metric", "baseline", "variant", "change", "moves"} <= set(df.columns)
    assert len(df) > 8


def test_cli_rejects_an_override_that_is_not_allowed():
    import subprocess

    proc = subprocess.run(
        [sys.executable, str(PKG_ROOT / "main.py"), "--offline", "--quiet", "--sims", "300",
         "--input", str(PKG_ROOT / "data" / "input" / "example_portfolio_minimal.xlsx"),
         "--out", str(Path(tempfile.mkdtemp())), "--variant", "nonsense_key=1"],
        capture_output=True, text=True, timeout=300, cwd=str(PKG_ROOT))
    assert proc.returncode == 2
    assert "cannot be overridden" in proc.stderr and "Allowed:" in proc.stderr

    proc = subprocess.run(
        [sys.executable, str(PKG_ROOT / "main.py"), "--offline", "--quiet", "--sims", "300",
         "--input", str(PKG_ROOT / "data" / "input" / "example_portfolio_minimal.xlsx"),
         "--out", str(Path(tempfile.mkdtemp())), "--variant", "just_a_word"],
        capture_output=True, text=True, timeout=300, cwd=str(PKG_ROOT))
    assert proc.returncode == 2 and "expected KEY=VALUE" in proc.stderr
