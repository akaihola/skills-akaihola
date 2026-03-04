#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["google-genai", "Pillow"]
# ///
"""Analyse one or more images with Gemini's vision model.

Usage:
    gemini_vision.py <prompt> <image1> [<image2> ...] [options]

Examples:
    gemini_vision.py "Describe this image." photo.jpg
    gemini_vision.py "What text is visible?" screenshot.png
    gemini_vision.py "Compare these two images." before.png after.png
    gemini_vision.py "Extract chart data as a table." chart.png --model gemini-2.5-flash

"""

import argparse
import io
import os
import sys
from pathlib import Path
from textwrap import dedent

from google import genai
from google.genai import types
from PIL import Image

DEFAULT_MODEL = "gemini-2.0-flash"
DEFAULT_MAX_TOKENS = 4096

# MIME types Gemini's vision API accepts
MIME_MAP: dict[str, str] = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "GIF": "image/gif",
    "WEBP": "image/webp",
    "BMP": "image/bmp",
    "TIFF": "image/tiff",
    "PDF": "application/pdf",
}


def detect_mime_type(path: Path) -> str:
    """Detect MIME type from file content via Pillow (ignores file extension)."""
    raw = path.read_bytes()
    # Check for PDF magic bytes first (Pillow can't open PDFs)
    if raw[:4] == b"%PDF":
        return "application/pdf"
    try:
        img = Image.open(io.BytesIO(raw))
        fmt = img.format or "JPEG"
        return MIME_MAP.get(fmt, "image/jpeg")
    except OSError:
        # Fall back to extension-based guess
        ext = path.suffix.lower().lstrip(".")
        fallback: dict[str, str] = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "gif": "image/gif",
            "webp": "image/webp",
            "bmp": "image/bmp",
            "tiff": "image/tiff",
            "tif": "image/tiff",
            "pdf": "application/pdf",
        }
        return fallback.get(ext, "image/jpeg")


def load_image_part(path: Path) -> types.Part:
    """Load an image file and return a Gemini content Part."""
    if not path.exists():
        print(f"ERROR: image file not found: {path}", file=sys.stderr)
        sys.exit(1)
    raw = path.read_bytes()
    mime = detect_mime_type(path)
    size_kb = len(raw) // 1024
    print(f"  {path.name}  ({size_kb} KB, {mime})", file=sys.stderr)
    return types.Part.from_bytes(data=raw, mime_type=mime)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(
        description="Analyse images with Gemini's vision model",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent("""\
            examples:
              gemini_vision.py "Describe this image." photo.jpg
              gemini_vision.py "What text is visible?" screenshot.png
              gemini_vision.py "Compare these images." before.png after.png
              gemini_vision.py "Extract table data." chart.png --model gemini-2.5-flash
        """),
    )
    p.add_argument("prompt", help="Question or instruction for the model")
    p.add_argument("images", nargs="+", metavar="IMAGE", help="Image file path(s)")
    p.add_argument(
        "--model",
        "-m",
        default=DEFAULT_MODEL,
        help=f"Gemini model to use (default: {DEFAULT_MODEL})",
    )
    p.add_argument(
        "--max-tokens",
        "-t",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help=f"Maximum output tokens (default: {DEFAULT_MAX_TOKENS})",
    )
    p.add_argument(
        "--system",
        "-s",
        default="",
        help="Optional system instruction",
    )
    return p.parse_args()


def main() -> None:
    """Entry point: analyse images and print the model's response to stdout."""
    args = parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY environment variable is not set", file=sys.stderr)
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    print(f"Model: {args.model}", file=sys.stderr)
    print(f"Images ({len(args.images)}):", file=sys.stderr)

    # Build contents: images first, then the prompt text
    image_parts: list[types.Part] = [load_image_part(Path(p)) for p in args.images]
    contents: list[types.Part | str] = [*image_parts, args.prompt]

    # Build request config
    config_kwargs: dict[str, object] = {"max_output_tokens": args.max_tokens}
    if args.system:
        config_kwargs["system_instruction"] = args.system

    print("Sending request to Gemini...", file=sys.stderr)
    try:
        response = client.models.generate_content(
            model=args.model,
            contents=contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )
    except genai.errors.APIError as exc:
        print(f"ERROR: Gemini API call failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if not response.text:
        print("ERROR: Empty response from Gemini", file=sys.stderr)
        try:
            candidate = response.candidates[0]
            print(f"  Finish reason: {candidate.finish_reason}", file=sys.stderr)
        except (IndexError, AttributeError) as exc:
            print(f"  (could not read finish reason: {exc})", file=sys.stderr)
        sys.exit(1)

    print(response.text)


if __name__ == "__main__":
    main()
