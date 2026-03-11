#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Convert PDF, DOCX, and EPUB files to cached Markdown.

Converts documents using pluggable backends (pandoc, pdftotext) and caches the
result in the workspace's .cache/markdown/ directory.  Repeated reads are
instant.  A content-hash index enables cache hits even when source files are
moved or renamed.

Usage:
    read_as_markdown.py FILE
    read_as_markdown.py FILE --limit 50 --offset 200
    read_as_markdown.py FILE --backend pandoc
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable

# ---------------------------------------------------------------------------
# Format / extension mapping
# ---------------------------------------------------------------------------

FORMAT_EXTENSIONS: dict[str, list[str]] = {
    "pdf": [".pdf"],
    "docx": [".docx"],
    "epub": [".epub"],
}

EXT_TO_FORMAT: dict[str, str] = {
    ext: fmt for fmt, exts in FORMAT_EXTENSIONS.items() for ext in exts
}

# ---------------------------------------------------------------------------
# Converter backends
#
# Each converter takes a Path and returns (markdown_text, version_string).
# The version string is recorded in the toolchain metadata.
# ---------------------------------------------------------------------------


def _run(cmd: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    """Run a subprocess, raising RuntimeError on failure."""
    result = subprocess.run(  # noqa: S603
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"command failed: {cmd}")
    return result


def _get_pandoc_version() -> str:
    """Return pandoc version string, or 'unknown'."""
    try:
        r = _run(["pandoc", "--version"])
        first_line = r.stdout.splitlines()[0]  # "pandoc 3.7.0.2"
        return first_line.split()[-1] if first_line else "unknown"
    except (RuntimeError, IndexError, FileNotFoundError):
        return "unknown"


def pandoc_converter(source: Path) -> tuple[str, str]:
    """Convert document to markdown using pandoc."""
    pandoc = shutil.which("pandoc")
    if not pandoc:
        msg = "pandoc not found in PATH"
        raise RuntimeError(msg)
    result = _run([pandoc, "--to=markdown", "--wrap=none", str(source)])
    return result.stdout, f"pandoc {_get_pandoc_version()}"


def _find_pdftotext() -> list[str]:
    """Return command prefix for pdftotext, with nix-shell fallback."""
    if shutil.which("pdftotext"):
        return ["pdftotext"]
    if shutil.which("nix-shell"):
        return ["nix-shell", "-p", "poppler-utils", "--run"]
    msg = "pdftotext not found. Install poppler-utils or ensure nix-shell is available."
    raise RuntimeError(msg)


def _get_pdftotext_version(cmd_prefix: list[str]) -> str:
    """Return pdftotext version string, or 'unknown'."""
    try:
        if cmd_prefix[0] == "nix-shell":
            r = _run([*cmd_prefix, "pdftotext -v 2>&1 || true"])
        else:
            r = subprocess.run(  # noqa: S603
                [*cmd_prefix, "-v"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        # pdftotext prints version to stderr
        text = r.stderr or r.stdout
        for line in text.splitlines():
            if "pdftotext" in line.lower() or "poppler" in line.lower():
                return line.strip()
        return "unknown"
    except (RuntimeError, FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"


def pdftotext_converter(source: Path) -> tuple[str, str]:
    """Convert PDF to text using pdftotext -layout."""
    cmd_prefix = _find_pdftotext()
    version = _get_pdftotext_version(cmd_prefix)

    if cmd_prefix[0] == "nix-shell":
        # nix-shell --run takes a single shell command string
        result = _run([*cmd_prefix, f"pdftotext -layout '{source}' -"])
    else:
        result = _run([*cmd_prefix, "-layout", str(source), "-"])

    return result.stdout, f"pdftotext ({version})"


# ---------------------------------------------------------------------------
# Backend registry
#
# format -> [(backend_name, converter_fn), ...]
# First entry is the default; others are fallbacks.
# ---------------------------------------------------------------------------

BackendEntry = tuple[str, Callable[[Path], tuple[str, str]]]

BACKENDS: dict[str, list[BackendEntry]] = {
    "pdf": [("pdftotext", pdftotext_converter), ("pandoc", pandoc_converter)],
    "docx": [("pandoc", pandoc_converter)],
    "epub": [("pandoc", pandoc_converter)],
}

# ---------------------------------------------------------------------------
# Workspace root detection
# ---------------------------------------------------------------------------


def find_workspace_root(start: Path) -> Path | None:
    """Walk up from *start* to find the nearest directory containing .claude/."""
    current = start.resolve()
    while current != current.parent:
        if (current / ".claude").is_dir():
            return current
        current = current.parent
    return None


# ---------------------------------------------------------------------------
# Content hashing
# ---------------------------------------------------------------------------

HASH_ALGORITHM = "sha256"
HASH_BUF_SIZE = 1 << 16  # 64 KiB


def content_hash(path: Path) -> str:
    """Return 'sha256:<hex>' digest of a file's contents."""
    h = hashlib.new(HASH_ALGORITHM)
    with path.open("rb") as f:
        while chunk := f.read(HASH_BUF_SIZE):
            h.update(chunk)
    return f"{HASH_ALGORITHM}:{h.hexdigest()}"


# ---------------------------------------------------------------------------
# Cache path computation
# ---------------------------------------------------------------------------


def compute_cache_paths(source: Path, workspace_root: Path) -> tuple[Path, Path]:
    """Return (cache_md_path, cache_meta_path) for a source file.

    The original extension is preserved in the cached filename to avoid
    collisions between e.g. ``paper.pdf`` and ``paper.docx``.  A ``.md``
    suffix is appended: ``paper.pdf.md``, ``paper.pdf.meta``.
    """
    try:
        rel = source.resolve().relative_to(workspace_root.resolve())
    except ValueError:
        # Source is outside workspace — use filename only
        rel = Path(source.name)

    cache_dir = workspace_root / ".cache" / "markdown"
    # Append .md/.meta to the full name (keeps original extension for disambiguation)
    cache_md = cache_dir / rel.parent / (rel.name + ".md")
    cache_meta = cache_dir / rel.parent / (rel.name + ".meta")
    return cache_md, cache_meta


# ---------------------------------------------------------------------------
# Hash index (content_hash -> cache_path)
# ---------------------------------------------------------------------------


def _index_path(workspace_root: Path) -> Path:
    return workspace_root / ".cache" / "markdown" / "index.json"


def load_index(workspace_root: Path) -> dict[str, str]:
    """Load the hash-to-cache-path index. Returns empty dict on error."""
    idx = _index_path(workspace_root)
    if not idx.exists():
        return {}
    try:
        return json.loads(idx.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_index(workspace_root: Path, index: dict[str, str]) -> None:
    """Persist the hash-to-cache-path index."""
    idx = _index_path(workspace_root)
    idx.parent.mkdir(parents=True, exist_ok=True)
    idx.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Cache validation
# ---------------------------------------------------------------------------


def check_cache(
    source: Path,
    cache_md: Path,
    cache_meta: Path,
    backend_name: str | None,
) -> bool:
    """Return True if the path-based cache is valid (hit)."""
    if not cache_md.exists() or not cache_meta.exists():
        return False
    try:
        meta = json.loads(cache_meta.read_text())
    except (json.JSONDecodeError, OSError):
        return False

    stat = source.stat()
    if meta.get("mtime") != stat.st_mtime or meta.get("size") != stat.st_size:
        return False

    # If user forced a specific backend, check it matches
    if backend_name:
        toolchain = meta.get("toolchain", [])
        convert_steps = [s for s in toolchain if s.get("step") == "convert"]
        if convert_steps and convert_steps[0].get("backend") != backend_name:
            return False

    return True


def check_hash_index(
    source: Path,
    file_hash: str,
    workspace_root: Path,
    backend_name: str | None = None,
) -> Path | None:
    """Look up content hash in the index. Returns cache .md path if found and valid.

    When *backend_name* is given, validates that the cached conversion used
    that backend (so ``--backend pandoc`` won't reuse a pdftotext cache).
    """
    index = load_index(workspace_root)
    cached_path_str = index.get(file_hash)
    if not cached_path_str:
        return None
    cached_path = Path(cached_path_str)
    if not cached_path.exists():
        return None

    # Validate backend if forced
    if backend_name:
        meta_path = cached_path.with_suffix(".meta")  # .pdf.md -> .pdf.meta
        try:
            meta = json.loads(meta_path.read_text())
            toolchain = meta.get("toolchain", [])
            convert_steps = [s for s in toolchain if s.get("step") == "convert"]
            if convert_steps and convert_steps[0].get("backend") != backend_name:
                return None
        except (json.JSONDecodeError, OSError):
            pass  # Can't verify — allow hit (conversion step will re-validate)

    return cached_path


# ---------------------------------------------------------------------------
# Gitignore management
# ---------------------------------------------------------------------------


def ensure_gitignore_entry(workspace_root: Path) -> None:
    """Append .cache/ to workspace .gitignore if not already present."""
    gitignore = workspace_root / ".gitignore"
    entry = ".cache/"

    if gitignore.exists():
        content = gitignore.read_text()
        for line in content.splitlines():
            stripped = line.strip()
            if stripped in (entry, ".cache"):
                return
        if not content.endswith("\n"):
            content += "\n"
        content += f"{entry}\n"
        gitignore.write_text(content)
    else:
        gitignore.write_text(f"{entry}\n")


# ---------------------------------------------------------------------------
# Main conversion pipeline
# ---------------------------------------------------------------------------


def convert(
    source: Path,
    *,
    workspace_root: Path | None = None,
    limit: int = 200,
    offset: int = 0,
    backend_name: str | None = None,
) -> dict:
    """Convert a document to cached markdown. Returns result dict."""
    source = source.resolve()

    if not source.exists():
        return {"error": f"File not found: {source}"}

    # Determine format
    ext = source.suffix.lower()
    fmt = EXT_TO_FORMAT.get(ext)
    if not fmt:
        supported = ", ".join(sorted(EXT_TO_FORMAT))
        return {"error": f"Unsupported format: {ext}. Supported: {supported}"}

    # Find workspace root
    if workspace_root is None:
        workspace_root = find_workspace_root(source.parent) or Path.cwd()

    # Compute cache paths for this source location
    cache_md, cache_meta = compute_cache_paths(source, workspace_root)

    # Select backend
    available = BACKENDS.get(fmt, [])
    if not available:
        return {"error": f"No backends registered for format: {fmt}"}

    if backend_name:
        selected = [(n, f) for n, f in available if n == backend_name]
        if not selected:
            names = ", ".join(n for n, _ in available)
            return {"error": f"Backend '{backend_name}' not available for {fmt}. Available: {names}"}
        backend_entry = selected[0]
    else:
        backend_entry = available[0]

    actual_backend_name, converter_fn = backend_entry

    # --- Cache lookup ---

    # 1. Path-based check (fast: stat only)
    cached = check_cache(source, cache_md, cache_meta, actual_backend_name)

    # 2. Content-hash fallback (slower: reads file to hash)
    hash_hit_path: Path | None = None
    file_hash: str | None = None
    if not cached:
        file_hash = content_hash(source)
        hash_hit_path = check_hash_index(
            source, file_hash, workspace_root, backend_name=backend_name,
        )
        if hash_hit_path and hash_hit_path != cache_md:
            # Same content exists at a different cache path (file was moved).
            # Copy cached markdown + meta to new location.
            cache_md.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(hash_hit_path, cache_md)
            # Copy the .meta sidecar too
            old_meta = hash_hit_path.with_suffix(".meta")
            if old_meta.exists():
                shutil.copy2(old_meta, cache_meta)
            # Update mtime/size in the new meta to match current source
            _update_meta_stat(cache_meta, source)
            # Update index to point to new location as well
            index = load_index(workspace_root)
            index[file_hash] = str(cache_md)
            save_index(workspace_root, index)
            cached = True

    # --- Conversion (on miss) ---
    if not cached:
        markdown_text: str | None = None
        version_str = ""

        try:
            markdown_text, version_str = converter_fn(source)
        except RuntimeError as exc:
            # Try fallback backends (only if user didn't force)
            if not backend_name:
                for fb_name, fb_fn in available[1:]:
                    try:
                        markdown_text, version_str = fb_fn(source)
                        actual_backend_name = fb_name
                        break
                    except RuntimeError:
                        continue
            if markdown_text is None:
                return {"error": str(exc)}

        # Write cached markdown
        cache_md.parent.mkdir(parents=True, exist_ok=True)
        cache_md.write_text(markdown_text)

        # Compute hash if not already done
        if file_hash is None:
            file_hash = content_hash(source)

        # Write meta sidecar
        stat = source.stat()
        now = datetime.now(timezone.utc).isoformat()
        meta = {
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "content_hash": file_hash,
            "toolchain": [
                {
                    "step": "convert",
                    "backend": actual_backend_name,
                    "version": version_str,
                    "at": now,
                },
            ],
            "converted_at": now,
        }
        cache_meta.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")

        # Update hash index
        index = load_index(workspace_root)
        index[file_hash] = str(cache_md)
        save_index(workspace_root, index)

        # Ensure .cache/ is gitignored
        ensure_gitignore_entry(workspace_root)

    # --- Read and return content ---
    text = cache_md.read_text()
    lines = text.splitlines()
    total_lines = len(lines)
    selected_lines = lines[offset : offset + limit]

    return {
        "cache_path": str(cache_md),
        "total_lines": total_lines,
        "content": "\n".join(selected_lines),
        "source": str(source),
        "format": fmt,
        "backend": actual_backend_name,
        "cached": cached,
    }


def _update_meta_stat(cache_meta: Path, source: Path) -> None:
    """Update mtime and size in an existing .meta sidecar to match source."""
    try:
        meta = json.loads(cache_meta.read_text())
    except (json.JSONDecodeError, OSError):
        return
    stat = source.stat()
    meta["mtime"] = stat.st_mtime
    meta["size"] = stat.st_size
    cache_meta.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert PDF/DOCX/EPUB to cached Markdown.",
    )
    parser.add_argument("file", type=Path, help="Path to document file")
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=None,
        help="Workspace root (auto-detected by walking up to find .claude/ dir)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Max lines to return (default: 200)",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Line offset for chunked reading (default: 0)",
    )
    parser.add_argument(
        "--backend",
        type=str,
        default=None,
        choices=["pandoc", "pdftotext"],
        help="Force a specific conversion backend",
    )

    args = parser.parse_args()

    result = convert(
        args.file,
        workspace_root=args.workspace_root,
        limit=args.limit,
        offset=args.offset,
        backend_name=args.backend,
    )

    json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
