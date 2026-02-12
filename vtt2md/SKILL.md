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

## Step 3: Enrich with description links (optional)

YouTube video descriptions often contain links to resources mentioned in the
video. This step extracts those links and turns matching phrases in the
transcript into hyperlinks.

### Extract links from the description

```bash
uv run ~/.claude/skills/vtt2md/scripts/extract_links.py video.info.json -o raw_links.json

# Or directly from a YouTube URL (fetches info.json automatically)
uv run ~/.claude/skills/vtt2md/scripts/extract_links.py "https://youtube.com/watch?v=ID" -o raw_links.json
```

Output is a JSON array of `{"url": "...", "title": "..."}` pairs, where
`title` is the label text found near the URL in the description.

### Generate a link map (LLM step)

The extracted titles are raw description labels — often full sentences or
generic words like "Website". Read both `raw_links.json` and the structured
transcript, then produce a **link map** JSON: an array of
`{"phrase": "...", "url": "..."}` objects where each `phrase` is a short
term that actually appears in the transcript text.

#### Prompt template for generating the link map

> You are given two inputs:
>
> 1. A **Markdown transcript** of a video.
> 2. A **raw links JSON** extracted from the video description — an array of
>    `{"url": "...", "title": "..."}` objects.
>
> Output **only** a JSON array (no other text) of objects with this shape:
>
> ```json
> [
>   {"phrase": "exact words from the transcript", "url": "https://..."}
> ]
> ```
>
> **Rules:**
> - Each `phrase` must be a substring that appears verbatim in the transcript
>   (case-insensitive match is fine).
> - Prefer short, specific phrases (1–4 words) over full sentences.
> - Skip social media links, subscribe links, and other non-content URLs.
> - Skip links that have no related mention in the transcript.
> - If multiple transcript phrases relate to the same URL, include the most
>   specific one.

### Apply the link map

```bash
uv run ~/.claude/skills/vtt2md/scripts/enrich_links.py structured.md \
  --links link_map.json -o enriched.md
```

The script replaces the first occurrence of each phrase with a Markdown
hyperlink. It skips headings, existing links, and `[M:SS]` timestamps.
Longer phrases are matched first to avoid partial overlaps.

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
