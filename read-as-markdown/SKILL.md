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
uv run ~/.claude/skills/read-as-markdown/scripts/read_as_markdown.py ~/documents/paper.pdf
```

Returns JSON with the cache path, total line count, and the first 200 lines of
content. Use the `Read` tool with offset/limit on `cache_path` for further
chunks.

## How it works

1. Detects format from file extension
2. Finds workspace root from the current working directory (walks up to find `.claude/`; falls back to the current directory)
3. Checks cache at `<workspace>/.cache/markdown/<relative-source-path>.md`
   for in-workspace sources, or
   `<workspace>/.cache/markdown/_external/<path-hash>/<filename>.md` for external
   sources (first 16 hex digits of SHA-256 of the resolved absolute source path)
   - Fast path: mtime + size match in `.meta` sidecar → cache hit
   - Content-hash fallback: SHA-256 of original file checked against
     `index.json` → finds cache even if the source file was moved/renamed
4. On miss: dispatches to the appropriate converter backend
5. Writes Markdown + `.meta` sidecar + updates `index.json` hash index;
   after conversion, creates or updates the workspace `.gitignore` with `.cache/`
6. Returns JSON with first N lines (default 200)

## CLI interface

```
read_as_markdown.py FILE [options]

positional arguments:
  FILE                    Path to document file (.pdf, .docx, .epub)

options:
  --workspace-root PATH   Override workspace root (default: .claude/ ancestor of current directory)
  --limit N               Max lines to return (default: 200)
  --offset N              Line offset for chunked reading (default: 0)
  --backend NAME          Force a specific backend (pandoc, pdftotext)
```

## Output and cache details

Read [cache layout and backends](references/cache.md) when inspecting cached
files, diagnosing conversion errors or adding a converter. The cache retains
the source extension, mirrors in-workspace paths, and groups external sources
under `_external/<path-hash>/` so same-name documents have separate caches.
It is local to the selected workspace.

Conversion writes cached files and may update the workspace ignore file.
Success exits 0. Handled errors are JSON objects with an `error` key and exit
status 1.
PDF uses `pdftotext` first, then the registered `pandoc` fallback; DOCX/EPUB
use `pandoc`. Forced backends do not fall back.

## Distinction from pdf/docx skills

- **read-as-markdown**: Reads documents → produces Markdown for the agent to consume
- **pdf skill**: Creates, merges, splits, watermarks, OCR, fills forms in PDFs
- **docx skill**: Creates, edits, tracks changes in Word documents
