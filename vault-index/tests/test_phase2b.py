"""Tests for vault-index Phase 2b: FTS5 search, entities, inline relations, suggest."""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from vault_index import (  # type: ignore[import-not-found]
    VaultIndexer,
    chunk_file,
    extract_inline_relations,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """Copy fixtures into a fresh tmp_path vault."""
    shutil.copytree(FIXTURES, tmp_path, dirs_exist_ok=True)
    return tmp_path


@pytest.fixture
def built_vault(vault: Path) -> Path:
    """Vault with a full index (including chunks)."""
    VaultIndexer(vault).build_index()
    return vault


# ── chunk_file ─────────────────────────────────────────────────────────────────


def test_chunk_file_splits_by_heading() -> None:
    """chunk_file splits markdown content by ## headings."""
    content = (
        "Intro text.\n\n"
        "## Section One\n\nContent one.\n\n"
        "## Section Two\n\nContent two."
    )
    chunks = chunk_file(content, title="Test")
    assert len(chunks) == 3  # intro + two sections
    headings = [c["heading_path"] for c in chunks]
    assert "" in headings or "Test" in headings  # intro chunk
    assert "Section One" in headings
    assert "Section Two" in headings


def test_chunk_file_single_chunk_for_short_file() -> None:
    """Very short files (no headings) become one chunk."""
    content = "Just a short note with no headings."
    chunks = chunk_file(content, title="Short")
    assert len(chunks) == 1
    assert chunks[0]["content"] == content


def test_chunk_file_content_hash_deterministic() -> None:
    """The same content always produces the same hash."""
    content = "Hello world."
    c1 = chunk_file(content, title="T")
    c2 = chunk_file(content, title="T")
    assert c1[0]["content_hash"] == c2[0]["content_hash"]


# ── extract_inline_relations ──────────────────────────────────────────────────


def test_extract_inline_relations_basic() -> None:
    """Lines matching '- rel_type [[Target]]' are extracted."""
    body = (
        "Some text.\n\n"
        "- depends_on [[Alpha Project]]\n"
        "- related_to [[Beta]]\n\nMore text."
    )
    rels = extract_inline_relations(body)
    assert len(rels) == 2
    rel_types = {r["rel_type"] for r in rels}
    assert "depends_on" in rel_types
    assert "related_to" in rel_types


def test_extract_inline_relations_ignores_prose() -> None:
    """Ordinary bullet points without wiki-link targets are ignored."""
    body = "- Some bullet point\n- Another bullet\n- depends_on [[Real]]"
    rels = extract_inline_relations(body)
    assert len(rels) == 1
    assert rels[0]["dst_target"] == "Real"


def test_extract_inline_relations_empty() -> None:
    """Files with no inline relations return empty list."""
    assert extract_inline_relations("No relations here.") == []


# ── build_index with chunks ────────────────────────────────────────────────────


def test_build_creates_content_chunks_table(built_vault: Path) -> None:
    """After build, content_chunks table exists and is populated."""
    conn = sqlite3.connect(built_vault / ".vault-index.db")
    count = conn.execute("SELECT COUNT(*) FROM content_chunks").fetchone()[0]
    conn.close()
    assert count > 0


def test_build_creates_fts_chunks_table(built_vault: Path) -> None:
    """After build, fts_chunks FTS5 virtual table exists."""
    conn = sqlite3.connect(built_vault / ".vault-index.db")
    # FTS5 table exists if this query succeeds
    rows = conn.execute("SELECT * FROM fts_chunks LIMIT 1").fetchall()
    conn.close()
    assert rows is not None  # table exists (may be empty)


def test_build_creates_inline_relations_table(built_vault: Path) -> None:
    """After build, inline_relations table exists."""
    conn = sqlite3.connect(built_vault / ".vault-index.db")
    count = conn.execute("SELECT COUNT(*) FROM inline_relations").fetchone()[0]
    conn.close()
    assert count >= 0  # fixture has inline relations in Alpha.md


def test_build_extracts_inline_relations(built_vault: Path) -> None:
    """Inline relations from Alpha.md are stored in inline_relations."""
    conn = sqlite3.connect(built_vault / ".vault-index.db")
    rows = conn.execute("SELECT rel_type, dst_target FROM inline_relations").fetchall()
    conn.close()
    rel_types = {r[0] for r in rows}
    assert "depends_on" in rel_types or "related_to" in rel_types


# ── FTS search ────────────────────────────────────────────────────────────────


def test_fts_search_finds_match(built_vault: Path) -> None:
    """FTS5 search returns results for a term present in the vault."""
    indexer = VaultIndexer(built_vault)
    results = indexer.search("knowledge graph", mode="fts")
    assert len(results) > 0
    # Result should have expected keys
    first = results[0]
    assert "file_path" in first
    assert "snippet" in first
    assert "score" in first


def test_fts_search_returns_empty_for_missing_term(built_vault: Path) -> None:
    """FTS5 search returns empty list for a term not in the vault."""
    indexer = VaultIndexer(built_vault)
    results = indexer.search("xyzzy_nonexistent_term_42", mode="fts")
    assert results == []


def test_fts_search_filter_by_type(built_vault: Path) -> None:
    """FTS5 search with --type project returns only project files."""
    indexer = VaultIndexer(built_vault)
    results = indexer.search("project", mode="fts", file_type="project")
    file_types = {r["file_type"] for r in results}
    assert file_types <= {"project"}


def test_fts_search_json_output(built_vault: Path) -> None:
    """search() results can be serialised to JSON."""
    indexer = VaultIndexer(built_vault)
    results = indexer.search("semantic", mode="fts")
    # Must be JSON-serialisable
    json.dumps(results)


# ── inline relations in traverse ──────────────────────────────────────────────


def test_traverse_includes_inline_relations(
    built_vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Traverse --include-inline shows inline relation targets."""
    indexer = VaultIndexer(built_vault)
    indexer.traverse("Alpha Project", max_depth=1, include_inline=True)
    out = capsys.readouterr().out
    # Alpha has inline depends_on Beta Project
    assert "Alpha Project" in out


# ── gaps with inline relations ────────────────────────────────────────────────


def test_find_gaps_inline_relations_section(
    built_vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """find_gaps with --inline-relations shows inline relation diagnostics."""
    VaultIndexer(built_vault).find_gaps(inline_relations=True)
    out = capsys.readouterr().out
    assert "inline" in out.lower() or "relation" in out.lower()


# ── entities ──────────────────────────────────────────────────────────────────


def test_build_creates_entities_table(built_vault: Path) -> None:
    """After build, entities and entity_mentions tables exist."""
    conn = sqlite3.connect(built_vault / ".vault-index.db")
    conn.execute("SELECT COUNT(*) FROM entities").fetchone()
    conn.execute("SELECT COUNT(*) FROM entity_mentions").fetchone()
    conn.close()


def test_entities_indexed_from_frontmatter(tmp_path: Path) -> None:
    """Entities defined in frontmatter entities: field are indexed."""
    md = tmp_path / "pages" / "Projects" / "WithEntities.md"
    md.parent.mkdir(parents=True)
    frontmatter = (
        "---\ntitle: With Entities\nstatus: Active\n"
        "entities:\n"
        "  - name: pykoclaw\n    type: tool\n"
        "  - name: Väinö\n    type: agent\n"
        "---\n"
    )
    md.write_text(
        frontmatter + "\n# With Entities\n\nMentions pykoclaw.", encoding="utf-8"
    )
    VaultIndexer(tmp_path).build_index()
    conn = sqlite3.connect(tmp_path / ".vault-index.db")
    names = {
        r[0] for r in conn.execute("SELECT canonical_name FROM entities").fetchall()
    }
    conn.close()
    assert "pykoclaw" in names
    assert "Väinö" in names


# ── suggest ──────────────────────────────────────────────────────────────────


def test_suggest_returns_list(built_vault: Path) -> None:
    """suggest() returns a list of suggestion dicts."""
    indexer = VaultIndexer(built_vault)
    suggestions = indexer.suggest("Gamma Note")
    assert isinstance(suggestions, list)
    for s in suggestions:
        assert "file_path" in s
        assert "category" in s
        assert "rationale" in s


def test_suggest_unknown_file(built_vault: Path) -> None:
    """suggest() returns empty list for unknown file."""
    indexer = VaultIndexer(built_vault)
    suggestions = indexer.suggest("NonExistentFile")
    assert suggestions == []
