"""The analyzer modules, imported in this order so their analyzers register.

Each module registers its analyzers with ``@model.analyzer``. Run order comes
from the declared dependencies, not from this list.
"""

from __future__ import annotations

import importlib

from .model import REGISTRY, Registration

MODULES = (
    "windows",
    "battery_history",
    "battery_summary",
    "kernel_suspend",
    "radio",
    "qcom",
    "memory",
    "perf",
    "cpu",
    "logs",
    "apps",
    "budget",
)


def load_analyzers() -> tuple[dict[str, Registration], dict[str, str]]:
    """Import every analyzer module.

    Returns the registry and ``{module: error}`` for modules that failed to
    import, so one broken module does not stop the others.
    """
    errors: dict[str, str] = {}
    for module in MODULES:
        try:
            importlib.import_module(f"androiddiag.{module}")
        except Exception as exc:  # ruff: ignore[blind-except] - report and keep going
            errors[module] = f"{type(exc).__name__}: {exc}"
    return REGISTRY, errors
