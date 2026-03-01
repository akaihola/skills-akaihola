---
name: read-as-markdown
description: >-
  Convert binary document files (PDF, DOCX, EPUB) to cached Markdown for
  reading. Use when the user asks to "read a PDF", "convert docx to markdown",
  "extract text from a document", "show me this PDF as markdown", "read this
  paper", or mentions reading, viewing, or extracting text from .pdf, .docx, or
  .epub files. This skill is for READING documents as markdown — not for
  creating or editing them (use the pdf/docx skills for that).
version: 1.0.0
---

# Read as Markdown

Convert PDF, DOCX, and EPUB files to cached Markdown. The converted Markdown is
stored in a per-workspace cache so repeated reads are instant.

## Quick start

```bash
uv run ~/.claude/skills/read-as-markdown/scripts/read_as_markdown.py ~/paivi/downloads/paper.pdf
```

Returns JSON with the cache path, total line count, and the first 200 lines of
content. Use the `Read` tool with offset/limit on `cache_path` for further
chunks.

## How it works

1. Detects format from file extension
2. Finds workspace root (walks up to find `.claude/` directory)
3. Checks cache at `<workspace>/.cache/markdown/<relative-path>.md`
   - Fast path: mtime + size match in `.meta` sidecar → cache hit
   - Content-hash fallback: SHA-256 of original file checked against
     `index.json` → finds cache even if the source file was moved/renamed
4. On miss: dispatches to the appropriate converter backend
5. Writes markdown + `.meta` sidecar + updates `index.json` hash index
6. Returns JSON with first N lines (default 200)

## CLI interface

```
read_as_markdown.py FILE [options]

positional arguments:
  FILE                    Path to document file (.pdf, .docx, .epub)

options:
  --workspace-root PATH   Override workspace root (auto-detected via .claude/)
  --limit N               Max lines to return (default: 200)
  --offset N              Line offset for chunked reading (default: 0)
  --backend NAME          Force a specific backend (pandoc, pdftotext)
```

## Output format

```json
{
  "cache_path": "/home/agent/paivi/.cache/markdown/downloads/paper.md",
  "total_lines": 847,
  "content": "first 200 lines...",
  "source": "/home/agent/paivi/downloads/paper.pdf",
  "format": "pdf",
  "backend": "pdftotext",
  "cached": false
}
```

On error: `{"error": "description"}`.

## Caching

Cache lives at `<workspace>/.cache/markdown/` mirroring the source file tree.
Each cached file has a `.meta` JSON sidecar:

```json
{
  "mtime": 1709312456.789,
  "size": 2048576,
  "content_hash": "sha256:a1b2c3...",
  "toolchain": [
    {"step": "convert", "backend": "pdftotext", "version": "24.04.0", "at": "2026-03-01T12:00:00+00:00"}
  ],
  "converted_at": "2026-03-01T12:00:00+00:00"
}
```

A hash index at `<workspace>/.cache/markdown/index.json` maps content hashes to
cache paths, enabling cache hits when source files are moved or renamed.

The `toolchain` array records every processing step — the initial conversion and
any later post-processing (formatting, cleanup, refinement by helper scripts).
Each step records its name, tool, version, and timestamp.

## Backends

| Format | Default backend | Fallback |
|--------|----------------|----------|
| PDF    | pdftotext      | pandoc   |
| DOCX   | pandoc         | —        |
| EPUB   | pandoc         | —        |

**pdftotext** uses `-layout` mode for best table/column preservation in academic
papers. On NixOS, automatically falls back to `nix-shell -p poppler-utils` if
pdftotext is not in PATH.

**pandoc** uses `--to=markdown --wrap=none` for clean, unwrapped output.

### Adding a new backend

Add a converter function and register it in `BACKENDS`:

```python
def marker_converter(source: Path) -> tuple[str, str]:
    # ... convert ...
    return markdown_text, "marker 1.0"

BACKENDS["pdf"].insert(0, ("marker", marker_converter))
```

## Distinction from pdf/docx skills

- **read-as-markdown**: Reads documents → produces Markdown for the agent to consume
- **pdf skill**: Creates, merges, splits, watermarks, OCR, fills forms in PDFs
- **docx skill**: Creates, edits, tracks changes in Word documents
