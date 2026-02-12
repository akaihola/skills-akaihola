#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Apply structure and hyperlinks to a sentence-per-line Markdown transcript.

Takes a sentence-per-line Markdown file (from vtt2md.py) and a combined hints
JSON, then applies title, section headings, paragraph breaks, timestamp
cleanup, and hyperlink enrichment.

Combined hints JSON format:
    {
      "title": "Video Title Here",
      "sections": [{"line": 6, "title": "Hardware Setup"}],
      "paragraphs": [5, 15, 25],
      "links": [{"phrase": "neural networks", "url": "https://example.com/nn"}]
    }

Usage:
    apply_structure.py transcript.md --hints hints.json -o final.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_TIMESTAMP_RE = re.compile(r"^\[(\d+):(\d{2})\]\s*")

# Matches existing Markdown links [text](url) and timestamp markers [M:SS]
_MD_LINK_OR_TS_RE = re.compile(
    r"\[([^\]]*)\]\([^)]+\)"  # [text](url)
    r"|\[\d+:\d{2}\]"  # [M:SS]
)


def _strip_timestamp(line: str) -> str:
    return _TIMESTAMP_RE.sub("", line)


def _is_heading(line: str) -> bool:
    return line.startswith("#")


def apply_structure(lines: list[str], hints: dict) -> str:
    """Apply title, section headings, paragraph breaks, and timestamp cleanup."""
    title: str = hints.get("title", "")
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
        stripped = line.rstrip()
        if not stripped:
            continue

        # Preserve existing headings as-is
        if stripped.startswith("#"):
            _flush_para()
            if out and out[-1] != "":
                out.append("")
            out.append(stripped)
            out.append("")
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
            stripped = _strip_timestamp(stripped)

        para.append(stripped)

    _flush_para()

    return "\n".join(out) + "\n"


def _replace_first(
    text: str,
    phrase: str,
    url: str,
) -> tuple[str, bool]:
    """Replace first case-insensitive *phrase* with a Markdown link,
    skipping protected spans (existing links, timestamps).
    """
    pattern = re.compile(re.escape(phrase), re.IGNORECASE)

    protected: list[tuple[int, int]] = []
    for m in _MD_LINK_OR_TS_RE.finditer(text):
        protected.append((m.start(), m.end()))

    def _in_protected(start: int, end: int) -> bool:
        return any(ps <= start < pe or ps < end <= pe for ps, pe in protected)

    for m in pattern.finditer(text):
        if not _in_protected(m.start(), m.end()):
            matched_text = m.group()
            replacement = f"[{matched_text}]({url})"
            return text[: m.start()] + replacement + text[m.end() :], True

    return text, False


def enrich_links(markdown: str, link_map: list[dict[str, str]]) -> str:
    """Replace first occurrence of each phrase with a Markdown hyperlink.

    Phrases are processed longest-first.  Headings, existing links, and
    ``[M:SS]`` timestamps are skipped.
    """
    sorted_map = sorted(link_map, key=lambda e: -len(e["phrase"]))

    lines = markdown.splitlines(keepends=True)
    used_phrases: set[str] = set()

    for entry in sorted_map:
        phrase = entry["phrase"]
        url = entry["url"]
        phrase_lower = phrase.lower()

        if phrase_lower in used_phrases:
            continue

        for i, line in enumerate(lines):
            if _is_heading(line):
                continue

            new_line, replaced = _replace_first(line, phrase, url)
            if replaced:
                lines[i] = new_line
                used_phrases.add(phrase_lower)
                break

    return "".join(lines)


def linkify_timestamps(
    markdown: str,
    video_id: str,
    separator: str = "\u25b8",
) -> str:
    """Convert ``[M:SS]`` timestamp prefixes to YouTube timestamp links.

    Replaces ``[M:SS] text`` with ``[M:SS](https://youtu.be/ID?t=Ns) ▸ text``
    at the start of each line.  The rendered Markdown shows the timestamp as
    a clickable link without square brackets, followed by the separator.
    """
    ts_re = re.compile(r"^\[(\d+):(\d{2})\]\s*", re.MULTILINE)

    def _replace(m: re.Match) -> str:
        minutes = int(m.group(1))
        seconds = int(m.group(2))
        total = minutes * 60 + seconds
        ts_text = f"{minutes}:{seconds:02d}"
        url = f"https://youtu.be/{video_id}?t={total}"
        return f"[{ts_text}]({url}) {separator} "

    return ts_re.sub(_replace, markdown)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Apply structure and links to sentence-per-line Markdown.",
    )
    ap.add_argument("input", type=Path, help="Sentence-per-line .md file")
    ap.add_argument(
        "--hints",
        type=Path,
        required=True,
        help="Combined hints JSON file",
    )
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="Output .md file",
    )
    ap.add_argument(
        "--video-id",
        default=None,
        help="YouTube video ID for timestamp links (e.g. Q7r--i9lLck)",
    )
    args = ap.parse_args()

    input_path: Path = args.input
    output_path: Path = args.output

    lines = input_path.read_text(encoding="utf-8").splitlines()
    hints: dict = json.loads(args.hints.read_text(encoding="utf-8"))

    result = apply_structure(lines, hints)

    link_map = hints.get("links", [])
    if link_map:
        result = enrich_links(result, link_map)

    if args.video_id:
        result = linkify_timestamps(result, args.video_id)

    output_path.write_text(result, encoding="utf-8")
    print(f"Wrote {output_path}", file=sys.stderr)

    if input_path.resolve() != output_path.resolve():
        input_path.unlink()
        print(f"Deleted {input_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
