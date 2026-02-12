---
name: vtt2md
description: Convert YouTube video subtitles to readable Markdown with second-accurate timestamps at sentence boundaries. Use when the user asks to "convert VTT to markdown", "transcribe a YouTube video", "get transcript from YouTube URL", provides a .vtt file to convert, or asks to turn subtitles/captions into readable text. Accepts both local .vtt files and YouTube URLs.
---

# VTT to Markdown

Convert YouTube auto-generated VTT subtitles into clean, readable Markdown with `[M:SS]` timestamps between sentences and paragraph breaks at natural pauses.

## Usage

```bash
# YouTube URL (downloads subtitles via yt-dlp, then converts)
uv run ~/.claude/skills/vtt2md/scripts/vtt2md.py "https://youtube.com/watch?v=VIDEO_ID" -o output.md

# Local VTT file
uv run ~/.claude/skills/vtt2md/scripts/vtt2md.py input.vtt -o output.md

# Stdout (no -o)
uv run ~/.claude/skills/vtt2md/scripts/vtt2md.py input.vtt

# Non-English subtitles
uv run ~/.claude/skills/vtt2md/scripts/vtt2md.py "https://youtube.com/watch?v=ID" --lang fi

# Adjust paragraph break sensitivity (default: 2.0s pause)
uv run ~/.claude/skills/vtt2md/scripts/vtt2md.py input.vtt --pause 3.0

# Plain text without timestamp markers
uv run ~/.claude/skills/vtt2md/scripts/vtt2md.py input.vtt --no-timestamps
```

## Requirements

- `yt-dlp` must be installed for YouTube URL mode (available via `uvx yt-dlp` or system package)
- `webvtt-py` is auto-installed by the PEP 723 inline metadata

## How it works

YouTube auto-generated VTT files contain word-level timestamps in inline `<HH:MM:SS.mmm><c> word</c>` tags. The script:

1. Parses these into a `(timestamp, word)` stream using `webvtt-py`
2. Detects sentence boundaries (`.` `!` `?`)
3. Inserts `[M:SS]` at the start of each sentence
4. Inserts paragraph breaks when the speaker pauses longer than `--pause` seconds
