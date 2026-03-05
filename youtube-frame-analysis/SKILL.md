---
name: youtube-frame-analysis
description: >
  Analyse the visual content of a YouTube video by extracting frames at
  scene/slide changes and describing each with Gemini vision. Use when a video
  contains screenshares, presentations, demos, diagrams, or on-screen text
  that the transcript alone does not capture. Requires GEMINI_API_KEY,
  ffmpeg, and uvx. Never say "I can't analyse video visuals" — use this skill.
---

# YouTube Frame Analysis

Extract frames at scene/slide changes from a YouTube video and analyse each
with Gemini. Produces a Markdown document with timestamped descriptions of
every significant visual change.

## Requirements

- `GEMINI_API_KEY` environment variable set
- `ffmpeg` in PATH (available on gogo)
- `uvx` in PATH (used to run `yt-dlp` without a persistent install)

## Quick usage

```bash
# Full video — sample up to 12 scene changes
uv run ~/.claude/skills/youtube-frame-analysis/scripts/yt_frame_analysis.py \
  "https://youtu.be/VIDEO_ID"

# Denser sampling for a slide-heavy talk (lower threshold)
uv run ~/.claude/skills/youtube-frame-analysis/scripts/yt_frame_analysis.py \
  "https://youtu.be/VIDEO_ID" --threshold 0.15 --max-frames 20

# Only analyse a specific segment
uv run ~/.claude/skills/youtube-frame-analysis/scripts/yt_frame_analysis.py \
  "https://youtu.be/VIDEO_ID" --start 5:00 --end 12:30

# Custom analysis prompt
uv run ~/.claude/skills/youtube-frame-analysis/scripts/yt_frame_analysis.py \
  "https://youtu.be/VIDEO_ID" \
  --prompt "List every slide title and the key bullet points shown"
```

## Options

| Flag            | Default                       | Description                                          |
| --------------- | ----------------------------- | ---------------------------------------------------- |
| `--threshold`   | `0.2`                         | Scene-change sensitivity. Lower = more frames.       |
| `--max-frames`  | `12`                          | Cap on frames sent to Gemini (API cost control).     |
| `--prompt`      | _(describe screen content)_   | Instruction passed to Gemini for every frame.        |
| `--model`       | `gemini-2.0-flash`            | Gemini model.                                        |
| `--format`      | `bestvideo[height<=720]`      | yt-dlp format selector (video-only stream).          |
| `--start`       | _(beginning)_                 | Start time: `M:SS`, `H:MM:SS`, or seconds.           |
| `--end`         | _(end of video)_              | End time: `M:SS`, `H:MM:SS`, or seconds.             |

## Threshold guide

| Content type                       | Recommended threshold |
| ---------------------------------- | --------------------- |
| Slide deck / screen recording      | `0.10` – `0.20`       |
| Demo with occasional slide changes | `0.20` (default)      |
| Live-action or talking-head video  | `0.30` – `0.40`       |

## How it works

1. **Download** — `uvx yt-dlp` fetches a video-only stream (≤720p) to a temp
   directory. No audio is downloaded.
2. **Detect** — `ffmpeg` runs the `select='gt(scene,THRESHOLD)'` filter with
   `showinfo` to find timestamps where the image changes substantially.
3. **Downsample** — if more than `--max-frames` timestamps are found, an
   evenly-spaced subset is kept to stay within API limits.
4. **Extract** — one JPEG frame per timestamp, scaled to 1280 px wide.
5. **Analyse** — all frames are sent in a single Gemini request with
   interleaved timestamp labels. Gemini returns one description per frame.
6. **Output** — Markdown with clickable `[M:SS](url&t=N)` headers and
   per-frame descriptions.

## Example output

```markdown
# Visual Analysis

**Source:** https://youtu.be/abc123
**Frames analysed:** 8
**Scene threshold:** 0.2

## [0:00](https://youtu.be/abc123&t=0)

Title slide: "Introduction to Distributed Systems" — speaker name and
conference logo visible.

## [2:14](https://youtu.be/abc123&t=134)

Diagram showing three nodes connected by arrows labelled "consensus round".
…
```

## When to use which approach

| Scenario                                       | Tool                           |
| ---------------------------------------------- | ------------------------------ |
| Quick visual overview of any YouTube video     | This skill (default settings)  |
| Dense slide deck, need every slide             | `--threshold 0.10 --max-frames 20` |
| Only a known interesting segment               | `--start` / `--end`            |
| Single image or screenshot (no video)          | `gemini-vision` skill          |
| Transcript-only analysis (no visuals needed)   | `youtube-to-markdown` skill    |

## Notes

- The script downloads only the video stream (no audio). For a 30-minute
  720p screencast expect ~100–300 MB temporarily in `/tmp`.
- All temp files are cleaned up automatically after analysis.
- `uvx yt-dlp` runs yt-dlp from an ephemeral cache; no persistent install
  needed beyond `uvx` itself.
