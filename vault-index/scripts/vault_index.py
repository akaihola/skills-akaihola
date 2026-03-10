#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["click", "pyyaml"]
# ///
"""Vault Knowledge Graph Indexer.

Index an Obsidian-style markdown vault into a SQLite database for graph
queries, link analysis, and gap detection.

Usage::

    vault-index build [--vault PATH]     # Rebuild the index
    vault-index traverse TITLE [--depth N]  # Graph traversal
    vault-index gaps                     # Orphans, broken links, stats

Environment:
    VAULT_ROOT  Path to the vault root (used when --vault is not given).
"""

from __future__ import annotations

import contextlib
import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import click
import yaml

if TYPE_CHECKING:
    from collections.abc import Callable

# ── constants ──────────────────────────────────────────────────────────────────

YAML_SPLIT_MIN_PARTS = 3
LINK_PREFIX_MIN_LEN = 10

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
    # Strip fenced code blocks (``` or ````+)
    stripped = re.sub(r"(`{3,}).*?\1", "", content, flags=re.DOTALL)
    # Strip inline code
    stripped = re.sub(r"`[^`]+`", "", stripped)
    # [[Target]] and [[Target|Alias]]; ]] used as delimiter (handles ] in names)
    pattern = r"\[\[((?:(?!\]\]).)+?)(?:\|(?:(?!\]\]).)+?)?\]\]"
    links = re.findall(pattern, stripped)
    # Strip #heading suffixes
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


def parse_file(vault_root: Path, path: Path) -> FileInfo:
    """Parse a markdown file and return a :class:`FileInfo`."""
    with contextlib.suppress(Exception):
        content = path.read_text(encoding="utf-8")
        metadata, body = _parse_frontmatter(content)

        # File type inferred from path
        rel = path.relative_to(vault_root)
        if "Projects" in rel.parts:
            file_type = "project"
        elif "journals" in rel.parts:
            file_type = "journal"
        else:
            file_type = "note"

        # Title: frontmatter > first heading > stem
        title: str = metadata.get("title", "") or path.stem
        if title == path.stem:
            m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
            if m:
                title = m.group(1)

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
        )
    return FileInfo(path=path, title=path.stem, file_type="note")


# ── database ───────────────────────────────────────────────────────────────────


def init_db(db_path: Path) -> sqlite3.Connection:
    """Create (or open) the SQLite index and ensure the schema exists."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    conn.executescript("""
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
            edge_type   TEXT NOT NULL,  -- 'frontmatter' or 'wiki-link'
            dst_target  TEXT,           -- unresolved target text
            UNIQUE(src_file_id, dst_file_id, rel_type, edge_type),
            FOREIGN KEY (src_file_id) REFERENCES files(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_files_path  ON files(path);
        CREATE INDEX IF NOT EXISTS idx_files_title ON files(title);
        CREATE INDEX IF NOT EXISTS idx_files_type  ON files(file_type);
        CREATE INDEX IF NOT EXISTS idx_edges_src   ON edges(src_file_id);
        CREATE INDEX IF NOT EXISTS idx_edges_dst   ON edges(dst_file_id);
        CREATE INDEX IF NOT EXISTS idx_edges_rel   ON edges(rel_type);
        CREATE INDEX IF NOT EXISTS idx_tags_file   ON tags(file_id);
        CREATE INDEX IF NOT EXISTS idx_tags_tag    ON tags(tag);
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
            # Prefix match for truncated names (heuristic)
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
        conn.execute("DELETE FROM edges")
        conn.execute("DELETE FROM tags")
        conn.execute("DELETE FROM files")

        files = self.scan_vault()
        print(f"Found {len(files)} files")

        resolve = self._make_resolver(files)

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
            assert row_id is not None  # always set after INSERT
            file_ids[f.path] = row_id
            for tag in f.tags:
                conn.execute(
                    "INSERT INTO tags (file_id, tag) VALUES (?, ?)",
                    (cur.lastrowid, tag),
                )

        for f in files:
            src_id = file_ids[f.path]
            body = ""
            with contextlib.suppress(Exception):
                raw = f.path.read_text(encoding="utf-8")
                _, body = _parse_frontmatter(raw)

            # Frontmatter relationships
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

            # Wiki-links
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

        conn.commit()
        edge_count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        tag_count = conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        print(f"Index built: {edge_count} edges, {tag_count} tags")
        print(f"Database: {self.db_path}")
        conn.close()

    # ── query ─────────────────────────────────────────────────────────────────

    def _require_conn(self) -> sqlite3.Connection:
        """Open the database.

        Raises:
            RuntimeError: if the index has not been built yet.

        """
        if not self.db_path.exists():
            msg = "Index not built. Run 'vault-index build' first."
            raise RuntimeError(msg)
        return sqlite3.connect(self.db_path)

    def traverse(self, start_file: str, max_depth: int = 2) -> None:
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
                "SELECT title, file_type FROM files WHERE id = ?",
                (current_id,),
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
        conn.close()

    def find_gaps(self) -> None:
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
@_VAULT_OPT
def traverse(file: str, depth: int, vault: Path | None) -> None:
    """Traverse the graph from a starting FILE."""
    VaultIndexer(_resolve_vault(vault)).traverse(file, depth)


@cli.command()
@_VAULT_OPT
def gaps(vault: Path | None) -> None:
    """Report orphans, broken links, and connectivity stats."""
    VaultIndexer(_resolve_vault(vault)).find_gaps()


if __name__ == "__main__":
    cli()
