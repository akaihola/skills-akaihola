#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["google-genai", "Pillow"]
# ///
"""
Edit or generate an image using Nano Banana Pro (gemini-3-pro-image-preview).

Usage:
    nano_banana_edit.py <prompt> [--input IMAGE] [--output OUTPUT] [--model MODEL]

If --input is provided, the image is sent alongside the prompt (image editing).
If not, a new image is generated from scratch.

Output is always saved as a real PNG file regardless of what the API returns.
"""

import argparse
import os
import sys
from pathlib import Path

import google.genai as genai
from google.genai import types
from PIL import Image
import io

MODEL_DEFAULT = "models/gemini-3-pro-image-preview"


def parse_args():
    p = argparse.ArgumentParser(
        description="Edit or generate images with Nano Banana Pro"
    )
    p.add_argument("prompt", help="Instruction for the model")
    p.add_argument("--input", "-i", help="Input image path (for editing mode)")
    p.add_argument("--output", "-o", required=True, help="Output image path (.png)")
    p.add_argument(
        "--model", default=MODEL_DEFAULT, help=f"Model name (default: {MODEL_DEFAULT})"
    )
    return p.parse_args()


def main():
    args = parse_args()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    contents = []

    if args.input:
        img_path = Path(args.input)
        if not img_path.exists():
            print(f"ERROR: Input file not found: {img_path}", file=sys.stderr)
            sys.exit(1)
        img_bytes = img_path.read_bytes()
        # Detect actual mime type regardless of extension
        img = Image.open(io.BytesIO(img_bytes))
        fmt = img.format or "JPEG"
        mime = f"image/{fmt.lower()}"
        print(
            f"Input: {img_path} ({img.size[0]}×{img.size[1]}, {fmt})", file=sys.stderr
        )
        contents.append(types.Part.from_bytes(data=img_bytes, mime_type=mime))

    contents.append(args.prompt)

    print(f"Model: {args.model}", file=sys.stderr)
    print("Sending request...", file=sys.stderr)

    response = client.models.generate_content(
        model=args.model,
        contents=contents,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
        ),
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    saved = False
    for part in response.candidates[0].content.parts:
        if part.inline_data and part.inline_data.mime_type.startswith("image/"):
            raw = part.inline_data.data
            # Always re-save via Pillow so the file format matches the extension.
            # The API may return JPEG data even when PNG is expected — Pillow fixes this.
            img = Image.open(io.BytesIO(raw))
            img.save(out_path, format="PNG")
            print(
                f"Saved: {out_path} ({img.size[0]}×{img.size[1]}, PNG)", file=sys.stderr
            )
            saved = True
            break
        elif part.text:
            print(f"Text response: {part.text[:300]}", file=sys.stderr)

    if not saved:
        print("ERROR: No image in response", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
