---
name: vtt2md
description: Convert YouTube video subtitles to readable Markdown with timestamps. Use when the user asks to "convert YouTube video to markdown", "transcribe a YouTube video", "get transcript from YouTube URL", or asks to turn subtitles/captions into readable text. Accepts YouTube URLs.
---

# VTT to Markdown

Convert YouTube auto-generated VTT subtitles into clean, readable Markdown with `[M:SS]` timestamps at sentence boundaries and paragraph breaks at natural pauses.

## Step 1: Download and convert

```bash
uv run ~/.claude/skills/vtt2md/scripts/vtt2md.py "https://youtube.com/watch?v=VIDEO_ID" -o transcript.md
```

This downloads subtitles and video metadata from YouTube in a single call, then writes sentence-per-line Markdown to the `-o` file. If the video has chapter markers, `## Title` headings are inserted automatically.

**Stdout output** (for LLM consumption):

```
TITLE: Video Title Here
VIDEO_ID: dQw4w9WgXcQ
CHAPTERS: yes
---
Description text here...
```

`CHAPTERS: yes` or `CHAPTERS: no` indicates whether chapter headings were embedded. The `---` separator and description are only printed when the description is non-empty.

**Options:**

- `--lang fi` — subtitle language (default: `en`)
- `--pause 3.0` — pause duration in seconds to trigger paragraph break (default: `2.0`)
- `--no-timestamps` — omit `[M:SS]` timestamp markers

## Step 2: Generate combined hints (LLM step)

Read the transcript file and the stdout output from step 1, then generate a single JSON object with all applicable keys.

#### Prompt template

> You are given two inputs:
>
> 1. A **sentence-per-line Markdown transcript** of a YouTube video (each sentence
>    prefixed with `[M:SS]` timestamp). It may contain `##` chapter headings.
> 2. The **video description** text (which may contain URLs to resources).
>
> Output **only** a JSON object (no other text) with this structure:
>
> ```json
> {
>   "title": "A concise, accurate title for this video",
>   "sections": [
>     {"line": <N>, "title": "Section title"}
>   ],
>   "paragraphs": [<line>, <line>, ...],
>   "links": [
>     {"phrase": "exact words from the transcript", "url": "https://..."}
>   ]
> }
> ```
>
> **Rules for each key (all keys are optional — include only what's needed):**
>
> `title`: Adapt the video topic into a clear, human-readable title.
>
> `sections`: Insert a `##` heading before line N wherever the topic changes
> significantly. Use short, descriptive titles. **Omit entirely** if the
> transcript already contains `##` chapter headings.
>
> `paragraphs`: Insert a paragraph break before line N wherever it helps
> readability — group logically related sentences. A section heading already
> implies a paragraph break, so don't duplicate. Line numbers are 1-based
> and refer to the input file.
>
> `links`: Match URLs from the video description to short phrases (1–4 words)
> that appear verbatim in the transcript. Skip social media, subscribe, and
> non-content URLs. Skip URLs with no related mention in the transcript.
> If multiple phrases relate to the same URL, pick the most specific one.

## Step 3: Apply structure and links

```bash
uv run ~/.claude/skills/vtt2md/scripts/apply_structure.py transcript.md \
  --hints hints.json --video-id VIDEO_ID -o final.md
```

This applies all structure from the hints JSON (title, sections, paragraphs), enriches matching phrases with hyperlinks, converts `[M:SS]` timestamps to clickable YouTube links (when `--video-id` is provided), writes the final Markdown to `-o`, and **deletes the intermediate transcript file**.

## Requirements

- `webvtt-py` — auto-installed by PEP 723 inline metadata
- `yt-dlp` — must be available (auto-installed by PEP 723 inline metadata, or via `uvx yt-dlp` / system package)

## How it works

YouTube auto-generated VTT files contain word-level timestamps in inline `<HH:MM:SS.mmm><c> word</c>` tags. The `vtt2md.py` script:

1. Parses these into a `(timestamp, word)` stream using `webvtt-py`
2. Detects sentence boundaries (`.` `!` `?`)
3. Inserts `[M:SS]` at the start of each sentence
4. Maps chapter markers from `info.json` to sentence timestamps for `##` headings
5. Outputs one sentence per line, with paragraph breaks at natural pauses
