"""Pytest configuration: add scripts to path so vault_index can be imported."""

from __future__ import annotations

import sys
from pathlib import Path

# Make vault_index importable in tests without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
