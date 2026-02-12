#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["webvtt-py", "yt-dlp"]
# ///
"""Convert YouTube VTT subtitles to clean Markdown with timestamps.

Downloads subtitles and metadata from a YouTube URL, parses word-level
timestamps, detects sentences, and writes sentence-per-line Markdown with
optional chapter headings.

Usage:
    vtt2md.py "https://youtube.com/watch?v=ID" -o transcript.md
    vtt2md.py URL -o out.md --pause 3.0
    vtt2md.py URL -o out.md --no-timestamps
    vtt2md.py URL -o out.md --lang fi
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

import webvtt
import yt_dlp


# <HH:MM:SS.mmm><c> word</c> groups in YouTube VTT raw_text
_WORD_TAG_RE = re.compile(r"<(\d{2}:\d{2}:\d{2}\.\d{3})><c>\s*(.*?)</c>")

# Leading word on a rolling cue's second line (before the first timestamp tag)
_LEADING_WORD_RE = re.compile(r"^([^\n<]+?)(?=<\d{2}:\d{2}:\d{2}\.\d{3}>)")


def _ts_to_seconds(ts: str) -> float:
    parts = ts.split(":")
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])


def _seconds_to_mmss(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def _parse_rolling_cue(cue_start: str, raw: str) -> list[tuple[float, str]]:
    """Extract (timestamp_seconds, word) pairs from a rolling cue's raw_text.

    A rolling cue has two lines:
      Line 1: plain text (previous words, already handled)
      Line 2: leading_word<TS><c> word2</c><TS><c> word3</c>...

    The leading word on line 2 gets the cue start timestamp.
    Subsequent words get their inline timestamps.
    """
    lines = raw.split("\n")
    if len(lines) < 2:
        return []

    second_line = lines[1]
    words: list[tuple[float, str]] = []

    # Leading word (before first <timestamp>)
    lead = _LEADING_WORD_RE.match(second_line)
    if lead:
        word = lead.group(1).strip()
        if word:
            words.append((_ts_to_seconds(cue_start), word))

    # Tagged words
    for m in _WORD_TAG_RE.finditer(second_line):
        ts = m.group(1)
        word = m.group(2).strip()
        if word:
            words.append((_ts_to_seconds(ts), word))

    return words


def parse_vtt(path: str | Path) -> list[tuple[float, str]]:
    """Parse a YouTube VTT file into a deduplicated stream of (seconds, word).

    Only processes the 2-line rolling cues (which contain inline timestamps).
    Deduplicates by keeping the *last* occurrence of each word at a given time,
    since rolling cues repeat the previous line.
    """
    all_words: list[tuple[float, str]] = []
    seen: set[tuple[float, str]] = set()

    for caption in webvtt.read(str(path)):
        raw = caption.raw_text
        # Only process cues with inline timing tags (the rolling cues)
        if "<c>" not in raw:
            continue
        pairs = _parse_rolling_cue(caption.start, raw)
        for pair in pairs:
            if pair not in seen:
                seen.add(pair)
                all_words.append(pair)

    all_words.sort(key=lambda x: x[0])
    return all_words


# ---------------------------------------------------------------------------
# Sentence detection and Markdown formatting
# ---------------------------------------------------------------------------

_SENTENCE_END_RE = re.compile(r"[.!?][\"'\u2019\u201D)]*$")


def words_to_sentences(
    words: list[tuple[float, str]],
    *,
    pause_threshold: float = 2.0,
    timestamps: bool = True,
) -> list[tuple[float | None, str]]:
    """Convert (seconds, word) stream to structured sentences.

    Returns a list of ``(sentence_start_seconds, formatted_text)`` tuples.
    Paragraph breaks (long pauses) are represented as ``(None, "")`` entries.
    Sentence text includes a ``[M:SS]`` prefix when *timestamps* is True.
    """
    if not words:
        return []

    result: list[tuple[float | None, str]] = []
    current_sentence_words: list[str] = []
    prev_ts = words[0][0]
    pending_ts: float | None = words[0][0]

    for ts, word in words:
        gap = ts - prev_ts

        # Detect paragraph break (long pause)
        if gap > pause_threshold and (current_sentence_words or result):
            # Flush current sentence
            if current_sentence_words:
                sentence = " ".join(current_sentence_words)
                if timestamps and pending_ts is not None:
                    sentence = f"[{_seconds_to_mmss(pending_ts)}] {sentence}"
                result.append((pending_ts, sentence))
                current_sentence_words = []

            # Insert paragraph break
            result.append((None, ""))
            pending_ts = ts

        # Add word to current sentence
        current_sentence_words.append(word)
        prev_ts = ts

        # Detect sentence end
        if _SENTENCE_END_RE.search(word):
            sentence = " ".join(current_sentence_words)
            if timestamps and pending_ts is not None:
                sentence = f"[{_seconds_to_mmss(pending_ts)}] {sentence}"
            result.append((pending_ts, sentence))
            current_sentence_words = []
            pending_ts = None

        # Track start of next sentence
        if pending_ts is None and not current_sentence_words:
            pass  # will be set when next word arrives
        elif pending_ts is None and current_sentence_words:
            pending_ts = ts  # already started

    # Flush remaining
    if current_sentence_words:
        sentence = " ".join(current_sentence_words)
        if timestamps and pending_ts is not None:
            sentence = f"[{_seconds_to_mmss(pending_ts)}] {sentence}"
        result.append((pending_ts, sentence))

    return result


def format_markdown(
    sentences: list[tuple[float | None, str]],
    chapters: list[dict] | None = None,
) -> str:
    """Format sentences into Markdown with optional chapter headings.

    *chapters* is a list of ``{"start_time": float, "title": str}`` dicts
    (from yt-dlp info.json).  A ``## Title`` heading is inserted before the
    first sentence whose timestamp >= the chapter's start_time.
    """
    chapter_queue: list[dict] = []
    if chapters:
        chapter_queue = sorted(chapters, key=lambda c: c.get("start_time", 0))

    out_lines: list[str] = []

    for start_ts, text in sentences:
        # Paragraph break
        if start_ts is None and text == "":
            # Avoid duplicate blank lines
            if out_lines and out_lines[-1] != "":
                out_lines.append("")
            continue

        # Insert chapter headings whose start_time <= this sentence's timestamp
        while chapter_queue and start_ts is not None:
            ch_start = chapter_queue[0].get("start_time", 0)
            ch_title = chapter_queue[0].get("title", "")
            if start_ts >= ch_start and ch_title:
                chapter_queue.pop(0)
                if out_lines and out_lines[-1] != "":
                    out_lines.append("")
                out_lines.append(f"## {ch_title}")
                out_lines.append("")
            else:
                break

        out_lines.append(text)

    # Clean trailing blank lines
    while out_lines and out_lines[-1] == "":
        out_lines.pop()

    return "\n".join(out_lines) + "\n"


# ---------------------------------------------------------------------------
# YouTube download
# ---------------------------------------------------------------------------


def _download_youtube(
    url: str,
    lang: str,
    tmpdir: Path,
) -> tuple[Path, dict]:
    """Download VTT subtitles and info.json from YouTube in a single call.

    Returns ``(vtt_path, info_dict)``.
    """
    opts = {
        "writeautomaticsub": True,
        "subtitleslangs": [lang],
        "subtitlesformat": "vtt",
        "writeinfojson": True,
        "skip_download": True,
        "outtmpl": str(tmpdir / "%(id)s"),
        "quiet": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    vtt_files = sorted(tmpdir.glob("*.vtt"))
    if not vtt_files:
        print("Error: yt-dlp produced no .vtt files", file=sys.stderr)
        sys.exit(1)

    json_files = sorted(tmpdir.glob("*.info.json"))
    if not json_files:
        print("Error: yt-dlp produced no .info.json files", file=sys.stderr)
        sys.exit(1)

    info = json.loads(json_files[0].read_text(encoding="utf-8"))
    return vtt_files[0], info


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert YouTube VTT subtitles to clean Markdown.",
    )
    parser.add_argument(
        "url",
        help="YouTube URL",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="Output .md file",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=2.0,
        help="Pause duration (seconds) to trigger paragraph break (default: 2.0)",
    )
    parser.add_argument(
        "--no-timestamps",
        action="store_true",
        help="Omit [MM:SS] timestamp markers",
    )
    parser.add_argument(
        "--lang",
        default="en",
        help="Subtitle language for YouTube downloads (default: en)",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="vtt2md_") as td:
        tmpdir = Path(td)
        vtt_path, info = _download_youtube(args.url, args.lang, tmpdir)
        words = parse_vtt(vtt_path)

    if not words:
        print("Warning: no word-level timestamps found in VTT", file=sys.stderr)

    sentences = words_to_sentences(
        words,
        pause_threshold=args.pause,
        timestamps=not args.no_timestamps,
    )

    chapters = info.get("chapters") or None
    md = format_markdown(sentences, chapters)

    args.output.write_text(md, encoding="utf-8")
    print(f"Wrote {args.output}", file=sys.stderr)

    # Print metadata to stdout for LLM consumption
    title = info.get("title", "")
    description = info.get("description", "")
    has_chapters = "yes" if chapters else "no"

    print(f"TITLE: {title}")
    print(f"CHAPTERS: {has_chapters}")
    if description:
        print("---")
        print(description)


if __name__ == "__main__":
    main()
