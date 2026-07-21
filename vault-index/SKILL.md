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
querying it as a knowledge graph. **All milestones through Phase 4.5 are
complete:** FTS5 + embeddings, entity extraction, MCP server, rich suggestions,
co-access logging, reports, temporal scoring, watched topics, weekly review, and
proactive suggestions.

## Environment

Set `VAULT_ROOT` to the vault directory, or pass `--vault PATH` to every
command.

```bash
export VAULT_ROOT=~/my-knowledge   # or pass --vault each time
```

**Package location:** `~/prg/vault-index/`  
**Run commands:** `uv run --project ~/prg/vault-index vault-index <cmd>`

## Quick reference

```bash
vault-index build                              # rebuild index
vault-index search "query" --mode hybrid      # best general search
vault-index search "query" --mode fts         # exact keyword
vault-index search "query" --mode semantic    # fuzzy/conceptual
vault-index search "query" --entity "CCM"     # filter by entity mention
vault-index traverse "Note Title" --json      # graph traversal (JSON)
vault-index gaps --json                       # orphans + broken links
vault-index entities --type project           # list entities
vault-index suggest "Note Title"              # related-note suggestions
vault-index report health                      # vault health check
vault-index report stale                      # structurally important but stale files
vault-index report watched                    # matches for configured watched topics
vault-index weekly-review                     # full weekly health review
vault-index proactive [--limit 10]            # proactive maintenance suggestions
vault-index watched-topics set pykoclaw MCP  # configure watched topics
vault-index watched-topics list              # see current watched topics
vault-index serve                             # start MCP server (stdio)
vault-index serve --transport sse             # MCP over HTTP/SSE
```

## Commands in detail

### build

Parse every `.md` file: extract wiki-links, frontmatter relationships, tags,
chunk text for FTS5, and embed chunks with Gemini `gemini-embedding-001` (when
`GEMINI_API_KEY` is set). Unchanged chunks reuse cached embeddings.

```bash
vault-index build
vault-index build --vault ~/other-vault
```

Run after significant batch edits, or hook into git post-commit.

### search

```bash
# FTS5 keyword search (always available)
vault-index search "tool search" --mode fts

# Semantic (requires GEMINI_API_KEY + built index with embeddings)
vault-index search "what note explains deferred loading of MCP tools" --mode semantic

# Hybrid: FTS5 + semantic (default for best recall)
vault-index search "knowledge graph" --mode hybrid

# Filter options (all combinable across all modes)
vault-index search "query" --type project          # file type filter
vault-index search "query" --tag MCP               # frontmatter tag filter
vault-index search "query" --path pages/Projects   # path prefix filter
vault-index search "query" --since 2026-03-01      # recency (YYYY-MM-DD)
vault-index search "query" --entity "Agent Commons" # entity mention filter
vault-index search "query" --json                  # JSON output
vault-index search "query" --limit 5               # result cap
```

JSON result schema (stable):

```json
[
  {
    "file_path": "/abs/path/to/file.md",
    "file_title": "Note Title",
    "file_type": "project|note|journal",
    "chunk_heading": "Section Heading",
    "snippet": "...matched text...",
    "score": 0.85,
    "match_reasons": ["fts", "semantic"]
  }
]
```

### traverse

Walk outgoing and incoming edges from a starting file.

```bash
vault-index traverse "Vault Knowledge Graph"
vault-index traverse "Second Brain" --depth 3 --include-inline
vault-index traverse "Agent Commons" --json   # machine-readable
```

**JSON output:** list of `{file_path, file_title, depth, rel_type, edge_type}`.

Use when user asks "what's related to X?" or needs graph-based navigation.

### gaps

Orphans, broken links, and link-distribution statistics.

```bash
vault-index gaps
vault-index gaps --inline-relations
vault-index gaps --json
```

**JSON output:** `{orphans: [...], broken_links: N, isolated_files: [...]}`.

### entities

List all indexed entities (auto-registered files + frontmatter explicit).

```bash
vault-index entities
vault-index entities --type project
vault-index entities --type tool
vault-index entities --json
```

### suggest

Suggest related notes using four signals:

- **link_candidate** — depth-2 structural neighbors
- **related_reading** — FTS content similarity
- **orphan_rescue** — isolated files with topical overlap
- **semantic_neighbor** — embedding cosine similarity ≥ 0.7
- **shared_entity** — files mentioning the same entity

```bash
vault-index suggest "Vault Knowledge Graph"
vault-index suggest "Second Brain" --json
```

### serve

Start the read-only MCP server exposing: `search`, `traverse`, `gaps`,
`entities`, `suggest` as MCP tools.

```bash
vault-index serve                      # stdio (Claude Desktop / Pi)
vault-index serve --transport sse      # HTTP/SSE
```

**Claude Desktop config** (`~/.config/claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "vault-index": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "/home/agent/prg/vault-index",
        "vault-index",
        "serve"
      ],
      "env": { "VAULT_ROOT": "/home/agent/my-knowledge" }
    }
  }
}
```

**Pi config** — add to agent MCP config or tool list.

## Agent behavioral guide

| User intent                       | Use                       |
| --------------------------------- | ------------------------- |
| "what's related to X?"            | `traverse X`              |
| "find notes about Y" (fuzzy)      | `search Y --mode hybrid`  |
| "find notes mentioning Z entity"  | `search Q --entity Z`     |
| vault hygiene / orphan check      | `gaps`                    |
| after editing a file, check links | `suggest <file>`          |
| list all project entities         | `entities --type project` |

### Index freshness

Before answering retrieval questions, check if the index is stale:

```bash
stat -c %Y /home/agent/my-knowledge/.vault-index.db
find /home/agent/my-knowledge -name "*.md" -newer .vault-index.db | head -5
```

If `.md` files are newer than the index, warn the user and offer to rebuild.

### When to use which search mode

- **`fts`** — exact terminology matters (`"pykoclaw"`, `"CCM"`, `"gemini-embedding-001"`)
- **`semantic`** — conceptual recall, paraphrased queries, "what was that note about…"
- **`hybrid`** — default for most queries (combines both signals)

## Database schema

**Core (Phase 2a):** `files`, `tags`, `edges`  
**Extended (Phase 2b+):** `content_chunks`, `fts_chunks`, `embeddings`,
`entities`, `entity_mentions`, `inline_relations`

The database is fully disposable — always rebuildable from markdown.  
Add `.vault-index.db` to `.gitignore`.

## Relationship vocabulary

Frontmatter fields and inline body relations:

| Relation      | Meaning                                        |
| ------------- | ---------------------------------------------- |
| `depends_on`  | This note/project requires the target          |
| `blocks`      | This work prevents the target from progressing |
| `related`     | Sibling topic (bidirectional)                  |
| `builds_on`   | Extends or elaborates on the target            |
| `similar_to`  | Different angle on the same subject            |
| `contradicts` | This note disagrees with the target            |

Inline format: `- depends_on [[pykoclaw plugin system]]`

## Development notes

- **Package:** `~/prg/vault-index/` (editable install via `uv sync`)
- **Tests:** `cd ~/prg/vault-index && uv run pytest tests/ -v`
- **Current test count:** 87 passing
- **Phase status:** 2a ✅ · 2b.1 ✅ · 2b.2 ✅ · 2b.3 ✅ · 2b.4 ✅ · 2b.5 ✅ · 3.1 ✅ · 3.2 ✅ · 3.3 ✅ · 3.4 ✅ · 3.5 ✅ · 4.1 ✅ · 4.2 ✅ · 4.3 ✅ · 4.4 ✅ · 4.5 ✅
