# Markdown cache and converter details

Implementation: [read-as-markdown/scripts/read_as_markdown.py].

## Output format

```json
{
  "cache_path": "/home/user/.cache/markdown/downloads/paper.pdf.md",
  "total_lines": 847,
  "content": "first 200 lines...",
  "source": "/home/user/downloads/paper.pdf",
  "format": "pdf",
  "backend": "pdftotext",
  "cached": false
}
```

Handled conversion errors return `{"error": "description"}` with exit status 0.
Argument errors exit nonzero; uncaught exceptions can still produce a traceback.

## Caching

Cache lives at `<workspace>/.cache/markdown/` mirroring in-workspace source paths.
It retains the original extension: `paper.pdf.md` and `paper.pdf.meta`. Sources
outside the workspace use only the filename. Files with the same filename
outside the workspace therefore share a cache location.
Symlinks in the cache are refused. Index entries outside the cache are ignored.
A document’s own `.claude/` directory cannot select the workspace.
Each cached file has a `.meta` JSON sidecar:

```json
{
  "mtime": 1709312456.789,
  "size": 2048576,
  "content_hash": "sha256:a1b2c3...",
  "toolchain": [
    {"step": "convert", "backend": "pdftotext", "version": "pdftotext (pdftotext version 24.04.0)", "at": "2026-03-01T12:00:00+00:00"}
  ],
  "converted_at": "2026-03-01T12:00:00+00:00"
}
```

A hash index at `<workspace>/.cache/markdown/index.json` maps content hashes to
relative cache paths, enabling cache hits when source files are moved or renamed.

The script writes one `convert` entry in `toolchain`. It does not implement or
record later post-processing.

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


[read-as-markdown/scripts/read_as_markdown.py]: ../scripts/read_as_markdown.py
