#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Enrich a Markdown transcript by turning phrases into hyperlinks.

Reads a structured Markdown file and a link-mapping JSON, then replaces
matching phrases with Markdown hyperlinks.

The link-mapping JSON is an array of objects::

    [
      {"phrase": "neural networks", "url": "https://example.com/nn"},
      {"phrase": "Michael Nielsen", "url": "https://goo.gl/Zmczdy"}
    ]

Each ``phrase`` is matched case-insensitively in the transcript.  Only
the **first** occurrence of each phrase is linked.  Phrases inside
existing Markdown links, headings, and ``[M:SS]`` timestamps are not
touched.

Usage::

    enrich_links.py transcript.md --links link_map.json -o enriched.md
    enrich_links.py transcript.md --links link_map.json   # stdout
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Matches existing Markdown links [text](url) and timestamp markers [M:SS]
_MD_LINK_OR_TS_RE = re.compile(
    r"\[([^\]]*)\]\([^)]+\)"  # [text](url)
    r"|\[\d+:\d{2}\]"  # [M:SS]
)


def _is_heading(line: str) -> bool:
    return line.startswith("#")


def _replace_first(
    text: str,
    phrase: str,
    url: str,
) -> tuple[str, bool]:
    """Replace the first case-insensitive occurrence of *phrase* in *text*
    with a Markdown link, skipping protected spans (existing links, timestamps).

    Returns (new_text, was_replaced).
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


def enrich(markdown: str, link_map: list[dict[str, str]]) -> str:
    """Apply link_map phrases to the Markdown text.

    Processes phrases longest-first to prefer specific matches over
    substrings.  Each phrase is linked at most once (first occurrence).
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich Markdown transcript with hyperlinks.",
    )
    parser.add_argument("input", type=Path, help="Structured .md file")
    parser.add_argument(
        "--links",
        type=Path,
        required=True,
        help=(
            "JSON file with link mapping: "
            '[{"phrase": "...", "url": "..."}, ...]'
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output .md file (default: stdout)",
    )
    args = parser.parse_args()

    markdown = args.input.read_text(encoding="utf-8")
    link_map = json.loads(args.links.read_text(encoding="utf-8"))

    result = enrich(markdown, link_map)

    if args.output:
        args.output.write_text(result, encoding="utf-8")
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(result)


if __name__ == "__main__":
    main()
