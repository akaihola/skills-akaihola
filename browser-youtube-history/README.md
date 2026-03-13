# browser-youtube-history

Find videos in a user's YouTube watch history by driving a logged-in browser session over CDP.

## Requirements

- A Chromium-based browser already running with remote debugging enabled
- A reachable CDP endpoint, usually `http://127.0.0.1:9222`
- The browser session already logged into the user's Google account
- Project dependencies installed with `uv sync`

## Dump visible YouTube history

```bash
uv run /home/agent/prg/skills-akaihola/browser-youtube-history/scripts/find_youtube_history.py \
  --cdp-url http://127.0.0.1:9222 \
  --output /tmp/youtube_history_dump.txt \
  --metadata-output /tmp/youtube_history_dump.json
```

Then inspect `/tmp/youtube_history_dump.txt` to identify the likely video title and URL.

## Dump visible details for a known video

```bash
uv run /home/agent/prg/skills-akaihola/browser-youtube-history/scripts/find_video_details.py \
  "https://youtu.be/VIDEO_ID" \
  --cdp-url http://127.0.0.1:9222 \
  --expand-description \
  --output /tmp/video-details.txt \
  --metadata-output /tmp/video-details.json
```

Then inspect `/tmp/video-details.txt` for the expanded description and visible page text.

## Notes

- The scripts use the current repo virtualenv, so run them from `/home/agent/prg/skills-akaihola` or with `uv run` from anywhere.
- Default outputs go under `~/.cache/browser-youtube-history/` if you omit `--output`.
- Public metadata and transcript fetches still work better with `yt-dlp` and the existing YouTube transcript skills once you know the exact video.
