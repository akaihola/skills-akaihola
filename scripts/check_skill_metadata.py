# /// script
# dependencies = ["pyyaml>=6.0"]
# ///
"""Validate tracked skill frontmatter: uv run scripts/check_skill_metadata.py."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml


def validate_metadata(path: Path) -> None:
    """Raise ValueError with the skill path when metadata is invalid."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise ValueError(f"{path}: missing opening frontmatter delimiter")
    try:
        end = lines.index("---", 1)
    except ValueError as error:
        raise ValueError(f"{path}: missing closing frontmatter delimiter") from error
    try:
        metadata = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as error:
        raise ValueError(f"{path}: invalid YAML: {error}") from error
    if not isinstance(metadata, dict):
        raise ValueError(f"{path}: frontmatter must be a mapping")
    for field in ("name", "description"):
        if not isinstance(metadata.get(field), str) or not metadata[field].strip():
            raise ValueError(f"{path}: {field} must be a nonempty string")


def main() -> int:
    """Check all Git-tracked SKILL.md files, reporting every failure."""
    root = Path(__file__).resolve().parents[1]
    tracked = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "--", "SKILL.md", "*/SKILL.md"],
            cwd=root,
        )
        .decode()
        .split("\0")
    )
    paths = [root / name for name in tracked if name]
    failures = []
    for path in paths:
        try:
            validate_metadata(path)
        except ValueError as error:
            failures.append(str(error))
    if failures:
        print("\n".join(failures))
        return 1
    print(f"Validated {len(paths)} skill frontmatters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
