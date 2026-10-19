"""Offline regression checks for skill metadata."""

import runpy
from pathlib import Path

import pytest

VALIDATE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/check_skill_metadata.py"),
)["validate_metadata"]


@pytest.mark.parametrize(
    ("metadata", "failure"),
    [
        (
            "name: demo\ndescription: Example\nargument-hint: [command] [details]",
            "invalid YAML",
        ),
        ("name: [demo]\ndescription: Example", "name must be a nonempty string"),
        ("name: demo\ndescription: 123", "description must be a nonempty string"),
        ("name: demo", "description must be a nonempty string"),
        ("[]", "frontmatter must be a mapping"),
    ],
)
def test_invalid_metadata_identifies_path(tmp_path, metadata, failure):
    """Reject invalid YAML and required fields with a path-specific error."""
    path = tmp_path / "SKILL.md"
    path.write_text(f"---\n{metadata}\n---\n")
    with pytest.raises(ValueError, match=failure) as error:
        VALIDATE(path)
    assert str(path) in str(error.value)


def test_quoted_hint(tmp_path):
    """Accept the library hint when quoted as a scalar."""
    path = tmp_path / "SKILL.md"
    path.write_text(
        '---\nname: demo\ndescription: Example\nargument-hint: "[command] [details]"\n---\n'
    )
    VALIDATE(path)


@pytest.mark.parametrize("text", ["name: demo", "---\nname: demo"])
def test_missing_delimiters(tmp_path, text):
    """Require a complete frontmatter block."""
    path = tmp_path / "SKILL.md"
    path.write_text(text)
    with pytest.raises(ValueError, match="frontmatter delimiter"):
        VALIDATE(path)
