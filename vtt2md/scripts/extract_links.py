#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["yt-dlp"]
# ///
"""Extract labelled links from a YouTube video description.

Reads a yt-dlp info.json (or fetches one from a URL) and parses the
``description`` field for URLs together with their surrounding context to
produce a JSON array of ``{"url": "...", "title": "..."}`` pairs.

Supported patterns (in priority order)::

    Label: https://example.com
    Label - https://example.com
    https://example.com - Label
    Some descriptive sentence https://example.com
    Some descriptive sentence ending with colon:
    https://example.com

When no inline label is found, the non-empty line immediately above the
URL is used as a fallback title.

Usage::

    extract_links.py video.info.json -o links.json
    extract_links.py "https://youtube.com/watch?v=ID" -o links.json
    extract_links.py video.info.json            # stdout
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

import yt_dlp

_URL_RE = re.compile(r"https?://[^\s)>\]]+")
_HTTP_RE = re.compile(r"https?://")

# "Label: URL" or "Label - URL" (label must not start with http)
_LABEL_BEFORE_RE = re.compile(
    r"^(?P<label>[^:\n]{2,80})[\s]*[-:]\s*(?P<url>https?://[^\s)>\]]+)",
)

# "URL - Label" (label after URL)
_LABEL_AFTER_RE = re.compile(
    r"(?P<url>https?://[^\s)>\]]+)\s+[-–—]\s+(?P<label>.{2,80}?)$",
)


def _clean_title(title: str) -> str:
    """Strip whitespace, trailing punctuation, and emoji-heavy prefixes."""
    title = title.strip().rstrip(":")
    title = re.sub(r"^[\U0001f300-\U0001fad6\u2600-\u27bf\ufe00-\ufeff\s]+", "", title)
    return title.strip()


def extract_links(description: str) -> list[dict[str, str]]:
    """Parse links and their titles from a YouTube description string.

    Returns a list of ``{"url": ..., "title": ...}`` dicts.
    Links without any discernible title are included with an empty title.
    """
    if not description:
        return []

    lines = description.splitlines()
    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        # Try "Label: URL" or "Label - URL"
        m = _LABEL_BEFORE_RE.match(stripped)
        if m and not _HTTP_RE.match(m.group("label").strip()):
            url = m.group("url")
            if url not in seen_urls:
                seen_urls.add(url)
                results.append(
                    {"url": url, "title": _clean_title(m.group("label"))}
                )
            continue

        # Try "URL - Label"
        m = _LABEL_AFTER_RE.match(stripped)
        if m:
            url = m.group("url")
            if url not in seen_urls:
                seen_urls.add(url)
                results.append(
                    {"url": url, "title": _clean_title(m.group("label"))}
                )
            continue

        # Line contains URL(s) but no inline label pattern matched
        urls_in_line = _URL_RE.findall(stripped)
        if not urls_in_line:
            continue

        for url in urls_in_line:
            if url in seen_urls:
                continue
            seen_urls.add(url)

            # Text before the URL on the same line
            before = stripped[: stripped.index(url)].strip().rstrip(":-")
            if before and not _HTTP_RE.match(before):
                results.append({"url": url, "title": _clean_title(before)})
                continue

            # Fall back to the preceding non-empty line
            title = ""
            for j in range(i - 1, -1, -1):
                prev = lines[j].strip()
                if prev and not _URL_RE.search(prev):
                    title = _clean_title(prev)
                    break

            results.append({"url": url, "title": title})

    return results


def _is_url(s: str) -> bool:
    return bool(_HTTP_RE.match(s))


def _fetch_info_json(url: str, tmpdir: Path) -> dict:
    opts = {
        "skip_download": True,
        "writeinfojson": True,
        "outtmpl": str(tmpdir / "%(id)s"),
        "quiet": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    json_files = sorted(tmpdir.glob("*.info.json"))
    if not json_files:
        print("Error: yt-dlp produced no .info.json files", file=sys.stderr)
        sys.exit(1)
    return json.loads(json_files[0].read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract labelled links from a YouTube video description.",
    )
    parser.add_argument(
        "input",
        help="yt-dlp .info.json file OR YouTube URL",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output .json file (default: stdout)",
    )
    args = parser.parse_args()

    if _is_url(args.input):
        with tempfile.TemporaryDirectory(prefix="extract_links_") as td:
            info = _fetch_info_json(args.input, Path(td))
    else:
        info_path = Path(args.input)
        if not info_path.exists():
            print(f"Error: {info_path} not found", file=sys.stderr)
            sys.exit(1)
        info = json.loads(info_path.read_text(encoding="utf-8"))

    description = info.get("description", "")
    links = extract_links(description)

    output_json = json.dumps(links, indent=2, ensure_ascii=False) + "\n"

    if args.output:
        args.output.write_text(output_json, encoding="utf-8")
        print(
            f"Wrote {len(links)} links to {args.output}",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(output_json)


if __name__ == "__main__":
    main()
