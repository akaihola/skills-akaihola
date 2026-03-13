---
name: browser-youtube-history
description: >-
  Find videos in a user's YouTube watch history by driving a logged-in browser session,
  not Google APIs. Use when the user says they watched something on YouTube and wants
  you to find it, mentions a browser with Google login or a CDP/remote-debugging session,
  or asks for a watched video's title, URL, description, or transcript from their history.
  Prefer this skill whenever browser access is available and the task depends on the
  user's private logged-in YouTube history.
version: 0.1.0
---

# Browser YouTube History

Use a logged-in browser session to inspect YouTube watch history and recover the exact video the user watched. This workflow is for browser automation against the user's existing session, not Google APIs.

For quick copy-paste examples, see `README.md` in this directory.

## When to use

Use this skill when:

- the user says they watched a YouTube video and wants help finding it
- the user can provide a logged-in browser session, CDP endpoint, or SSH tunnel to a browser
- the task requires private watch-history data unavailable to public search
- the user wants the found video's title, URL, description, or transcript

Do not use this skill when a plain public YouTube URL is already known and no history lookup is needed - use `youtube-to-markdown` or other YouTube skills directly.

## Inputs to gather

Before starting, confirm:

- a reachable Chromium CDP endpoint, usually `http://127.0.0.1:9222`
- the browser session is already logged into Google
- any hints the user remembers: title fragment, channel, time of day, topic, language

If the remote browser only listens on `127.0.0.1`, ask the user to provide an SSH tunnel so the endpoint becomes reachable locally.

## Workflow

### 1. Verify browser access

Check that the CDP endpoint responds:

```bash
python - <<'PY'
import urllib.request
for url in ["http://127.0.0.1:9222/json/version", "http://127.0.0.1:9222/json/list"]:
    with urllib.request.urlopen(url, timeout=8) as r:
        print(url)
        print(r.read().decode("utf-8", "replace"))
PY
```

If this fails, stop and ask the user to fix the tunnel or browser session.

### 2. Open YouTube history in the logged-in browser

A simple and reliable way is to create a new tab through the DevTools HTTP API:

```bash
python - <<'PY'
import urllib.request
req = urllib.request.Request(
    "http://127.0.0.1:9222/json/new?https://myactivity.google.com/product/youtube?hl=en",
    method="PUT",
)
with urllib.request.urlopen(req, timeout=10) as r:
    print(r.read().decode())
PY
```

This reuses the existing logged-in browser profile instead of trying to recreate authentication elsewhere.

### 3. Capture the visible history text

When you mainly need to identify the watched video title, use the helper script in `scripts/find_youtube_history.py`. It connects to the logged-in browser over CDP, opens the YouTube history page, scrolls a few times, and writes the visible text dump to a file.

```bash
uv run /home/agent/prg/skills-akaihola/browser-youtube-history/scripts/find_youtube_history.py \
  --cdp-url http://127.0.0.1:9222 \
  --output /tmp/youtube_history_dump.txt \
  --metadata-output /tmp/youtube_history_dump.json
```

Then inspect the saved file with the Read tool. The history page often already contains the exact watched title, channel, time, and duration.

### 4. Identify the candidate video

Search the saved dump for the user's remembered fragment. Watch for nearby entries in the same time window - the first guess may be wrong if the terminal output was truncated.

For example, look for keywords like `superpower`, `superpowers`, or a channel name.

### 5. Fetch description and transcript once the video is known

After you identify the video, you have two good paths:

- use browser automation again to open the actual video page and dump the visible description/details with `scripts/find_video_details.py`
- use normal public YouTube tooling to get metadata and transcript from the public video URL

Browser path:

```bash
uv run /home/agent/prg/skills-akaihola/browser-youtube-history/scripts/find_video_details.py \
  "https://youtu.be/VIDEO_ID" \
  --cdp-url http://127.0.0.1:9222 \
  --expand-description \
  --output /tmp/video-details.txt \
  --metadata-output /tmp/video-details.json
```

Public metadata path:

```bash
uvx yt-dlp --get-id --get-title --get-description "https://youtu.be/VIDEO_ID"
```

Transcript path:

```bash
uv run /home/agent/.claude/skills/youtube-to-markdown/scripts/vtt2md.py \
  "https://youtu.be/VIDEO_ID" -o /tmp/video-transcript.md
```

Read the saved files with the Read tool and summarize the important parts for the user.

## Practical notes

- Prefer writing intermediate outputs to `/tmp/*.txt` or `/tmp/*.md` so failed wrapper sessions do not lose the only useful data.
- If Playwright wrapper output is killed or truncated, check for the `/tmp` file before retrying.
- The YouTube history page text is often enough. Network interception is a fallback, not the first move.
- When Playwright JavaScript snippets become fiddly, simplify. Reading `body.inner_text()` is often more reliable than complex DOM extraction.
- Once you have the title from history, use normal public YouTube tools for the rest.

## Report back

When answering the user, include:

- the exact video title
- the channel
- the watched time from history if useful
- the video URL if recovered
- the description summary and transcript summary, if requested

Be explicit about confidence if multiple similar titles appear in history.
