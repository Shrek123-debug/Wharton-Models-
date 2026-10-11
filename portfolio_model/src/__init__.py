"""Portfolio modeling agent package.

Importing this package configures the local runtime (matplotlib / yfinance cache
directories) *before* any module pulls in matplotlib, so a run never dies on an
unwritable ~/.matplotlib on locked-down machines or CI.
"""
from __future__ import annotations

from .runtime_env import configure_local_runtime as _configure_local_runtime

_configure_local_runtime()

__all__ = ["configure_local_runtime"]
