#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Apply structure hints to sentence-per-line Markdown transcript.

Takes a sentence-per-line Markdown file (from vtt2md.py) and applies:
- A top-level title heading
- Section headings (from yt-dlp chapters or LLM-generated hints)
- Paragraph breaks (from LLM-generated hints)
- Strips mid-paragraph timestamps, keeping only the first

Hints JSON format (from LLM):
    {
      "title": "Video Title Here",
      "sections": [
        {"line": 6, "title": "Hardware Setup"},
        {"line": 16, "title": "System Overview"}
      ],
      "paragraphs": [5, 15, 25, 30]
    }

- "title": becomes the # heading at the top
- "sections": ## headings inserted before the given line number
- "paragraphs": blank-line paragraph breaks inserted before the given line

When --info-json is provided, chapters from yt-dlp override "sections" from
the hints file, and the video title is used if "title" is absent from hints.

Usage:
    apply_structure.py transcript.md --hints hints.json -o output.md
    apply_structure.py transcript.md --info-json v.info.json --hints hints.json
    apply_structure.py transcript.md --hints hints.json   # stdout
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_TIMESTAMP_RE = re.compile(r"^\[(\d+):(\d{2})\]\s*")


def _parse_line_timestamp(line: str) -> int | None:
    """Extract timestamp in total seconds from '[M:SS] ...' prefix."""
    m = _TIMESTAMP_RE.match(line)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    return None


def _strip_timestamp(line: str) -> str:
    """Remove the [M:SS] prefix from a line."""
    return _TIMESTAMP_RE.sub("", line)


def _chapters_to_sections(
    chapters: list[dict],
    lines: list[str],
) -> dict[int, str]:
    """Map yt-dlp chapter start_time values to line numbers.

    For each chapter, finds the first line whose [M:SS] timestamp is
    >= the chapter's start_time (in seconds).  Returns {line_no: title}.
    """
    line_ts: list[tuple[int, int]] = []
    for i, line in enumerate(lines, 1):
        ts = _parse_line_timestamp(line)
        if ts is not None:
            line_ts.append((i, ts))

    sections: dict[int, str] = {}
    for ch in chapters:
        start = int(ch.get("start_time", 0))
        title = ch.get("title", "")
        if not title:
            continue
        for line_no, ts in line_ts:
            if ts >= start:
                sections[line_no] = title
                break
    return sections


def apply_structure(
    lines: list[str],
    hints: dict,
    chapters: list[dict] | None = None,
) -> str:
    """Apply headings, paragraph breaks, and timestamp cleanup.

    Args:
        lines: Raw lines from the sentence-per-line markdown (no newlines).
        hints: Parsed hints dict (title, sections, paragraphs).
        chapters: Optional yt-dlp chapters list (overrides hints sections).

    Returns:
        Fully structured Markdown string.
    """
    title: str = hints.get("title", "")

    if chapters:
        sections = _chapters_to_sections(chapters, lines)
    else:
        sections = {s["line"]: s["title"] for s in hints.get("sections", [])}

    section_lines = set(sections.keys())
    paragraph_breaks = set(hints.get("paragraphs", []))

    out: list[str] = []
    para: list[str] = []

    def _flush_para() -> None:
        if para:
            out.append(" ".join(para))
            para.clear()

    if title:
        out.append(f"# {title}")
        out.append("")

    for i, line in enumerate(lines, 1):
        line = line.rstrip()
        if not line:
            continue

        if i in section_lines:
            _flush_para()
            if out and out[-1] != "":
                out.append("")
            out.append(f"## {sections[i]}")
            out.append("")
        elif i in paragraph_breaks:
            _flush_para()
            if out and out[-1] != "":
                out.append("")

        if para:
            line = _strip_timestamp(line)

        para.append(line)

    _flush_para()

    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Apply structure hints to sentence-per-line Markdown.",
    )
    ap.add_argument("input", type=Path, help="Sentence-per-line .md file")
    ap.add_argument(
        "--hints",
        type=Path,
        default=None,
        help="LLM-generated hints JSON file",
    )
    ap.add_argument(
        "--info-json",
        type=Path,
        default=None,
        help="yt-dlp .info.json for chapters & video title",
    )
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output .md file (default: stdout)",
    )
    args = ap.parse_args()

    lines = args.input.read_text(encoding="utf-8").splitlines()

    hints: dict = {}
    if args.hints:
        hints = json.loads(args.hints.read_text(encoding="utf-8"))

    chapters: list[dict] | None = None
    if args.info_json:
        info = json.loads(args.info_json.read_text(encoding="utf-8"))
        chapters = info.get("chapters") or None
        if not hints.get("title") and info.get("title"):
            hints.setdefault("title", info["title"])

    if not hints and chapters is None:
        print(
            "Error: provide at least --hints or --info-json",
            file=sys.stderr,
        )
        sys.exit(1)

    result = apply_structure(lines, hints, chapters)

    if args.output:
        args.output.write_text(result, encoding="utf-8")
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(result)


if __name__ == "__main__":
    main()
