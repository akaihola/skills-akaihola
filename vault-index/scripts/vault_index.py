#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["vault-index"]
#
# [tool.uv.sources]
# vault-index = { path = "/home/agent/prg/vault-index", editable = true }
# ///
"""Thin launcher for the vault-index CLI."""

import sys
from pathlib import Path

# Remove this script's directory from sys.path so 'vault_index' resolves to
# the installed package, not this file (both share the name 'vault_index').
_this_dir = str(Path(__file__).resolve().parent)
sys.path = [p for p in sys.path if p != _this_dir]

from vault_index import cli  # noqa: E402

if __name__ == "__main__":
    cli()
