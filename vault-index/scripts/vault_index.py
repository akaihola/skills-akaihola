#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["click", "pyyaml", "httpx"]
# ///
"""Vault Knowledge Graph Indexer.

Index an Obsidian-style markdown vault into a SQLite database for graph
queries, link analysis, and gap detection.

Usage::

    vault-index build [--vault PATH]           # Rebuild the index
    vault-index traverse TITLE [--depth N]     # Graph traversal
    vault-index gaps                           # Orphans, broken links, stats
    vault-index search QUERY [--mode fts]      # Full-text / semantic search
    vault-index entities [--type ETYPE]        # Browse indexed entities
    vault-index suggest FILE                   # Suggest related notes

Environment:
    VAULT_ROOT             Path to the vault root (used when --vault is omitted)
    OPENAI_API_KEY         For embedding-based semantic search (optional)
    OPENAI_BASE_URL        Override OpenAI-compatible endpoint (optional)
    VAULT_EMBEDDING_MODEL  Embedding model ID (default: text-embedding-3-small)
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click
import yaml

if TYPE_CHECKING:
    from collections.abc import Callable

# ── constants ──────────────────────────────────────────────────────────────────

YAML_SPLIT_MIN_PARTS = 3
LINK_PREFIX_MIN_LEN = 10
DEFAULT_SEARCH_LIMIT = 10
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
CHUNK_MAX_CHARS = 2000  # hard cap for max-size fallback chunking

# Relationship types (from vault CLAUDE.md Graph Hygiene section)
KNOWN_RELATIONSHIPS = frozenset(
    {
        "depends_on",
        "blocks",
        "related",
        "builds_on",
        "similar_to",
        "contradicts",
    }
)

# Inline relation pattern: bullet starting with a known or custom rel_type
# followed by [[Target]]
_INLINE_REL_PATTERN = re.compile(
    r"^\s*-\s+(\w+)\s+\[\[((?:(?!\]\]).)+?)\]\]",
    re.MULTILINE,
)


# ── helpers ────────────────────────────────────────────────────────────────────


def _default_vault() -> Path:
    """Return vault root from VAULT_ROOT env-var or the current directory."""
    env = os.environ.get("VAULT_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return Path.cwd()


_VAULT_OPT = click.option(
    "--vault",
    "-v",
    default=None,
    help="Vault root directory (overrides VAULT_ROOT env var).",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)


def _resolve_vault(vault: Path | None) -> Path:
    """Resolve the vault root from CLI option or environment."""
    return vault.expanduser().resolve() if vault else _default_vault()


def _content_hash(text: str) -> str:
    """Return a short SHA-256 hex digest of *text*."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# ── data model ─────────────────────────────────────────────────────────────────


@dataclass
class FileInfo:
    """Metadata parsed from a single vault file."""

    path: Path
    title: str
    file_type: str  # project | note | journal
    status: str | None = None
    priority: str | None = None
    created: str | None = None
    last_updated: str | None = None
    tags: list[str] = field(default_factory=list)
    entities: list[dict[str, str]] = field(default_factory=list)


# ── parsing helpers ────────────────────────────────────────────────────────────


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Return (metadata_dict, body_text) from a markdown string."""
    metadata: dict = {}
    body = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= YAML_SPLIT_MIN_PARTS:
            with contextlib.suppress(yaml.YAMLError):
                metadata = yaml.safe_load(parts[1].strip()) or {}
            body = parts[2].strip()
    return metadata, body


def extract_wiki_links(content: str) -> list[str]:
    """Extract wiki-link targets from *content*, skipping code spans/blocks."""
    stripped = re.sub(r"(`{3,}).*?\1", "", content, flags=re.DOTALL)
    stripped = re.sub(r"`[^`]+`", "", stripped)
    pattern = r"\[\[((?:(?!\]\]).)+?)(?:\|(?:(?!\]\]).)+?)?\]\]"
    links = re.findall(pattern, stripped)
    return [link.split("#")[0] for link in links if link.split("#")[0]]


def extract_frontmatter_relationships(path: Path) -> list[tuple[str, str]]:
    """Return [(rel_type, target), …] from frontmatter relationship fields."""
    relationships: list[tuple[str, str]] = []
    with contextlib.suppress(Exception):
        content = path.read_text(encoding="utf-8")
        metadata, _ = _parse_frontmatter(content)
        for rel_type in KNOWN_RELATIONSHIPS:
            value = metadata.get(rel_type)
            if not value:
                continue
            items = value if isinstance(value, list) else [value]
            for item in items:
                target = str(item).strip('[]" ')
                relationships.append((rel_type, target))
    return relationships


def extract_inline_relations(body: str) -> list[dict[str, str]]:
    """Return typed inline relation dicts from body text.

    Matches bullet lines of the form: ``- rel_type [[Target]]``
    where rel_type is any word (not just the known relationship vocabulary,
    so callers can filter as needed).
    """
    results: list[dict[str, str]] = []
    for m in _INLINE_REL_PATTERN.finditer(body):
        rel_type = m.group(1)
        dst_target = m.group(2).split("#")[0].strip()
        if dst_target:
            results.append(
                {
                    "rel_type": rel_type,
                    "dst_target": dst_target,
                    "raw_text": m.group(0).strip(),
                }
            )
    return results


def chunk_file(content: str, title: str = "") -> list[dict[str, Any]]:
    """Split *content* into chunks by heading.

    Strategy:
    - Split on ``##`` and ``###`` headings.
    - Pre-heading text (if any) becomes chunk 0 with heading_path = title.
    - Very short files with no headings → single chunk.

    Returns a list of dicts with keys:
        chunk_index, heading_path, content, content_hash
    """
    # Split on level-2 or level-3 headings
    heading_re = re.compile(r"^(#{2,3})\s+(.+)$", re.MULTILINE)
    parts: list[tuple[str, str]] = []  # (heading_path, content)

    last_end = 0
    current_heading = title
    for m in heading_re.finditer(content):
        segment = content[last_end : m.start()].strip()
        if last_end == 0 and segment:
            parts.append((current_heading, segment))
        elif last_end > 0:
            parts.append((current_heading, segment))
        current_heading = m.group(2).strip()
        last_end = m.end()

    # Remaining content after last heading (or whole file if no headings)
    tail = content[last_end:].strip()
    if tail or not parts:
        parts.append((current_heading, tail or content.strip()))

    # Build result dicts
    chunks: list[dict[str, Any]] = []
    for idx, (heading, text) in enumerate(parts):
        if not text:
            continue
        # Apply max-size fallback chunking
        while text:
            chunk_text = text[:CHUNK_MAX_CHARS]
            text = text[CHUNK_MAX_CHARS:]
            chunks.append(
                {
                    "chunk_index": len(chunks),
                    "heading_path": heading,
                    "content": chunk_text,
                    "content_hash": _content_hash(chunk_text),
                }
            )
    if not chunks:
        chunks.append(
            {
                "chunk_index": 0,
                "heading_path": title,
                "content": "",
                "content_hash": _content_hash(""),
            }
        )
    return chunks


def parse_file(vault_root: Path, path: Path) -> FileInfo:
    """Parse a markdown file and return a :class:`FileInfo`."""
    with contextlib.suppress(Exception):
        content = path.read_text(encoding="utf-8")
        metadata, body = _parse_frontmatter(content)

        rel = path.relative_to(vault_root)
        if "Projects" in rel.parts:
            file_type = "project"
        elif "journals" in rel.parts:
            file_type = "journal"
        else:
            file_type = "note"

        title: str = metadata.get("title", "") or path.stem
        if title == path.stem:
            m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
            if m:
                title = m.group(1)

        # Parse entities from frontmatter
        raw_entities = metadata.get("entities") or []
        entities: list[dict[str, str]] = []
        for ent in raw_entities:
            if isinstance(ent, dict) and "name" in ent:
                entities.append(
                    {
                        "name": str(ent["name"]),
                        "type": str(ent.get("type", "unknown")),
                    }
                )

        return FileInfo(
            path=path,
            title=title,
            file_type=file_type,
            status=metadata.get("status"),
            priority=metadata.get("priority"),
            created=str(metadata["created"]) if metadata.get("created") else None,
            last_updated=(
                str(metadata["last_updated"]) if metadata.get("last_updated") else None
            ),
            tags=metadata.get("tags") or [],
            entities=entities,
        )
    return FileInfo(path=path, title=path.stem, file_type="note")


# ── database ───────────────────────────────────────────────────────────────────


def init_db(db_path: Path) -> sqlite3.Connection:
    """Create (or open) the SQLite index and ensure the schema exists."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    conn.executescript("""
        -- Core tables (Phase 2a)
        CREATE TABLE IF NOT EXISTS files (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            path         TEXT UNIQUE NOT NULL,
            title        TEXT NOT NULL,
            file_type    TEXT NOT NULL,
            status       TEXT,
            priority     TEXT,
            created      TEXT,
            last_updated TEXT,
            raw_content  TEXT
        );
        CREATE TABLE IF NOT EXISTS tags (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL,
            tag     TEXT NOT NULL,
            FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS edges (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            src_file_id INTEGER NOT NULL,
            dst_file_id INTEGER,
            rel_type    TEXT NOT NULL,
            edge_type   TEXT NOT NULL,
            dst_target  TEXT,
            UNIQUE(src_file_id, dst_file_id, rel_type, edge_type),
            FOREIGN KEY (src_file_id) REFERENCES files(id) ON DELETE CASCADE
        );

        -- Phase 2b tables
        CREATE TABLE IF NOT EXISTS content_chunks (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id      INTEGER NOT NULL,
            chunk_index  INTEGER NOT NULL,
            heading_path TEXT NOT NULL DEFAULT '',
            content      TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_chunks USING fts5(
            content,
            title,
            tags,
            content=content_chunks,
            content_rowid=id
        );
        CREATE TABLE IF NOT EXISTS entities (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_name TEXT UNIQUE NOT NULL,
            entity_type    TEXT NOT NULL DEFAULT 'unknown',
            source         TEXT NOT NULL DEFAULT 'frontmatter'
        );
        CREATE TABLE IF NOT EXISTS entity_mentions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id    INTEGER NOT NULL,
            file_id      INTEGER NOT NULL,
            chunk_id     INTEGER,
            surface_form TEXT NOT NULL,
            mention_count INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE,
            FOREIGN KEY (file_id)   REFERENCES files(id)    ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS inline_relations (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            src_file_id       INTEGER NOT NULL,
            src_chunk_id      INTEGER,
            rel_type          TEXT NOT NULL,
            dst_target        TEXT NOT NULL,
            dst_file_id       INTEGER,
            raw_text          TEXT NOT NULL DEFAULT '',
            resolution_status TEXT NOT NULL DEFAULT 'unresolved',
            FOREIGN KEY (src_file_id) REFERENCES files(id) ON DELETE CASCADE
        );

        -- Indexes
        CREATE INDEX IF NOT EXISTS idx_files_path       ON files(path);
        CREATE INDEX IF NOT EXISTS idx_files_title      ON files(title);
        CREATE INDEX IF NOT EXISTS idx_files_type       ON files(file_type);
        CREATE INDEX IF NOT EXISTS idx_edges_src        ON edges(src_file_id);
        CREATE INDEX IF NOT EXISTS idx_edges_dst        ON edges(dst_file_id);
        CREATE INDEX IF NOT EXISTS idx_edges_rel        ON edges(rel_type);
        CREATE INDEX IF NOT EXISTS idx_tags_file        ON tags(file_id);
        CREATE INDEX IF NOT EXISTS idx_tags_tag         ON tags(tag);
        CREATE INDEX IF NOT EXISTS idx_chunks_file      ON content_chunks(file_id);
        CREATE INDEX IF NOT EXISTS idx_irel_src         ON inline_relations(src_file_id);
        CREATE INDEX IF NOT EXISTS idx_irel_dst         ON inline_relations(dst_file_id);
        CREATE INDEX IF NOT EXISTS idx_mentions_entity  ON entity_mentions(entity_id);
        CREATE INDEX IF NOT EXISTS idx_mentions_file    ON entity_mentions(file_id);
    """)
    conn.commit()
    return conn


# ── indexer ────────────────────────────────────────────────────────────────────


class VaultIndexer:
    """Build and query a SQLite graph index for a markdown vault."""

    def __init__(self, vault_root: Path) -> None:
        """Initialise the indexer pointing at *vault_root*."""
        self.vault_root = vault_root
        self.db_path = vault_root / ".vault-index.db"

    # ── scanning ──────────────────────────────────────────────────────────────

    def scan_vault(self) -> list[FileInfo]:
        """Recursively find and parse all markdown files in the vault."""
        files: list[FileInfo] = []
        for pattern in ("pages/**/*.md", "journals/**/*.md", "*.md"):
            for path in self.vault_root.glob(pattern):
                if path.is_file() and not path.name.startswith("."):
                    if path.suffix not in {".md", ""}:
                        continue
                    files.append(parse_file(self.vault_root, path))
        return files

    # ── link resolution ───────────────────────────────────────────────────────

    @staticmethod
    def _build_lookup(files: list[FileInfo], vault_root: Path) -> dict[str, Path]:
        """Return a mapping of every known name/path variant to a file path."""
        lookup: dict[str, Path] = {}
        for f in files:
            lookup[f.path.stem] = f.path
            lookup[f.title] = f.path
            rel = f.path.relative_to(vault_root)
            no_ext = str(rel.with_suffix(""))
            lookup[no_ext] = f.path
            if no_ext.startswith("pages/"):
                lookup[no_ext[6:]] = f.path
        return lookup

    def _make_resolver(self, files: list[FileInfo]) -> Callable[[str], Path | None]:
        """Return a closure that resolves a wiki-link text to a file path."""
        lookup = self._build_lookup(files, self.vault_root)
        stems = {f.path.stem: f.path for f in files}

        def resolve(link_text: str) -> Path | None:
            if dst := lookup.get(link_text):
                return dst
            if "/" in link_text and (dst := lookup.get(link_text.rsplit("/", 1)[-1])):
                return dst
            if len(link_text) > LINK_PREFIX_MIN_LEN:
                for stem, path in stems.items():
                    if stem.startswith(link_text):
                        return path
            return None

        return resolve

    # ── build ─────────────────────────────────────────────────────────────────

    def build_index(self) -> None:
        """Rebuild the full index from scratch."""
        print(f"Building index for vault at {self.vault_root}…")
        conn = init_db(self.db_path)

        # Clear all derived data
        conn.execute("DELETE FROM inline_relations")
        conn.execute("DELETE FROM entity_mentions")
        conn.execute("DELETE FROM entities")
        conn.execute("DELETE FROM fts_chunks")
        conn.execute("DELETE FROM content_chunks")
        conn.execute("DELETE FROM edges")
        conn.execute("DELETE FROM tags")
        conn.execute("DELETE FROM files")

        files = self.scan_vault()
        print(f"Found {len(files)} files")

        resolve = self._make_resolver(files)

        # --- Insert files, tags, and collect IDs ---
        file_ids: dict[Path, int] = {}
        for f in files:
            cur = conn.execute(
                """INSERT INTO files
                       (path, title, file_type, status, priority,
                        created, last_updated)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(f.path),
                    f.title,
                    f.file_type,
                    f.status,
                    f.priority,
                    f.created,
                    f.last_updated,
                ),
            )
            row_id = cur.lastrowid
            assert row_id is not None
            file_ids[f.path] = row_id
            for tag in f.tags:
                conn.execute(
                    "INSERT INTO tags (file_id, tag) VALUES (?, ?)",
                    (row_id, tag),
                )
            # Entities from frontmatter
            for ent in f.entities:
                name = ent["name"]
                etype = ent.get("type", "unknown")
                conn.execute(
                    """INSERT OR IGNORE INTO entities (canonical_name, entity_type, source)
                       VALUES (?, ?, 'frontmatter')""",
                    (name, etype),
                )
                entity_row = conn.execute(
                    "SELECT id FROM entities WHERE canonical_name = ?", (name,)
                ).fetchone()
                if entity_row:
                    conn.execute(
                        """INSERT INTO entity_mentions
                               (entity_id, file_id, surface_form, mention_count)
                           VALUES (?, ?, ?, 1)""",
                        (entity_row[0], row_id, name),
                    )

        # --- Build edges, chunks, and inline relations ---
        for f in files:
            src_id = file_ids[f.path]
            body = ""
            with contextlib.suppress(Exception):
                raw = f.path.read_text(encoding="utf-8")
                _, body = _parse_frontmatter(raw)

            # Frontmatter relationships → edges
            for rel_type, target in extract_frontmatter_relationships(f.path):
                dst = resolve(target)
                if dst and dst in file_ids:
                    conn.execute(
                        """INSERT OR IGNORE INTO edges
                               (src_file_id, dst_file_id, rel_type, edge_type)
                           VALUES (?, ?, ?, 'frontmatter')""",
                        (src_id, file_ids[dst], rel_type),
                    )
                else:
                    conn.execute(
                        """INSERT INTO edges
                               (src_file_id, dst_target, rel_type, edge_type)
                           VALUES (?, ?, ?, 'frontmatter')""",
                        (src_id, target, rel_type),
                    )

            # Wiki-links → edges
            for link in extract_wiki_links(body):
                dst = resolve(link)
                if dst and dst in file_ids:
                    conn.execute(
                        """INSERT OR IGNORE INTO edges
                               (src_file_id, dst_file_id, rel_type, edge_type)
                           VALUES (?, ?, 'links_to', 'wiki-link')""",
                        (src_id, file_ids[dst]),
                    )
                else:
                    conn.execute(
                        """INSERT INTO edges
                               (src_file_id, dst_target, rel_type, edge_type)
                           VALUES (?, ?, 'links_to', 'wiki-link')""",
                        (src_id, link),
                    )

            # Chunks + FTS
            tag_str = " ".join(f.tags)
            chunks = chunk_file(body, title=f.title)
            for ch in chunks:
                ch_cur = conn.execute(
                    """INSERT INTO content_chunks
                           (file_id, chunk_index, heading_path, content, content_hash)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        src_id,
                        ch["chunk_index"],
                        ch["heading_path"],
                        ch["content"],
                        ch["content_hash"],
                    ),
                )
                chunk_id = ch_cur.lastrowid
                assert chunk_id is not None
                conn.execute(
                    "INSERT INTO fts_chunks(rowid, content, title, tags) VALUES (?,?,?,?)",
                    (chunk_id, ch["content"], f.title, tag_str),
                )

            # Inline relations
            for ir in extract_inline_relations(body):
                dst = resolve(ir["dst_target"])
                dst_id = file_ids[dst] if dst and dst in file_ids else None
                status = "resolved" if dst_id is not None else "unresolved"
                conn.execute(
                    """INSERT INTO inline_relations
                           (src_file_id, rel_type, dst_target, dst_file_id,
                            raw_text, resolution_status)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        src_id,
                        ir["rel_type"],
                        ir["dst_target"],
                        dst_id,
                        ir["raw_text"],
                        status,
                    ),
                )

        conn.commit()
        edge_count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        chunk_count = conn.execute("SELECT COUNT(*) FROM content_chunks").fetchone()[0]
        tag_count = conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        print(
            f"Index built: {edge_count} edges, {chunk_count} chunks, {tag_count} tags"
        )
        print(f"Database: {self.db_path}")
        conn.close()

    # ── query helpers ─────────────────────────────────────────────────────────

    def _require_conn(self) -> sqlite3.Connection:
        """Open the database.

        Raises:
            RuntimeError: if the index has not been built yet.

        """
        if not self.db_path.exists():
            msg = "Index not built. Run 'vault-index build' first."
            raise RuntimeError(msg)
        return sqlite3.connect(self.db_path)

    # ── search ────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        mode: str = "fts",
        file_type: str | None = None,
        tag: str | None = None,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> list[dict[str, Any]]:
        """Search the vault and return ranked results.

        Returns:
            List of result dicts with keys: file_path, file_title, file_type,
            chunk_heading, snippet, score, match_reasons.
        """
        conn = self._require_conn()
        results = self._fts_search(conn, query, file_type, tag, limit)
        conn.close()
        return results

    def _fts_search(
        self,
        conn: sqlite3.Connection,
        query: str,
        file_type: str | None,
        tag: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Run an FTS5 query and return structured results."""
        # Escape FTS5 special chars in simple mode
        safe_query = re.sub(r'["\*\(\)\{\}\[\]^~?\\]', " ", query).strip()
        if not safe_query:
            return []

        params: list[Any] = [safe_query, limit * 3]  # extra for type/tag filtering
        sql = """
            SELECT
                f.path,
                f.title,
                f.file_type,
                cc.heading_path,
                snippet(fts_chunks, 0, '<b>', '</b>', '…', 16) AS snippet,
                bm25(fts_chunks) AS score
            FROM fts_chunks
            JOIN content_chunks cc ON fts_chunks.rowid = cc.id
            JOIN files f ON cc.file_id = f.id
            WHERE fts_chunks MATCH ?
            ORDER BY score
            LIMIT ?
        """
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return []

        results: list[dict[str, Any]] = []
        for path, title, ftype, heading, snippet, score in rows:
            if file_type and ftype != file_type:
                continue
            if tag:
                has_tag = conn.execute(
                    "SELECT 1 FROM tags t JOIN files f ON t.file_id = f.id "
                    "WHERE f.path = ? AND t.tag = ?",
                    (path, tag),
                ).fetchone()
                if not has_tag:
                    continue
            results.append(
                {
                    "file_path": path,
                    "file_title": title,
                    "file_type": ftype,
                    "chunk_heading": heading or "",
                    "snippet": snippet or "",
                    "score": float(score),
                    "match_reasons": ["fts5"],
                }
            )
            if len(results) >= limit:
                break
        return results

    # ── entities ──────────────────────────────────────────────────────────────

    def list_entities(self, entity_type: str | None = None) -> list[dict[str, Any]]:
        """Return all indexed entities, optionally filtered by type."""
        conn = self._require_conn()
        if entity_type:
            rows = conn.execute(
                "SELECT canonical_name, entity_type, source FROM entities "
                "WHERE entity_type = ? ORDER BY canonical_name",
                (entity_type,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT canonical_name, entity_type, source FROM entities "
                "ORDER BY canonical_name"
            ).fetchall()
        conn.close()
        return [{"name": r[0], "type": r[1], "source": r[2]} for r in rows]

    # ── traverse ──────────────────────────────────────────────────────────────

    def traverse(
        self,
        start_file: str,
        max_depth: int = 2,
        include_inline: bool = False,
    ) -> None:
        """Print a tree of files reachable from *start_file*."""
        conn = self._require_conn()
        row = conn.execute(
            "SELECT id, title FROM files WHERE title = ? OR path LIKE ?",
            (start_file, f"%{start_file}%"),
        ).fetchone()
        if not row:
            print(f"File not found: {start_file}")
            conn.close()
            return

        file_id, title = row
        print(f"Traversing from: {title}")
        print("=" * 50)

        visited: set[int] = set()
        queue: list[tuple[int, int]] = [(file_id, 0)]
        while queue:
            current_id, depth = queue.pop(0)
            if current_id in visited or depth > max_depth:
                continue
            visited.add(current_id)

            file_row = conn.execute(
                "SELECT title, file_type FROM files WHERE id = ?", (current_id,)
            ).fetchone()
            indent = "  " * depth
            ftype = f" [{file_row[1]}]" if file_row[1] else ""
            print(f"{indent}├── {file_row[0]}{ftype}")

            edges = conn.execute(
                """SELECT e.rel_type, e.edge_type, f.title, e.dst_target
                   FROM edges e
                   LEFT JOIN files f ON e.dst_file_id = f.id
                   WHERE e.src_file_id = ?
                   ORDER BY e.edge_type DESC""",
                (current_id,),
            ).fetchall()
            for rel_type, edge_type, dst_title, dst_target in edges:
                if dst_title:
                    dst_row = conn.execute(
                        "SELECT id FROM files WHERE title = ?", (dst_title,)
                    ).fetchone()
                    if dst_row and dst_row[0] not in visited:
                        label = (
                            f"{edge_type}:{rel_type}"
                            if edge_type != "wiki-link"
                            else rel_type
                        )
                        print(f"{indent}│   └── {label} → [[{dst_title}]]")
                        queue.append((dst_row[0], depth + 1))
                elif dst_target:
                    label = f"{edge_type}:{rel_type}"
                    print(f"{indent}│   └── {label} → [[{dst_target}]] (BROKEN)")

            # Inline relations (if requested)
            if include_inline:
                irels = conn.execute(
                    """SELECT ir.rel_type, f2.title, ir.dst_target
                       FROM inline_relations ir
                       LEFT JOIN files f2 ON ir.dst_file_id = f2.id
                       WHERE ir.src_file_id = ?""",
                    (current_id,),
                ).fetchall()
                for rel_type, dst_title, dst_target in irels:
                    label = f"inline:{rel_type}"
                    if dst_title:
                        print(f"{indent}│   └── {label} → [[{dst_title}]] (inline)")
                    else:
                        print(
                            f"{indent}│   └── {label} → [[{dst_target}]] (inline/unresolved)"
                        )
        conn.close()

    # ── find_gaps ─────────────────────────────────────────────────────────────

    def find_gaps(self, inline_relations: bool = False) -> None:
        """Report orphan files, broken links, and connectivity statistics."""
        conn = self._require_conn()

        print("VAULT ANALYSIS")
        print("=" * 50)

        orphan_count = conn.execute("""
            SELECT COUNT(*) FROM files f
            WHERE f.file_type = 'project'
              AND f.status NOT IN ('Completed', 'Abandoned')
              AND f.id NOT IN (SELECT src_file_id FROM edges)
              AND f.id NOT IN (
                  SELECT dst_file_id FROM edges WHERE dst_file_id IS NOT NULL
              )
        """).fetchone()[0]
        print(f"\n📍 Orphan projects (Active/Planning, no connections): {orphan_count}")
        orphans = conn.execute("""
            SELECT f.title, f.status FROM files f
            WHERE f.file_type = 'project'
              AND f.status IN ('Active', 'Planning')
              AND f.id NOT IN (SELECT src_file_id FROM edges)
              AND f.id NOT IN (
                  SELECT dst_file_id FROM edges WHERE dst_file_id IS NOT NULL
              )
            ORDER BY f.title
        """).fetchall()
        for t, s in orphans:
            print(f"   • {t} [{s}]")

        broken_count = conn.execute("""
            SELECT COUNT(*) FROM edges
            WHERE dst_file_id IS NULL AND dst_target IS NOT NULL
        """).fetchone()[0]
        print(f"\n🔗 Broken links: {broken_count}")
        broken = conn.execute("""
            SELECT f.title, e.dst_target, e.rel_type, e.edge_type
            FROM edges e
            JOIN files f ON e.src_file_id = f.id
            WHERE e.dst_file_id IS NULL AND e.dst_target IS NOT NULL
            ORDER BY f.title
        """).fetchall()
        for src, dst, rel, etype in broken:
            print(f"   • {src} --{etype}:{rel}--> [[{dst}]]")

        # Inline relation diagnostics
        if inline_relations:
            unresolved = conn.execute("""
                SELECT COUNT(*) FROM inline_relations
                WHERE resolution_status = 'unresolved'
            """).fetchone()[0]
            print(f"\n🔗 Unresolved inline relations: {unresolved}")
            ur_rows = conn.execute("""
                SELECT f.title, ir.rel_type, ir.dst_target
                FROM inline_relations ir
                JOIN files f ON ir.src_file_id = f.id
                WHERE ir.resolution_status = 'unresolved'
                ORDER BY f.title
            """).fetchall()
            for title, rel, dst in ur_rows:
                print(f"   • {title} -inline:{rel}-> [[{dst}]]")

        print("\n📊 Link distribution:")
        stats = conn.execute("""
            SELECT
                CASE
                    WHEN link_count = 0 THEN '0 links'
                    WHEN link_count = 1 THEN '1 link'
                    WHEN link_count = 2 THEN '2 links'
                    WHEN link_count <= 5 THEN '3-5 links'
                    ELSE '6+ links'
                END AS bucket,
                COUNT(*) AS count
            FROM (
                SELECT f.id, COUNT(e.id) AS link_count
                FROM files f
                LEFT JOIN edges e ON f.id = e.src_file_id
                GROUP BY f.id
            )
            GROUP BY bucket
            ORDER BY
                CASE bucket
                    WHEN '0 links' THEN 1
                    WHEN '1 link'  THEN 2
                    WHEN '2 links' THEN 3
                    WHEN '3-5 links' THEN 4
                    ELSE 5
                END
        """).fetchall()
        for bucket, count in stats:
            bar = "█" * min(count, 50)
            print(f"   {bucket:10} {bar} ({count})")

        print("\n🌟 Most connected files:")
        top = conn.execute("""
            SELECT f.title, COUNT(e.id) AS edge_count, f.file_type
            FROM files f
            JOIN edges e ON f.id = e.src_file_id OR f.id = e.dst_file_id
            GROUP BY f.id
            ORDER BY edge_count DESC
            LIMIT 10
        """).fetchall()
        for t, c, ftype in top:
            print(f"   {c:2} edges | {t} [{ftype}]")

        conn.close()

    # ── suggest ───────────────────────────────────────────────────────────────

    def suggest(self, file_title: str) -> list[dict[str, Any]]:
        """Suggest related notes for a given file.

        Returns:
            List of suggestion dicts with keys: file_path, file_title,
            category, rationale, score.

        Categories: link_candidate, related_reading, possible_duplicate,
        orphan_rescue.
        """
        conn = self._require_conn()
        row = conn.execute(
            "SELECT id, path, title FROM files WHERE title = ? OR path LIKE ?",
            (file_title, f"%{file_title}%"),
        ).fetchone()
        if not row:
            conn.close()
            return []

        src_id, src_path, src_title = row
        suggestions: dict[str, dict[str, Any]] = {}

        # 1. Structural neighbors (connected at depth 2 but not directly linked)
        direct_ids: set[int] = {
            r[0]
            for r in conn.execute(
                """SELECT dst_file_id FROM edges
                   WHERE src_file_id = ? AND dst_file_id IS NOT NULL
                   UNION
                   SELECT src_file_id FROM edges
                   WHERE dst_file_id = ?""",
                (src_id, src_id),
            ).fetchall()
        }

        depth2_ids = set()
        for d_id in direct_ids:
            for r in conn.execute(
                """SELECT dst_file_id FROM edges
                   WHERE src_file_id = ? AND dst_file_id IS NOT NULL
                   UNION
                   SELECT src_file_id FROM edges
                   WHERE dst_file_id = ?""",
                (d_id, d_id),
            ).fetchall():
                if r[0] and r[0] != src_id and r[0] not in direct_ids:
                    depth2_ids.add(r[0])

        for cand_id in depth2_ids:
            cand = conn.execute(
                "SELECT path, title, file_type FROM files WHERE id = ?", (cand_id,)
            ).fetchone()
            if cand:
                key = cand[0]
                suggestions[key] = {
                    "file_path": cand[0],
                    "file_title": cand[1],
                    "file_type": cand[2],
                    "category": "link_candidate",
                    "rationale": f"Reachable at depth-2 from {src_title} via shared connections",
                    "score": 0.6,
                }

        # 2. FTS similarity: search using the source file's title and tags
        tag_rows = conn.execute(
            "SELECT tag FROM tags WHERE file_id = ?", (src_id,)
        ).fetchall()
        query_terms = src_title + " " + " ".join(r[0] for r in tag_rows)
        fts_results = self._fts_search(conn, query_terms, None, None, limit=10)
        for res in fts_results:
            rpath = res["file_path"]
            if rpath == src_path:
                continue
            if rpath not in suggestions:
                suggestions[rpath] = {
                    "file_path": rpath,
                    "file_title": res["file_title"],
                    "file_type": res["file_type"],
                    "category": "related_reading",
                    "rationale": (
                        f"Semantically similar content (FTS match: {res['snippet'][:60]}…)"
                    ),
                    "score": min(0.9, abs(res["score"]) / 10.0),
                }

        # 3. Orphan rescue: very similar isolated notes
        for rpath, s in list(suggestions.items()):
            cand_id_row = conn.execute(
                "SELECT id FROM files WHERE path = ?", (rpath,)
            ).fetchone()
            if not cand_id_row:
                continue
            cand_id = cand_id_row[0]
            edge_count = conn.execute(
                """SELECT COUNT(*) FROM edges
                   WHERE src_file_id = ? OR dst_file_id = ?""",
                (cand_id, cand_id),
            ).fetchone()[0]
            if edge_count == 0 and s["category"] == "related_reading":
                suggestions[rpath]["category"] = "orphan_rescue"
                suggestions[rpath]["rationale"] = (
                    "Isolated note that shares content with " + src_title
                )

        conn.close()
        return sorted(suggestions.values(), key=lambda x: -x["score"])


# ── CLI ────────────────────────────────────────────────────────────────────────


@click.group()
def cli() -> None:
    """Vault Knowledge Graph Indexer."""


@cli.command()
@_VAULT_OPT
def build(vault: Path | None) -> None:
    """Rebuild the index from the vault."""
    VaultIndexer(_resolve_vault(vault)).build_index()


@cli.command()
@click.argument("file")
@click.option("--depth", "-d", default=2, help="Maximum traversal depth.")
@click.option(
    "--include-inline",
    is_flag=True,
    default=False,
    help="Include typed inline relations.",
)
@_VAULT_OPT
def traverse(file: str, depth: int, include_inline: bool, vault: Path | None) -> None:
    """Traverse the graph from a starting FILE."""
    VaultIndexer(_resolve_vault(vault)).traverse(file, depth, include_inline)


@cli.command()
@click.option(
    "--inline-relations",
    is_flag=True,
    default=False,
    help="Show unresolved inline relation diagnostics.",
)
@_VAULT_OPT
def gaps(inline_relations: bool, vault: Path | None) -> None:
    """Report orphans, broken links, and connectivity stats."""
    VaultIndexer(_resolve_vault(vault)).find_gaps(inline_relations)


@cli.command()
@click.argument("query")
@click.option(
    "--mode",
    type=click.Choice(["fts", "semantic", "hybrid"]),
    default="fts",
    help="Search mode.",
)
@click.option("--type", "file_type", default=None, help="Filter by file type.")
@click.option("--tag", default=None, help="Filter by tag.")
@click.option("--limit", default=DEFAULT_SEARCH_LIMIT, help="Max results.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@_VAULT_OPT
def search(
    query: str,
    mode: str,
    file_type: str | None,
    tag: str | None,
    limit: int,
    as_json: bool,
    vault: Path | None,
) -> None:
    """Search the vault."""
    indexer = VaultIndexer(_resolve_vault(vault))
    results = indexer.search(
        query, mode=mode, file_type=file_type, tag=tag, limit=limit
    )
    if as_json:
        click.echo(json.dumps(results, indent=2))
        return
    if not results:
        click.echo("No results.")
        return
    for r in results:
        heading = f"#{r['chunk_heading']}" if r["chunk_heading"] else ""
        click.echo(f"  {r['file_title']}{heading}  [{r['file_type']}]")
        click.echo(f"    {r['snippet']}")
        click.echo(f"    → {r['file_path']}")


@cli.command()
@click.option("--type", "entity_type", default=None, help="Filter by entity type.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@_VAULT_OPT
def entities(entity_type: str | None, as_json: bool, vault: Path | None) -> None:
    """List indexed entities."""
    indexer = VaultIndexer(_resolve_vault(vault))
    ents = indexer.list_entities(entity_type)
    if as_json:
        click.echo(json.dumps(ents, indent=2))
        return
    for e in ents:
        click.echo(f"  {e['name']}  [{e['type']}]  ({e['source']})")


@cli.command()
@click.argument("file")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@_VAULT_OPT
def suggest(file: str, as_json: bool, vault: Path | None) -> None:
    """Suggest related notes for a FILE."""
    indexer = VaultIndexer(_resolve_vault(vault))
    results = indexer.suggest(file)
    if as_json:
        click.echo(json.dumps(results, indent=2))
        return
    if not results:
        click.echo("No suggestions.")
        return
    for s in results:
        click.echo(f"  [{s['category']}] {s['file_title']}")
        click.echo(f"    {s['rationale']}")


if __name__ == "__main__":
    cli()
