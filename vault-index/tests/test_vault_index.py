"""Tests for the vault-index Phase 2a core functionality.

Uses a small fixture vault under tests/fixtures/.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest
from vault_index import (  # type: ignore[import-not-found]
    VaultIndexer,
    extract_frontmatter_relationships,
    extract_wiki_links,
    parse_file,
)

FIXTURES = Path(__file__).parent / "fixtures"
EXPECTED_FILE_COUNT = 4  # Alpha, Beta, Gamma, Orphan


# ── helpers ────────────────────────────────────────────────────────────────────


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """Copy fixtures into a fresh tmp_path vault and return the root."""
    shutil.copytree(FIXTURES, tmp_path, dirs_exist_ok=True)
    return tmp_path


@pytest.fixture
def built_vault(vault: Path) -> Path:
    """Vault with an index already built."""
    VaultIndexer(vault).build_index()
    return vault


# ── extract_wiki_links ─────────────────────────────────────────────────────────


def test_extract_wiki_links_basic() -> None:
    """Simple [[Link]] extraction."""
    links = extract_wiki_links("See [[Alpha]] and [[Beta]].")
    assert "Alpha" in links
    assert "Beta" in links


def test_extract_wiki_links_with_alias() -> None:
    """[[Target|Alias]] yields only the target."""
    links = extract_wiki_links("See [[Alpha Project|the alpha]].")
    assert "Alpha Project" in links


def test_extract_wiki_links_skips_code_blocks() -> None:
    """Links inside fenced code blocks must not be extracted."""
    content = "```\n[[NotALink]]\n```\nReal [[Link]]."
    links = extract_wiki_links(content)
    assert "NotALink" not in links
    assert "Link" in links


def test_extract_wiki_links_skips_inline_code() -> None:
    """Links inside backtick spans must not be extracted."""
    links = extract_wiki_links("Use `[[NotALink]]` then [[RealLink]].")
    assert "NotALink" not in links
    assert "RealLink" in links


def test_extract_wiki_links_strips_heading_anchor() -> None:
    """[[Note#Section]] should yield 'Note'."""
    links = extract_wiki_links("See [[Alpha#Introduction]].")
    assert links == ["Alpha"]


# ── extract_frontmatter_relationships ─────────────────────────────────────────


def test_frontmatter_relationships_list() -> None:
    """List-valued frontmatter relationships are returned correctly."""
    path = FIXTURES / "pages" / "Projects" / "Alpha.md"
    rels = extract_frontmatter_relationships(path)
    rel_dict: dict[str, list[str]] = {}
    for rel_type, target in rels:
        rel_dict.setdefault(rel_type, []).append(target)
    assert "Beta Project" in rel_dict.get("depends_on", [])
    assert "Gamma Note" in rel_dict.get("related", [])


def test_frontmatter_relationships_single() -> None:
    """Single-value frontmatter relationship is handled."""
    path = FIXTURES / "pages" / "Projects" / "Beta.md"
    rels = extract_frontmatter_relationships(path)
    targets = [t for rel_type, t in rels if rel_type == "blocks"]
    assert "Alpha Project" in targets


# ── parse_file ─────────────────────────────────────────────────────────────────


def test_parse_file_project_type() -> None:
    """Files under pages/Projects/ get file_type='project'."""
    path = FIXTURES / "pages" / "Projects" / "Alpha.md"
    info = parse_file(FIXTURES, path)
    assert info.file_type == "project"
    assert info.title == "Alpha Project"
    assert info.status == "Active"
    assert info.priority == "P1"
    assert "python" in info.tags


def test_parse_file_note_type() -> None:
    """Files outside Projects/ get file_type='note'."""
    path = FIXTURES / "pages" / "Gamma Note.md"
    info = parse_file(FIXTURES, path)
    assert info.file_type == "note"
    assert info.title == "Gamma Note"


def test_parse_file_missing_frontmatter(tmp_path: Path) -> None:
    """Files without frontmatter fall back to first heading as title."""
    tmp = tmp_path / "NoFront.md"
    tmp.write_text("# My Title\n\nSome content.", encoding="utf-8")
    info = parse_file(tmp_path, tmp)
    assert info.title == "My Title"


# ── VaultIndexer.scan_vault ────────────────────────────────────────────────────


def test_scan_vault_finds_all_markdown(vault: Path) -> None:
    """scan_vault returns one FileInfo per .md file in the fixture."""
    indexer = VaultIndexer(vault)
    files = indexer.scan_vault()
    titles = {f.title for f in files}
    assert "Alpha Project" in titles
    assert "Beta Project" in titles
    assert "Gamma Note" in titles
    assert "Orphan Note" in titles


# ── VaultIndexer.build_index ──────────────────────────────────────────────────


def test_build_index_creates_db(vault: Path) -> None:
    """build_index creates the .vault-index.db file."""
    indexer = VaultIndexer(vault)
    assert not indexer.db_path.exists()
    indexer.build_index()
    assert indexer.db_path.exists()


def test_build_index_populates_files(built_vault: Path) -> None:
    """After build, files table contains one row per markdown file."""
    conn = sqlite3.connect(built_vault / ".vault-index.db")
    count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    conn.close()
    assert count == EXPECTED_FILE_COUNT


def test_build_index_records_frontmatter_edges(built_vault: Path) -> None:
    """Frontmatter depends_on / related / blocks edges are stored."""
    conn = sqlite3.connect(built_vault / ".vault-index.db")
    rows = conn.execute(
        "SELECT rel_type, edge_type FROM edges WHERE edge_type = 'frontmatter'"
    ).fetchall()
    conn.close()
    rel_types = {r[0] for r in rows}
    assert "depends_on" in rel_types
    assert "blocks" in rel_types
    assert "related" in rel_types


def test_build_index_records_wiki_link_edges(built_vault: Path) -> None:
    """Wiki-links in the body are stored as links_to edges."""
    conn = sqlite3.connect(built_vault / ".vault-index.db")
    rows = conn.execute(
        "SELECT rel_type FROM edges WHERE edge_type = 'wiki-link'"
    ).fetchall()
    conn.close()
    assert len(rows) > 0
    assert all(r[0] == "links_to" for r in rows)


def test_build_index_is_idempotent(vault: Path) -> None:
    """Running build twice gives the same file count."""
    indexer = VaultIndexer(vault)
    indexer.build_index()
    conn = sqlite3.connect(indexer.db_path)
    count1 = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    conn.close()
    indexer.build_index()
    conn = sqlite3.connect(indexer.db_path)
    count2 = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    conn.close()
    assert count1 == count2


def test_build_index_tags(built_vault: Path) -> None:
    """Tags from frontmatter are indexed."""
    conn = sqlite3.connect(built_vault / ".vault-index.db")
    tags = {r[0] for r in conn.execute("SELECT tag FROM tags").fetchall()}
    conn.close()
    assert "python" in tags
    assert "MCP" in tags
    assert "research" in tags


# ── VaultIndexer.traverse ─────────────────────────────────────────────────────


def test_traverse_finds_connected_file(
    built_vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Traversing from Alpha shows Beta in output."""
    VaultIndexer(built_vault).traverse("Alpha Project", max_depth=1)
    out = capsys.readouterr().out
    assert "Alpha Project" in out
    assert "Beta Project" in out


def test_traverse_unknown_file(
    built_vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Traversing an unknown file name prints 'not found'."""
    VaultIndexer(built_vault).traverse("NonExistentFile")
    out = capsys.readouterr().out
    assert "not found" in out.lower()


# ── VaultIndexer.find_gaps ────────────────────────────────────────────────────


def test_find_gaps_reports_zero_links(
    built_vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """find_gaps link distribution shows at least one file with 0 links."""
    VaultIndexer(built_vault).find_gaps()
    out = capsys.readouterr().out
    assert "0 links" in out


def test_find_gaps_broken_links_zero(
    built_vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fixture vault has no broken links."""
    VaultIndexer(built_vault).find_gaps()
    out = capsys.readouterr().out
    assert "Broken links: 0" in out
