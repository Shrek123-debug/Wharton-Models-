"""Config validation: a bad config must fail with the key named, not a KeyError later."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest
import yaml

PKG_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG_ROOT))

from src.config import ConfigError, load_config, validate_config  # noqa: E402

CONFIG = PKG_ROOT / "config" / "model_config.yaml"


def _broken(mutate) -> Path:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    mutate(cfg)
    path = Path(tempfile.mkdtemp()) / "model_config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def test_the_shipped_config_is_valid():
    assert validate_config(load_config()) == []


@pytest.mark.parametrize("name,mutate,expected", [
    ("missing key", lambda c: c["risk"].pop("correlation_threshold"), "risk.correlation_threshold is missing"),
    ("missing whole section", lambda c: c.pop("stress_tests"), "stress_tests.crises is missing"),
    ("string where a number belongs", lambda c: c["simulation"].__setitem__("n_simulations", "two thousand"),
     "simulation.n_simulations must be whole number"),
    ("unknown enum value", lambda c: c["simulation"].__setitem__("model", "gauss"),
     "simulation.model must be one of gaussian, lognormal, student_t, historical_residual"),
    ("out of range", lambda c: c["risk"].__setitem__("max_position_weight", 4),
     "risk.max_position_weight must be at most 1"),
    ("boolean where a number belongs", lambda c: c["risk"].__setitem__("inflation_base", True),
     "risk.inflation_base must be number"),
    ("years inverted", lambda c: c["simulation"].__setitem__("glide_end_year", 1999),
     "glide_end_year (1999) is before simulation.start_year"),
    ("markov thresholds mismatched", lambda c: c["markov"].__setitem__("thresholds", [-0.1]),
     "markov.thresholds must hold 4 values"),
    ("contribution without amount", lambda c: c["cashflows"]["contributions"].append({"year": 2030}),
     "needs at least 'year' and 'amount'"),
    ("crisis without end", lambda c: c["stress_tests"]["crises"].append({"name": "X", "start": "2020-01-01"}),
     "stress_tests.crises[3] needs 'name', 'start' and 'end'"),
])
def test_broken_configs_are_named_not_obscured(name, mutate, expected):
    with pytest.raises(ConfigError) as exc:
        load_config(_broken(mutate))
    assert expected in str(exc.value), str(exc.value)


def test_invalid_yaml_is_reported_as_yaml():
    path = Path(tempfile.mkdtemp()) / "model_config.yaml"
    path.write_text("risk:\n  - [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "not valid YAML" in str(exc.value)


def test_missing_config_file_says_where_to_point_the_cli():
    with pytest.raises(ConfigError) as exc:
        load_config(Path(tempfile.mkdtemp()) / "nope.yaml")
    assert "not found" in str(exc.value) and "--config" in str(exc.value)


def test_the_cli_exits_with_a_config_error_instead_of_a_traceback():
    import subprocess

    broken = _broken(lambda c: c["risk"].pop("correlation_threshold"))
    proc = subprocess.run(
        [sys.executable, str(PKG_ROOT / "main.py"), "--config", str(broken),
         "--input", str(PKG_ROOT / "data" / "input" / "example_portfolio_minimal.xlsx"),
         "--offline", "--sims", "300"],
        capture_output=True, text=True, timeout=300, cwd=str(PKG_ROOT))
    assert proc.returncode == 2, proc.stdout[-500:] + proc.stderr[-500:]
    assert "CONFIG PROBLEM" in proc.stderr
    assert "risk.correlation_threshold is missing" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_selfcheck_reports_the_offending_key():
    from src.selfcheck import collect_checks

    checks = collect_checks(config_path=str(_broken(lambda c: c["risk"].pop("max_sector_weight"))))
    config_checks = [c for c in checks if c["area"] == "config"]
    assert config_checks and config_checks[0]["status"] == "fail"
    assert "risk.max_sector_weight is missing" in config_checks[0]["message"]
    assert config_checks[0]["fix"]
