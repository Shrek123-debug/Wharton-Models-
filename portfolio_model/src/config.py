"""Central configuration loader."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = PACKAGE_ROOT.parent


def load_config(path: str | os.PathLike | None = None) -> dict:
    path = Path(path) if path else PACKAGE_ROOT / "config" / "model_config.yaml"
    with open(path, "r") as fh:
        return yaml.safe_load(fh)


def resolve(path: str | os.PathLike) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = (PACKAGE_ROOT / p).resolve()
    return p
