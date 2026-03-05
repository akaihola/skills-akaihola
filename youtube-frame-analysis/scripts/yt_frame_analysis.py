#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["google-genai", "Pillow"]
# ///
r"""Analyse the visual content of a YouTube video.

Extracts frames at scene/slide changes and describes each with Gemini.

Usage:
    yt_frame_analysis.py <youtube-url> [options]

Requirements:
    - GEMINI_API_KEY environment variable
    - ffmpeg in PATH
    - uvx in PATH (for yt-dlp)

Examples:
    yt_frame_analysis.py "https://youtu.be/VIDEO_ID"
    yt_frame_analysis.py "https://youtu.be/VIDEO_ID" --threshold 0.15 --max-frames 20
    yt_frame_analysis.py "https://youtu.be/VIDEO_ID" --start 5:00 --end 12:30
    yt_frame_analysis.py "https://youtu.be/VIDEO_ID" \
        --prompt "List every slide title shown"

"""

import argparse
import io
import os
import re
import shutil
import subprocess  # noqa: S404
import sys
import tempfile
from pathlib import Path
from textwrap import dedent
from typing import Any

from google import genai
from google.genai import types
from PIL import Image

DEFAULT_MODEL = "gemini-2.0-flash"
# Lower threshold = more frames. 0.2 works well for screen recordings/slides;
# use 0.3-0.4 for live-action video.
DEFAULT_THRESHOLD = 0.2
DEFAULT_MAX_FRAMES = 12
# yt-dlp format: video-only stream at a reasonable resolution
DEFAULT_FORMAT = "bestvideo[height<=720][ext=mp4]/bestvideo[height<=720]/bestvideo"
DEFAULT_PROMPT = dedent("""\
    This is a frame extracted from a screen recording or presentation video.
    Describe what is shown on screen: slide content, diagrams, code, UI elements,
    demos, or other visual information. Be concise but complete. If it is a blank
    or transition frame, say so briefly.""")

_TS_PARTS_MM_SS = 2
_TS_PARTS_HH_MM_SS = 3
_MIN_RESPONSE_PARTS = 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fmt_ts(seconds: float) -> str:
    """Format seconds as M:SS or H:MM:SS."""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def parse_ts(value: str) -> float:
    """Parse M:SS or H:MM:SS or plain seconds string to float."""
    if ":" in value:
        parts = value.split(":")
        if len(parts) == _TS_PARTS_MM_SS:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == _TS_PARTS_HH_MM_SS:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    return float(value)


def run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:  # noqa: ANN401
    """Run a subprocess command and return the completed process."""
    return subprocess.run(cmd, check=False, **kwargs)  # noqa: S603


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------


def download_video(url: str, output_path: Path, fmt: str) -> None:
    """Download video stream (no audio) with uvx yt-dlp."""
    print(f"\u2b07  Downloading: {url}", file=sys.stderr)
    result = run(
        [
            "uvx",
            "yt-dlp",
            "--no-playlist",
            "--format",
            fmt,
            "-o",
            str(output_path),
            url,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"yt-dlp stderr:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    size_kb = output_path.stat().st_size // 1024
    print(f"   Saved -> {output_path.name}  ({size_kb} KB)", file=sys.stderr)


def detect_scene_changes(
    video_path: Path,
    threshold: float,
    start: float | None,
    end: float | None,
) -> list[float]:
    """Return sorted list of timestamps (seconds) where the scene changes."""
    print(
        f"\U0001f50d Detecting scene changes (threshold={threshold})...",
        file=sys.stderr,
    )

    vf = f"select='gt(scene,{threshold})',showinfo"
    cmd: list[str] = ["ffmpeg", "-i", str(video_path)]
    if start is not None:
        cmd += ["-ss", str(start)]
    if end is not None:
        cmd += ["-to", str(end)]
    cmd += ["-vf", vf, "-vsync", "vfr", "-f", "null", "-"]

    result = run(cmd, capture_output=True, text=True)

    timestamps: list[float] = []
    for line in result.stderr.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            ts = float(m.group(1))
            if start is not None:
                ts += start
            timestamps.append(ts)

    # Always start at t=0 (or start offset)
    t0 = start or 0.0
    if not timestamps or timestamps[0] > t0 + 1.0:
        timestamps.insert(0, t0)

    return sorted(set(timestamps))


def downsample(timestamps: list[float], max_frames: int) -> list[float]:
    """Keep an evenly-spaced subset, always including the first timestamp."""
    if len(timestamps) <= max_frames:
        return timestamps
    step = len(timestamps) / max_frames
    return [timestamps[int(i * step)] for i in range(max_frames)]


def extract_frame(video_path: Path, timestamp: float, output_path: Path) -> bool:
    """Extract a single JPEG frame at the given timestamp."""
    result = run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            str(timestamp),
            "-i",
            str(video_path),
            "-vframes",
            "1",
            "-q:v",
            "3",  # JPEG quality 3 = good enough, not huge
            "-vf",
            "scale=1280:-1",  # cap width at 1280 px
            str(output_path),
        ],
        capture_output=True,
    )
    return result.returncode == 0 and output_path.exists()


def _frame_mime(raw: bytes) -> str:
    """Detect MIME type from raw image bytes via Pillow."""
    mime_map = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
    try:
        img = Image.open(io.BytesIO(raw))
        return mime_map.get(img.format or "JPEG", "image/jpeg")
    except OSError:
        return "image/jpeg"


def analyse_frames_batch(
    frames: list[tuple[float, Path]],
    url: str,
    prompt: str,
    model: str,
    api_key: str,
) -> list[tuple[float, str]]:
    """Send all frames in one Gemini request for context-aware analysis."""
    client = genai.Client(api_key=api_key)
    print(
        f"\U0001f916 Sending {len(frames)} frames to Gemini ({model})...",
        file=sys.stderr,
    )

    # Build interleaved contents: intro + (label, image) pairs
    intro = (
        "Below are frames extracted from a video at timestamps where the screen "
        "content changes. For each frame I show the timestamp then the image.\n\n"
        f"Your task: {prompt}\n\n"
        "Provide a response for EACH frame in the format:\n"
        "## [TIMESTAMP]\n<your description>\n\n"
        "Use the exact timestamps shown.\n\n"
    )
    contents: list[object] = [intro]

    for ts, frame_path in frames:
        raw = frame_path.read_bytes()
        mime = _frame_mime(raw)
        contents.extend(
            [
                f"**Frame at {fmt_ts(ts)}** ({url}&t={int(ts)})\n",
                types.Part.from_bytes(data=raw, mime_type=mime),
            ]
        )

    try:
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(max_output_tokens=4096),
        )
        text = response.text or ""
    except genai.errors.APIError as exc:
        print(f"Gemini error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Parse structured response: ## [TIMESTAMP] ... ## [TIMESTAMP] ...
    parts = re.split(r"^##\s+\[?([0-9:]+)\]?", text, flags=re.MULTILINE)
    results: list[tuple[float, str]] = []
    if len(parts) >= _MIN_RESPONSE_PARTS:
        # parts[0] = preamble, then alternating: timestamp_str, description, ...
        it = iter(parts[1:])
        for ts_str, desc in zip(it, it, strict=False):
            try:
                ts = parse_ts(ts_str.strip())
            except ValueError:
                ts = 0.0
            results.append((ts, desc.strip()))
    elif frames:
        results.append((frames[0][0], text.strip()))
    else:
        print(text)

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Build and return the argument parser."""
    p = argparse.ArgumentParser(
        description=(
            "Extract scene-change frames from a YouTube video and analyse with Gemini"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent("""\
            examples:
              %(prog)s "https://youtu.be/VIDEO_ID"
              %(prog)s "https://youtu.be/VIDEO_ID" --threshold 0.15 --max-frames 20
              %(prog)s "https://youtu.be/VIDEO_ID" --start 5:00 --end 12:30
              %(prog)s "https://youtu.be/VIDEO_ID" \\
                  --prompt "List each slide title shown"
        """),
    )
    p.add_argument("url", help="YouTube video URL")
    p.add_argument(
        "--threshold",
        "-t",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=(
            f"Scene-change sensitivity 0.0-1.0 (default: {DEFAULT_THRESHOLD}; "
            "lower = more frames; try 0.15 for dense slides, 0.35 for live video)"
        ),
    )
    p.add_argument(
        "--max-frames",
        "-n",
        type=int,
        default=DEFAULT_MAX_FRAMES,
        help=f"Maximum frames to analyse (default: {DEFAULT_MAX_FRAMES})",
    )
    p.add_argument(
        "--prompt",
        "-p",
        default=DEFAULT_PROMPT,
        help="Instruction sent to Gemini for each frame",
    )
    p.add_argument(
        "--model",
        "-m",
        default=DEFAULT_MODEL,
        help=f"Gemini model to use (default: {DEFAULT_MODEL})",
    )
    p.add_argument(
        "--format",
        "-f",
        default=DEFAULT_FORMAT,
        dest="fmt",
        help="yt-dlp format selector (default: bestvideo[height<=720])",
    )
    p.add_argument(
        "--start",
        type=parse_ts,
        default=None,
        metavar="TIME",
        help="Start time (M:SS, H:MM:SS, or seconds)",
    )
    p.add_argument(
        "--end",
        type=parse_ts,
        default=None,
        metavar="TIME",
        help="End time (M:SS, H:MM:SS, or seconds)",
    )
    return p.parse_args()


def main() -> None:
    """Entry point: download, detect, extract, analyse, print."""
    args = parse_args()

    api_key = os.environ.get("GEMINI_API_KEY") or ""
    if not api_key:
        print("ERROR: GEMINI_API_KEY environment variable is not set", file=sys.stderr)
        sys.exit(1)

    for tool in ("ffmpeg", "uvx"):
        if not shutil.which(tool):
            print(f"ERROR: {tool!r} not found in PATH", file=sys.stderr)
            sys.exit(1)

    with tempfile.TemporaryDirectory(prefix="yt_frames_") as tmpdir:
        tmp = Path(tmpdir)
        video_path = tmp / "video.mp4"
        frames_dir = tmp / "frames"
        frames_dir.mkdir()

        # 1. Download
        download_video(args.url, video_path, args.fmt)

        # 2. Detect scene changes
        timestamps = detect_scene_changes(
            video_path, args.threshold, args.start, args.end
        )
        print(f"   Found {len(timestamps)} candidate frames", file=sys.stderr)

        # 3. Downsample
        timestamps = downsample(timestamps, args.max_frames)
        print(
            f"   Keeping {len(timestamps)} frames (max={args.max_frames})",
            file=sys.stderr,
        )

        # 4. Extract frames
        frames: list[tuple[float, Path]] = []
        for i, ts in enumerate(timestamps):
            frame_path = frames_dir / f"frame_{i:04d}.jpg"
            if extract_frame(video_path, ts, frame_path):
                frames.append((ts, frame_path))
            else:
                print(
                    f"   WARNING: Could not extract frame at {fmt_ts(ts)}",
                    file=sys.stderr,
                )

        print(f"   Extracted {len(frames)} frames", file=sys.stderr)

        if not frames:
            print("ERROR: no frames could be extracted", file=sys.stderr)
            sys.exit(1)

        # 5. Analyse (all frames in one Gemini request)
        results = analyse_frames_batch(
            frames, args.url, args.prompt, args.model, api_key
        )

    # 6. Print Markdown output
    print("# Visual Analysis\n")
    print(f"**Source:** {args.url}  ")
    print(f"**Frames analysed:** {len(results)}  ")
    print(f"**Scene threshold:** {args.threshold}  ")
    if args.start or args.end:
        if args.end:
            rng = f"{fmt_ts(args.start or 0)} - {fmt_ts(args.end)}"
        else:
            rng = f"from {fmt_ts(args.start or 0)}"
        print(f"**Time range:** {rng}  ")
    print()

    for ts, description in results:
        link = f"{args.url}&t={int(ts)}"
        print(f"## [{fmt_ts(ts)}]({link})\n")
        print(f"{description}\n")


if __name__ == "__main__":
    main()
