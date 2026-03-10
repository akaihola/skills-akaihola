---
name: vault-index
description: >-
  Build, query, and traverse an Obsidian-style markdown vault as a knowledge
  graph. Use this skill whenever the user asks to index their vault, find
  related notes, search vault content, discover orphan or broken-link files,
  traverse connections between notes, do semantic search across the vault, or
  surface proactive suggestions about what to link next. Always load this skill
  when the words "vault", "knowledge graph", "vault-index", or "obsidian notes"
  appear in context.
---

# vault-index skill

Tools for indexing an Obsidian-style markdown vault into a SQLite database and
querying it as a knowledge graph.

## Environment

Set `VAULT_ROOT` to the vault directory, or pass `--vault PATH` to every
command. The default falls back to `VAULT_ROOT` env var, then the current
working directory.

```bash
export VAULT_ROOT=~/my-knowledge   # or pass --vault each time
```

## Commands

All commands live in `scripts/vault-index.py` and are PEP 723 standalone
scripts (run with `uv run` or directly if `uv` is on `PATH`).

### build – rebuild the index

Parse every `.md` file, extract wiki-links, frontmatter relationships, tags,
and (when enabled) chunk text for FTS5 / embeddings.

```bash
uv run vault-index/scripts/vault-index.py build
uv run vault-index/scripts/vault-index.py build --vault ~/my-knowledge
VAULT_ROOT=~/my-knowledge python vault-index/scripts/vault-index.py build
```

Run after any significant batch of vault edits, or hook it into a git
post-commit.

### traverse – graph traversal from a note

Walk outgoing and incoming edges from a starting file and print a tree.

```bash
uv run vault-index/scripts/vault-index.py traverse "Vault Knowledge Graph"
uv run vault-index/scripts/vault-index.py traverse "Second Brain" --depth 3
```

Use this when the user asks "what's related to X?" or wants to see how a note
connects to the rest of the vault.

### gaps – orphan and broken-link report

Find project files with no connections, broken wiki-links, and link distribution
statistics.

```bash
uv run vault-index/scripts/vault-index.py gaps
```

Use for vault maintenance: after major edits, or when preparing a health report.

### search – full-text and semantic search _(Phase 2b)_

```bash
uv run vault-index/scripts/vault-index.py search "semantic search" --mode fts
uv run vault-index/scripts/vault-index.py search "MCP tool discovery" --mode hybrid
uv run vault-index/scripts/vault-index.py search "pykoclaw" --entity
```

### suggest – related note suggestions _(Phase 3)_

```bash
uv run vault-index/scripts/vault-index.py suggest "Vault Knowledge Graph"
```

## Database

The index is stored in `<vault>/.vault-index.db` (SQLite). It is fully
disposable and rebuildable from the markdown source files. Add it to
`.gitignore`.

### Core schema (Phase 2a)

| Table   | Contents                                                  |
| ------- | --------------------------------------------------------- |
| `files` | One row per `.md` file – path, title, type, status, dates |
| `tags`  | Frontmatter tags per file                                 |
| `edges` | Wiki-links and typed frontmatter relationships            |

### Extended schema (Phase 2b+)

| Table              | Contents                                          |
| ------------------ | ------------------------------------------------- |
| `content_chunks`   | Heading-split chunks with heading path            |
| `fts_chunks`       | FTS5 virtual table for keyword search             |
| `embeddings`       | Per-chunk embedding vectors (sqlite-vec)          |
| `entities`         | Named entities (projects, tools, people, …)       |
| `entity_mentions`  | Where each entity is mentioned                    |
| `inline_relations` | Typed body-level relations (`- depends_on [[X]]`) |

## Relationship vocabulary

Used in frontmatter fields and body-level inline relations:

| Relation      | Meaning                                        |
| ------------- | ---------------------------------------------- |
| `depends_on`  | This note/project requires the target          |
| `blocks`      | This work prevents the target from progressing |
| `related`     | Sibling topic (bidirectional)                  |
| `builds_on`   | Extends or elaborates on the target            |
| `similar_to`  | Different angle on the same subject            |
| `contradicts` | This note disagrees with the target            |

### Inline relation format (body text)

```markdown
- depends_on [[pykoclaw plugin system]]
- related_to [[Agent Commons]]
- builds_on [[Second Brain]]
```

## Agent behaviour guide

| User intent                        | Preferred tool         |
| ---------------------------------- | ---------------------- |
| "what's related to X?"             | `traverse`             |
| fuzzy recall / "that note about Y" | `search --mode hybrid` |
| vault maintenance, orphans         | `gaps`                 |
| after editing a file               | `suggest`              |

When the index may be stale (vault files newer than `.vault-index.db`), warn the
user and offer to rebuild before answering retrieval questions.

## Development notes

- Tests live in `vault-index/tests/`; run with `uv run pytest vault-index/tests/`
- The index is always rebuildable from markdown — never treat it as canonical
- Phase roadmap: 2a (structural, ✅) → 2b (FTS5 + embeddings) → 3 (MCP) → 4 (proactive)
