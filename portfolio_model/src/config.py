"""Central configuration loader and validator.

The config drives every number in the report, so a typo in it must fail loudly and say which
key is wrong. Without validation a missing key surfaces hundreds of lines later as a bare
`KeyError: 'correlation_threshold'` - true but useless - and a mistyped value such as
`n_simulations: "two thousand"` can flow straight through into a simulation.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = PACKAGE_ROOT.parent


class ConfigError(RuntimeError):
    """The configuration is missing keys or has values the model cannot use."""


# ---------------------------------------------------------------------------
# Schema: dotted path -> expectation.
#
# `types` is the accepted Python type set, `choices` the allowed string values,
# `ge`/`le` the numeric range, `nullable` whether an explicit null is meaningful,
# and `note` the human hint shown when the value is wrong.
# ---------------------------------------------------------------------------

_SCHEMA: dict[str, dict] = {
    "input.spreadsheet": {"types": (str,)},
    "input.sheet": {"types": (str, type(None))},
    "input.base_currency": {"types": (str,)},

    "historical_data.start_date": {"types": (str,)},
    "historical_data.end_date": {"types": (str, type(None))},
    "historical_data.frequency": {"types": (str,), "choices": ("daily", "monthly")},
    "historical_data.cache_dir": {"types": (str,)},
    "historical_data.offline": {"types": (str,), "choices": ("auto", "always", "never")},
    "historical_data.bundled_dir": {"types": (str,)},
    "historical_data.max_cache_age_days": {"types": (int, float), "ge": 0},
    "historical_data.allow_stale_cache": {"types": (bool,)},
    "historical_data.benchmarks.equity": {"types": (str,)},
    "historical_data.benchmarks.bonds": {"types": (str,)},

    "simulation.n_simulations": {"types": (int,), "ge": 100, "le": 200000,
                                 "note": "whole number, at least 100"},
    "simulation.random_seed": {"types": (int,)},
    "simulation.start_year": {"types": (int,)},
    "simulation.glide_end_year": {"types": (int,), "note": "must be >= simulation.start_year"},
    "simulation.reserve_end_year": {"types": (int,)},
    "simulation.step": {"types": (str,), "choices": ("monthly", "quarterly")},
    "simulation.model": {"types": (str,),
                         "choices": ("gaussian", "lognormal", "student_t", "historical_residual")},
    "simulation.student_t_dof": {"types": (int,), "ge": 3},

    "cashflows.contributions": {"types": (list,), "note": "list of {year, amount, timing}"},
    "cashflows.withdrawals": {"types": (list,)},
    "cashflows.reserve_payments.amount": {"types": (int, float), "ge": 0},
    "cashflows.reserve_payments.first_year": {"types": (int,)},
    "cashflows.reserve_payments.last_year": {"types": (int,)},
    "cashflows.reserve_payments.timing": {"types": (str,), "choices": ("start", "end")},
    "cashflows.reserve_discount_rate": {"types": (int, float), "ge": -1, "le": 1},

    "expected_returns.source": {"types": (str,), "choices": ("input", "historical", "blend")},
    "expected_returns.window_years": {"types": (int, type(None)), "ge": 1},
    "expected_returns.shrinkage": {"types": (int, float), "ge": 0, "le": 1},

    "risk.var_confidence": {"types": (list,), "note": "list of confidences between 0.5 and 0.999"},
    "risk.correlation_threshold": {"types": (int, float), "ge": 0, "le": 1},
    "risk.max_position_weight": {"types": (int, float), "ge": 0, "le": 1},
    "risk.max_sector_weight": {"types": (int, float), "ge": 0, "le": 1},
    "risk.max_correlated_group_weight": {"types": (int, float), "ge": 0, "le": 1},
    "risk.min_cash_weight": {"types": (int, float), "ge": 0, "le": 1},
    "risk.risk_free_rate": {"types": (int, float), "ge": -1, "le": 1},
    "risk.inflation_base": {"types": (int, float), "ge": -1, "le": 1},
    "risk.inflation_scenarios": {"types": (list,)},

    "rebalancing.enabled": {"types": (bool,)},
    "rebalancing.method": {"types": (str,), "choices": ("absolute", "relative")},
    "rebalancing.band": {"types": (int, float), "ge": 0, "le": 1},
    "rebalancing.relative_band": {"types": (int, float), "ge": 0, "le": 1},
    "rebalancing.frequency": {"types": (str,), "choices": ("annual", "semi-annual", "quarterly", "monthly")},
    "rebalancing.transaction_cost": {"types": (int, float), "ge": 0, "le": 1},

    "glide_path.enabled": {"types": (bool,)},
    "glide_path.target_year": {"types": (int,)},
    "glide_path.method": {"types": (str,), "choices": ("linear", "stepped", "custom")},
    "glide_path.start_equity": {"types": (int, float, type(None)), "ge": 0, "le": 1},
    "glide_path.end_equity": {"types": (int, float), "ge": 0, "le": 1},

    "bootstrap.method": {"types": (str,), "choices": ("block", "iid")},
    "bootstrap.block_size_days": {"types": (int,), "ge": 1},
    "bootstrap.n_simulations": {"types": (int,), "ge": 100, "le": 200000},

    "markov.states": {"types": (list,), "note": "five state names, ordered worst to best"},
    "markov.thresholds": {"types": (list,), "note": "len(states) - 1 numeric thresholds"},
    "markov.n_simulations": {"types": (int,), "ge": 100, "le": 200000},

    "sensitivity.return_shifts": {"types": (list,)},
    "sensitivity.vol_multipliers": {"types": (list,)},
    "sensitivity.n_simulations": {"types": (int,), "ge": 100, "le": 200000},

    "stress_tests.crises": {"types": (list,), "note": "list of {name, start, end}"},
    "stress_tests.hypothetical": {"types": (dict,)},
}


def _get(cfg: dict, dotted: str):
    node = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False, None
        node = node[part]
    return True, node


def _type_name(t) -> str:
    return {str: "text", int: "whole number", float: "number", bool: "true/false",
            list: "list", dict: "mapping", type(None): "blank"}.get(t, t.__name__)


def _numeric_hint(spec: dict) -> str:
    types = spec["types"]
    if int in types and float in types:
        return "number"
    return _type_name(types[0])


def _hint(spec: dict) -> str:
    return spec.get("note") or f"expected {_numeric_hint(spec)}"


def validate_config(cfg: dict) -> list[str]:
    """Return every problem with the configuration. Empty list means it is usable."""
    problems: list[str] = []

    if not isinstance(cfg, dict):
        return ["config file did not parse to a mapping - is it valid YAML?"]

    for path, spec in _SCHEMA.items():
        found, value = _get(cfg, path)
        if not found:
            problems.append(f"{path} is missing ({_hint(spec)}). Restore it from config/model_config.yaml.")
            continue
        types = spec["types"]
        # bool is a subclass of int in Python: a config that says `true` for a number is wrong
        if isinstance(value, bool) and int in types and bool not in types:
            problems.append(f"{path} must be {_numeric_hint(spec)}, got {value!r}.")
            continue
        if not isinstance(value, types):
            expected = " or ".join(_type_name(t) for t in types)
            problems.append(f"{path} must be {expected}, got {value!r} ({type(value).__name__}).")
            continue
        choices = spec.get("choices")
        if choices and value not in choices:
            problems.append(f"{path} must be one of {', '.join(choices)}, got {value!r}.")
        ge, le = spec.get("ge"), spec.get("le")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if ge is not None and value < ge:
                problems.append(f"{path} must be at least {ge}, got {value}.")
            if le is not None and value > le:
                problems.append(f"{path} must be at most {le}, got {value}.")

    # cross-field checks that a per-key schema cannot express
    ok, start_year = _get(cfg, "simulation.start_year")
    ok2, glide_end = _get(cfg, "simulation.glide_end_year")
    if ok and ok2 and isinstance(start_year, int) and isinstance(glide_end, int) and glide_end < start_year:
        problems.append(f"simulation.glide_end_year ({glide_end}) is before simulation.start_year "
                        f"({start_year}); the plan would end before it begins.")

    ok, states = _get(cfg, "markov.states")
    ok2, thresholds = _get(cfg, "markov.thresholds")
    if ok and ok2 and isinstance(states, list) and isinstance(thresholds, list) \
            and len(thresholds) != len(states) - 1:
        problems.append(f"markov.thresholds must hold {len(states) - 1} values for "
                        f"{len(states)} states, got {len(thresholds)}.")

    ok, contribs = _get(cfg, "cashflows.contributions")
    if ok and isinstance(contribs, list):
        for i, c in enumerate(contribs):
            if not isinstance(c, dict) or "year" not in c or "amount" not in c:
                problems.append(f"cashflows.contributions[{i}] needs at least 'year' and 'amount', got {c!r}.")

    ok, crises = _get(cfg, "stress_tests.crises")
    if ok and isinstance(crises, list):
        for i, c in enumerate(crises):
            if not isinstance(c, dict) or not all(k in c for k in ("name", "start", "end")):
                problems.append(f"stress_tests.crises[{i}] needs 'name', 'start' and 'end', got {c!r}.")

    return problems


def load_config(path: str | os.PathLike | None = None, *, validate: bool = True) -> dict:
    path = Path(path) if path else PACKAGE_ROOT / "config" / "model_config.yaml"
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}\n"
                          f"Restore it, or point --config at an existing YAML file.")
    try:
        with open(path) as fh:
            cfg = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Config file {path} is not valid YAML: {exc}") from exc

    if validate:
        problems = validate_config(cfg)
        if problems:
            raise ConfigError(
                f"Configuration problem in {path}:\n  - " + "\n  - ".join(problems)
                + "\n\nFix the key(s) above, or restore the shipped config/model_config.yaml.")
    return cfg


def resolve(path: str | os.PathLike) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = (PACKAGE_ROOT / p).resolve()
    return p
