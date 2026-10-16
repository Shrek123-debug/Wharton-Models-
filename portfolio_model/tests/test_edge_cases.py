"""Edge-case and degenerate-input tests.

These cases are how the pipeline actually breaks in practice: one holding, all cash, a
ticker Yahoo does not know, a negative weight, a foreign ticker, weights that do not sum to
one, a holding whose history starts after every configured crisis. Each must either produce
a complete, sane run or a clear, actionable error - never a crash and never a silent NaN.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest
from openpyxl import Workbook

PKG_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG_ROOT))

from src.pipeline import PipelineError, run  # noqa: E402

OPTIONS = {"sims": 400, "sensitivity_sims": 200, "offline": "always", "seed": 5}


def _workbook(rows, headers=("Ticker", "Weight", "Asset Class"), name="case"):
    wb = Workbook()
    ws = wb.active
    ws.title = "Holdings"
    ws.append(list(headers))
    for r in rows:
        ws.append(list(r))
    path = Path(tempfile.mkdtemp()) / f"{name}.xlsx"
    wb.save(path)
    return path


def _run(rows, name):
    return run(input_path=str(_workbook(rows, name=name)),
               out_dir=str(Path(tempfile.mkdtemp()) / "out"),
               overrides=dict(OPTIONS), render_charts=True)


CASES = {
    "single_holding": [["VOO", 1.0, "ETF"]],
    "weights_not_summing": [["VOO", 0.3, "ETF"], ["IEF", 0.2, "Treasury"]],
    "no_asset_class_column": [["VOO", 0.6], ["IEF", 0.4]],
    "unknown_ticker_dropped": [["ZZZZQQ", 0.5, "US Equity"], ["VOO", 0.5, "ETF"]],
    "negative_weight_dropped": [["VOO", 1.2, "ETF"], ["IEF", -0.2, "Treasury"]],
    "foreign_ticker_dropped": [["TOYOF", 0.5, "International Equity"], ["VOO", 0.5, "ETF"]],
    "equity_plus_cash": [["VOO", 0.9, "ETF"], ["CASH", 0.1, "Cash"]],
    "history_shorter_than_every_crisis": [["DUOL", 1.0, "US Equity"]],
    "many_holdings": [[t, 0.9 / 6, "ETF" if i == 0 else "US Equity"]
                      for i, t in enumerate(["VOO", "ADBE", "DIS", "XOM", "JNJ", "KO"])]
                     + [["CASH", 0.1, "Cash"]],
}


@pytest.mark.parametrize("name,rows", sorted(CASES.items()))
def test_degenerate_inputs_produce_a_complete_run(name, rows):
    res = _run(rows, name)
    assert len(res["holdings"]) >= 1
    assert res["mc_sum"]["median_terminal"] > 0
    assert res["figures"], "figures should still render for degenerate portfolios"
    for key in ("stress_sheet", "risk_sheet", "comparison_sheet", "holdings_sheet"):
        num = res[key].select_dtypes("number")
        assert int(num.isna().sum().sum()) == 0, f"{key} has NaN cells for case {name}"
    assert abs(res["holdings"]["weight"].sum() - 1.0) < 1e-9


def test_all_cash_portfolio_fails_with_an_actionable_message():
    with pytest.raises(PipelineError) as exc:
        _run([["CASH", 1.0, "Cash"]], "all_cash")
    msg = str(exc.value).lower()
    assert "cash" in msg and "simulate" in msg


def test_crisis_windows_outside_the_price_history_are_reported_not_faked():
    # DUOL starts 2021-07: the 2008 and 2020 windows do not overlap it, 2022 does
    res = _run([["DUOL", 1.0, "US Equity"]], "young_only")
    dq = res["dq_sheet"]
    skipped = dq[dq["issue"] == "Crisis window skipped"]
    assert len(skipped) == 2, f"expected 2 skipped crisis windows, got {len(skipped)}"
    assert "2008" in " ".join(skipped["detail"].tolist())
    stress = res["stress_sheet"]
    assert len(stress) == 1 and "2022" in str(stress["crisis"].tolist())
    num = stress.select_dtypes("number")
    assert int(num.isna().sum().sum()) == 0, "skipped windows must not leave NaN rows behind"


def test_dropped_ticker_leaves_a_high_data_quality_flag():
    res = _run([["ZZZZQQ", 0.5, "US Equity"], ["VOO", 0.5, "ETF"]], "dropped")
    high = res["dq_sheet"][res["dq_sheet"]["severity"] == "high"]
    assert "Ticker unavailable" in " ".join(high["issue"].tolist())
    assert "ZZZZQQ" in " ".join(high["ticker"].astype(str).tolist())


def test_positional_indexing_survives_row_dropping():
    """Regression: holdings.loc[[0, 1]] on a frame whose index survived a row drop."""
    res = _run([["TOYOF", 0.5, "International Equity"], ["VOO", 0.4, "ETF"],
                ["IEF", 0.1, "Treasury"], ["CASH", 0.0, "Cash"]], "index_regression")
    tickers = list(res["holdings"]["ticker"])
    assert "TOYOF" not in tickers
    assert "VOO" in tickers
    assert res["ctx"].equity_idx == [tickers.index("VOO")]


def test_empty_crisis_chart_and_payload_still_render():
    from src.reporting import charts
    from web.serialize import build_payload

    res = _run([["DUOL", 1.0, "US Equity"]], "empty_crisis")
    # the empty case is exercised directly on the renderers
    assert charts.crisis_comparison([], Path(tempfile.mkdtemp())).exists()
    payload = build_payload(res)
    assert payload["charts"]["crisis"]["data"] is not None
    assert len(payload["tables"]["stress"]) == 1
