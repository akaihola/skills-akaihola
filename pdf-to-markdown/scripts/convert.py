# /// script
# requires-python = ">=3.11"
# dependencies = ["google-genai", "pymupdf"]
# ///

# Convert a PDF book (or document) to Markdown using the Gemini Files API.
# Images are extracted with pymupdf and embedded into the output.
#
# Usage:
#   GEMINI_API_KEY=... uv run convert.py config.toml
#
# config.toml defines chapters/sections with page ranges and output paths.
# See README.md for the config format.

import os
import re
import sys
import time
from pathlib import Path
from textwrap import dedent
from unicodedata import normalize

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-reuse-def]

import fitz
from google import genai
from google.genai import types

DEFAULT_MODEL = "gemini-2.0-flash"
DEFAULT_DPI = 150  # used if image_extraction = "render" (not needed for PDF mode)


def slugify(text: str) -> str:
    text = normalize("NFD", text.lower())
    text = re.sub(r"[^\w\s-]", "", text, flags=re.ASCII)
    return re.sub(r"[\s_]+", "-", text).strip("-")


def extract_images(
    doc: fitz.Document, page_images: dict[int, list[str]], img_dir: Path
) -> int:
    """Extract embedded images from PDF pages into img_dir."""
    img_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for page_num in range(len(doc)):
        page = doc[page_num]
        for idx, img in enumerate(page.get_images()):
            xref = img[0]
            base_image = doc.extract_image(xref)
            ext = base_image["ext"]
            name = f"image-{idx + 1:02d}-page{page_num + 1}.{ext}"
            (img_dir / name).write_bytes(base_image["image"])
            page_images.setdefault(page_num + 1, []).append(name)
            count += 1
    return count


def fix_hyphenation(text: str) -> str:
    """Join words split across lines with a hyphen."""
    return re.sub(r"([a-zäöåA-ZÄÖÅ])-\s*\n\s*([a-zäöåA-ZÄÖÅ])", r"\1\2", text)


def fix_broken_paragraphs(text: str) -> str:
    """Join lines that were broken at page boundaries (no sentence-ending punctuation)."""
    lines = text.split("\n")
    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if (
            i + 1 < len(lines)
            and line.strip()
            and lines[i + 1].strip()
            and not line.startswith(("#", ">", "-", "*", "!", "|"))
            and not lines[i + 1].startswith(("#", ">", "-", "*", "!", "|"))
        ):
            last_char = line.rstrip()[-1] if line.rstrip() else ""
            first_char = lines[i + 1].lstrip()[0] if lines[i + 1].lstrip() else ""
            if last_char not in '.?!"»)' and first_char.islower():
                result.append(line + " " + lines[i + 1].lstrip())
                i += 2
                continue
        result.append(line)
        i += 1
    return "\n".join(result)


def build_image_replacer(chapter_images: dict[int, list[str]], img_rel_path: str):
    def replace(m: re.Match) -> str:
        p = int(m.group(1))
        imgs = chapter_images.get(p, [])
        if not imgs:
            return ""
        return (
            "\n\n"
            + "\n\n".join(f"![{img}]({img_rel_path}/{img})" for img in imgs)
            + "\n\n"
        )

    return replace


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: convert.py config.toml")
        sys.exit(1)

    config_path = Path(sys.argv[1]).resolve()
    with open(config_path, "rb") as f:
        config = tomllib.load(f)

    pdf_path = (config_path.parent / config["pdf"]).resolve()
    output_dir = (config_path.parent / config.get("output_dir", ".")).resolve()
    img_subdir = config.get("images_dir", "images")
    img_dir = output_dir / img_subdir
    model = config.get("model", DEFAULT_MODEL)
    rate_limit_sleep = config.get("rate_limit_sleep", 1.0)

    sections = config["sections"]

    # Step 1: extract images
    doc = fitz.open(pdf_path)
    page_images: dict[int, list[str]] = {}
    img_count = extract_images(doc, page_images, img_dir)
    doc.close()
    print(f"Extracted {img_count} images from {len(page_images)} pages")

    # Step 2: upload PDF
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    print(f"Uploading PDF ({pdf_path.stat().st_size // 1024} KB)...")
    uploaded = client.files.upload(
        file=pdf_path,
        config=types.UploadFileConfig(mime_type="application/pdf"),
    )
    print(f"Uploaded: {uploaded.uri}")

    # Step 3: convert each section
    for sec in sections:
        slug = sec["slug"]
        start_page = sec["start_page"]
        end_page = sec["end_page"]
        heading = sec["heading"]
        out_rel = sec.get("output", f"{slug}.md")
        out_path = output_dir / out_rel
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Relative path from output file to images dir
        img_rel = os.path.relpath(img_dir, out_path.parent)

        chapter_images = {
            p: imgs for p, imgs in page_images.items() if start_page <= p <= end_page
        }
        img_pages_str = (
            ", ".join(f"page {p}" for p in sorted(chapter_images)) or "no images"
        )

        extra_instructions = sec.get("instructions", "")
        prompt = dedent(f"""\
            Convert pages {start_page}–{end_page} of this PDF to clean Markdown.
            Start exactly with the heading: {heading}
            - Join hyphenated words (e.g. "hier-\narchy" → "hierarchy")
            - Continue paragraphs seamlessly across page boundaries — no extra line breaks at page turns
            - Remove page numbers entirely
            - Use ## for main sections, ### for subsections
            - Format quotations/citations as Markdown blockquotes (> text)
            - Image locations ({img_pages_str}): mark each image as [IMAGE page N]
            - Return plain Markdown only, no code block wrapper
            {extra_instructions}
        """)

        print(f"\nConverting: {out_rel} (pages {start_page}–{end_page})...")
        try:
            response = client.models.generate_content(
                model=model,
                contents=[uploaded, prompt],
                config=types.GenerateContentConfig(max_output_tokens=8192),
            )
            content = response.text.strip()
        except Exception as e:
            print(f"  ERROR: {e}")
            continue

        # Replace image placeholders
        replacer = build_image_replacer(chapter_images, img_rel)
        content = re.sub(r"\[IMAGE page (\d+)\]", replacer, content)

        # Post-process: fix remaining hyphenation and page-break paragraph splits
        content = fix_hyphenation(content)
        content = fix_broken_paragraphs(content)

        out_path.write_text(content, encoding="utf-8")
        print(f"  Written: {out_rel} ({len(content)} chars)")
        time.sleep(rate_limit_sleep)

    client.files.delete(name=uploaded.name)
    print("\nDone!")


if __name__ == "__main__":
    main()
