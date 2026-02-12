---
name: vtt2md
description: Convert YouTube video subtitles to readable Markdown with second-accurate timestamps at sentence boundaries. Use when the user asks to "convert VTT to markdown", "transcribe a YouTube video", "get transcript from YouTube URL", provides a .vtt file to convert, or asks to turn subtitles/captions into readable text. Accepts both local .vtt files and YouTube URLs.
---

# VTT to Markdown

Convert YouTube auto-generated VTT subtitles into clean, readable Markdown with `[M:SS]` timestamps between sentences and paragraph breaks at natural pauses.

## Step 1: Convert VTT to sentence-per-line Markdown

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

## Step 2: Add structure (headings and paragraphs)

The sentence-per-line output from step 1 needs structure: a title, section
headings, and paragraph breaks. Two sources of structure are supported:

- **yt-dlp chapters** (`--info-json`): section headings from YouTube chapter
  markers (preferred when available)
- **LLM hints** (`--hints`): a compact JSON with paragraph breaks and
  optionally section headings when chapters are missing

### Get chapters from YouTube (when available)

```bash
yt-dlp --dump-json "https://youtube.com/watch?v=VIDEO_ID" > video.info.json
```

Chapters live in `.chapters[]` as `{start_time, end_time, title}`.

### Generate LLM hints

Read the sentence-per-line Markdown file, then output a JSON object with the
format below. **Each key is optional** — provide only what's needed.

```json
{
  "title": "Video Title Here",
  "sections": [
    {"line": 6, "title": "Hardware Setup"},
    {"line": 16, "title": "System Overview"}
  ],
  "paragraphs": [5, 15, 25, 30]
}
```

| Key          | Meaning                                                     |
|--------------|-------------------------------------------------------------|
| `title`      | Becomes the `#` heading at the top of the document          |
| `sections[]` | `##` headings inserted **before** the given line number     |
| `paragraphs` | Blank-line paragraph breaks inserted **before** the line    |

When `--info-json` is also provided, its chapters override `sections` from
hints, and the video title is used if `title` is absent from hints.

#### Prompt template for generating hints

> You are reading a transcript that has one sentence per line, each prefixed
> with a `[M:SS]` timestamp. Output **only** a JSON object (no other text)
> with the following structure:
>
> ```json
> {
>   "title": "A concise, accurate title for this video",
>   "sections": [
>     {"line": <N>, "title": "Section title"}
>   ],
>   "paragraphs": [<line>, <line>, ...]
> }
> ```
>
> **Rules:**
> - `"title"`: adapt the topic into a clear, human-readable title.
> - `"sections"`: insert a section heading **before** line N wherever the
>   topic changes significantly. Use short, descriptive titles.
> - `"paragraphs"`: insert a paragraph break **before** line N wherever it
>   helps readability — group logically related sentences together.
>   A section heading already implies a paragraph break, so don't duplicate.
> - Omit `"sections"` entirely if chapter headings will come from yt-dlp.
> - Line numbers are 1-based and refer to the input file.

### Apply structure

```bash
# Chapters + LLM paragraph breaks
uv run ~/.claude/skills/vtt2md/scripts/apply_structure.py transcript.md \
  --info-json video.info.json --hints hints.json -o structured.md

# LLM hints only (no chapters available)
uv run ~/.claude/skills/vtt2md/scripts/apply_structure.py transcript.md \
  --hints hints.json -o structured.md
```

The script:
1. Inserts `#` title and `##` section headings at the mapped line numbers
2. Inserts blank-line paragraph breaks
3. Strips `[M:SS]` timestamps from all lines except the first in each paragraph

## Requirements

- `webvtt-py` is auto-installed by the PEP 723 inline metadata
- `yt-dlp` must be installed for YouTube URL mode (available via `uvx yt-dlp`
  or system package)

## How it works

YouTube auto-generated VTT files contain word-level timestamps in inline
`<HH:MM:SS.mmm><c> word</c>` tags. The `vtt2md.py` script:

1. Parses these into a `(timestamp, word)` stream using `webvtt-py`
2. Detects sentence boundaries (`.` `!` `?`)
3. Inserts `[M:SS]` at the start of each sentence
4. Outputs one sentence per line, with paragraph breaks at natural pauses
