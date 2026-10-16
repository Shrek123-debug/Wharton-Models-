"""Tests for the offline-first data layer, runtime setup, override validation and self-test.

These exist because the historical failure mode of this project was not a bad model — it
was "the run needs the internet, and the internet is not available / is rate limited".
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PKG_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG_ROOT))

from src.config import load_config  # noqa: E402
from src.market_data import fetch as fetch_mod  # noqa: E402
from src.market_data.fetch import align_price_frames, fetch_history  # noqa: E402
from src.pipeline import PipelineError, _apply_overrides  # noqa: E402


def _synthetic(start: str = "2000-01-01", n: int = 6000, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start=start, periods=n)
    price = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.012, n)))
    df = pd.DataFrame({"Close": price, "Open": price, "High": price, "Low": price,
                       "Volume": 1_000_000}, index=idx)
    df.index.name = "Date"
    return df


@pytest.fixture()
def bundled(tmp_path):
    d = tmp_path / "offline"
    d.mkdir()
    _synthetic().to_parquet(d / "ACME.parquet")
    _synthetic(seed=1).to_parquet(d / "SPY.parquet")
    return d


# ---------------------------------------------------------------- cache keys
def test_cache_key_does_not_embed_today(tmp_path):
    """The old key used the current date, so every new day forced a re-download."""
    p1 = fetch_mod._cache_path(tmp_path, "SPY", "2000-01-01", "live")
    assert p1.name == "SPY__2000-01-01__live.parquet"
    assert str(pd.Timestamp.now().date()) not in p1.name


def test_cache_hit_avoids_network(tmp_path, bundled, monkeypatch):
    calls = []
    monkeypatch.setattr(fetch_mod, "_network_fetch", lambda *a, **k: calls.append(a) or pd.DataFrame())
    cache = tmp_path / "cache"

    first = fetch_history(["ACME"], "2000-01-01", None, cache, bundled_dir=bundled)
    assert first.provenance["ACME"]["status"] == "ok"
    assert len(list(cache.glob("ACME__*"))) == 1, "a resolved ticker must land in the project cache"

    calls.clear()
    second = fetch_history(["ACME"], "2000-01-01", None, cache, bundled_dir=bundled)
    assert second.provenance["ACME"]["source"] == "cache"
    assert not calls, "a fresh cache hit must not touch the network"


def test_stale_cache_is_reused_with_a_visible_note(tmp_path, bundled, monkeypatch):
    monkeypatch.setattr(fetch_mod, "_network_fetch", lambda *a, **k: pd.DataFrame())
    cache = tmp_path / "cache"
    fetch_history(["ACME"], "2000-01-01", None, cache, bundled_dir=bundled)
    res = fetch_history(["ACME"], "2000-01-01", None, cache, bundled_dir=bundled, max_age_days=0)
    assert res.provenance["ACME"]["status"] == "ok"
    assert res.provenance["ACME"]["rows"] > 0


# ---------------------------------------------------------------- network failure
def test_network_failure_falls_back_to_bundled_snapshot(tmp_path, bundled, monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("network unavailable")
    monkeypatch.setattr(fetch_mod, "_network_fetch", boom)
    res = fetch_history(["ACME", "SPY"], "2000-01-01", None, tmp_path / "cache", bundled_dir=bundled)
    assert res.missing() == []
    assert {p["source"] for p in res.provenance.values()} == {"bundled snapshot"}


def test_offline_always_never_calls_the_network(tmp_path, bundled, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("offline mode must not touch the network")
    monkeypatch.setattr(fetch_mod, "_network_fetch", boom)
    res = fetch_history(["ACME"], "2000-01-01", None, tmp_path / "cache",
                        bundled_dir=bundled, offline="always")
    assert res.provenance["ACME"]["status"] == "ok"
    assert "offline" in res.provenance["ACME"]["note"]


def test_missing_ticker_reports_an_actionable_note(tmp_path, bundled, monkeypatch):
    monkeypatch.setattr(fetch_mod, "_network_fetch", lambda *a, **k: pd.DataFrame())
    res = fetch_history(["NOSUCHTICKER"], "2000-01-01", None, tmp_path / "cache", bundled_dir=bundled)
    assert res.missing() == ["NOSUCHTICKER"]
    note = res.provenance["NOSUCHTICKER"]["note"]
    assert "build_offline_dataset.py" in note and "NOSUCHTICKER" in note


def test_wider_cached_window_serves_a_narrower_request(tmp_path, bundled, monkeypatch):
    monkeypatch.setattr(fetch_mod, "_network_fetch", lambda *a, **k: pd.DataFrame())
    cache = tmp_path / "cache"
    fetch_history(["ACME"], "2000-01-01", None, cache, bundled_dir=bundled)
    res = fetch_history(["ACME"], "2015-01-01", "2020-01-01", cache, bundled_dir=bundled, offline="always")
    frame = res.frames["ACME"]
    assert frame.index.min() >= pd.Timestamp("2015-01-01")
    assert frame.index.max() <= pd.Timestamp("2020-01-01")
    assert res.provenance["ACME"]["source"] == "cache"


def test_corrupt_bundled_snapshot_does_not_crash_the_run(tmp_path, monkeypatch):
    d = tmp_path / "offline"
    d.mkdir()
    (d / "BAD.parquet").write_bytes(b"not a parquet file")
    monkeypatch.setattr(fetch_mod, "_network_fetch", lambda *a, **k: pd.DataFrame())
    res = fetch_history(["BAD"], "2000-01-01", None, tmp_path / "cache", bundled_dir=d)
    assert res.provenance["BAD"]["status"] == "unavailable"


def test_provenance_is_written_to_disk(tmp_path, bundled):
    cache = tmp_path / "cache"
    fetch_history(["ACME"], "2000-01-01", None, cache, bundled_dir=bundled, offline="always")
    meta = pd.read_csv(cache / "_fetch_meta.csv", index_col=0)
    assert "source" in meta.columns and "data_as_of" in meta.columns
    assert meta.loc["ACME", "rows"] > 0


def test_align_price_frames_never_zero_fills():
    frames = {"A": _synthetic(n=50), "B": _synthetic(n=50, seed=3), "EMPTY": pd.DataFrame()}
    prices = align_price_frames(frames)
    assert list(prices.columns) == ["A", "B"]
    assert not (prices == 0).any().any()
    assert prices.index.is_monotonic_increasing


def test_offline_mode_resolution(tmp_path, monkeypatch):
    monkeypatch.delenv(fetch_mod.OFFLINE_ENV, raising=False)
    assert fetch_mod._offline_mode(None) == "auto"
    assert fetch_mod._offline_mode("always") == "always"
    assert fetch_mod._offline_mode("1") == "always"
    assert fetch_mod._offline_mode("never") == "never"
    monkeypatch.setenv(fetch_mod.OFFLINE_ENV, "true")
    assert fetch_mod._offline_mode(None) == "always"


# ---------------------------------------------------------------- overrides
def test_overrides_are_validated_and_clamped():
    cfg = load_config()
    _apply_overrides(cfg, {"sims": 5000, "seed": 7, "model": "student_t"})
    assert cfg["simulation"]["n_simulations"] == 5000
    assert cfg["bootstrap"]["n_simulations"] == 5000
    assert cfg["simulation"]["random_seed"] == 7
    assert cfg["simulation"]["model"] == "student_t"

    for bad in ({"sims": 0}, {"sims": 10_000_000}, {"band": 5}, {"model": "poisson"},
                {"start_date": "not-a-date"}, {"nonsense_key": 1}):
        with pytest.raises(PipelineError):
            _apply_overrides(load_config(), bad)


def test_override_error_message_names_the_key(tmp_path):
    with pytest.raises(PipelineError) as exc:
        _apply_overrides(load_config(), {"sims": "abc"})
    assert "sims" in str(exc.value)


# ---------------------------------------------------------------- runtime env
def test_runtime_env_sets_writable_cache_dirs(monkeypatch, tmp_path):
    from src import runtime_env

    monkeypatch.delenv("MPLCONFIGDIR", raising=False)
    monkeypatch.setattr(runtime_env, "CACHE_ROOT", tmp_path / ".cache")
    set_vars = runtime_env.configure_local_runtime()
    assert set_vars["MPLCONFIGDIR"].startswith(str(tmp_path))
    assert Path(set_vars["MPLCONFIGDIR"]).is_dir()


def test_selfcheck_runs_against_the_example_portfolio(capsys):
    from src.selfcheck import run_selfcheck

    example = PKG_ROOT / "data" / "input" / "example_portfolio_full.xlsx"
    ok = run_selfcheck(input_path=str(example))
    out = capsys.readouterr().out
    assert "Self-test" in out
    assert ok, out
