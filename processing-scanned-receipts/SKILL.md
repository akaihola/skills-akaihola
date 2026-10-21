---
name: processing-scanned-receipts
description: Use when processing a batch of scanned receipt PDFs that need image extraction, OCR, structured plaintext generation, and descriptive renaming.
---

# Processing Scanned Receipts

Automates the full pipeline from raw scan PDFs to neatly named, OCR-extracted receipt files. Produces three files per receipt: `.pdf` (original), `.jpg` (extracted image), `.txt` (structured plaintext).

## Prerequisites

| Tool | Install |
|------|---------|
| `pdfimages` | `nix-shell -p poppler_utils` / `apt install poppler-utils` |
| `magick` | `nix-shell -p imagemagick` / `apt install imagemagick` |
| `llm` CLI | `pip install llm` |
| openrouter plugin | `llm install llm-openrouter` then `llm keys set openrouter` |

## Quick Start

All examples below are synthetic and contain no real receipt data.

```bash
uv run /path/to/process_receipts.py "receipts/synthetic-batch/"
```

The script processes all `*.pdf` files in the directory in parallel (4 workers by default).

## What It Does

1. **Extracts** the embedded image from each PDF using `pdfimages -j`; keeps the first JPEG or converts the first non-JPEG via ImageMagick.
2. **OCRs** each JPG by sending it to `gpt-5.4-nano` via `llm -m openrouter/openai/gpt-5.4-nano … -a image.jpg`, asking for a structured JSON response with date, payee, route, amounts, VAT, card, vehicle details, etc.
3. **Caches** OCR JSON in `<dir>/.receipt-work/` keyed by the input PDF stem. Reuse requires that stem to stay unchanged;
   renamed outputs do not match the original cache keys. `--force` repeats extraction and OCR.
4. **Generates** a formatted plaintext `.txt` receipt (TAKSIKUITTI / KUITTI sections).
5. **Renames** all three files to `YYYY-MM-DD Payee description.ext`.
6. **Flags** potential duplicate scans (same complete sanitized date/payee/description basename) with `(2)` suffix and a warning.

## Options

```
--model MODEL       Override LLM model (default: openrouter/openai/gpt-5.4-nano)
--force             Re-OCR even if JSON cache exists
--dry-run           Preview renames from cached JSON only; no OCR or writes
--jobs N            Parallel workers (default: 4)
--work-dir DIR      Cache directory (default: <input-dir>/.receipt-work)
```

Dry-run reads existing `<work-dir>/<PDF stem>.json` metadata, even without a
cached JPG. It reports cache misses and unreadable metadata and skips those
PDFs. It creates no directories or files, runs no extraction or OCR commands,
and ignores `--force`. Run normal processing first to populate missing caches.

## Review and correction

Read [receipt review and output details](references/review.md) when correcting
OCR, comparing duplicate scans or inspecting the generated text. Only the
first embedded image is OCRed. Duplicate suffixes are based on the complete
sanitized basename within one run, not on date/payee alone.

Existing destination files are not protected against overwrites. Caches use
the original input stem, so rerunning renamed PDFs can perform OCR again.
Preserve corrections before another processing run.

Offline checks from the repository root:

```bash
uv run --no-project --with pytest pytest processing-scanned-receipts/tests -q
```
