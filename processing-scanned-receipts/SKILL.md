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

```bash
uv run /path/to/process_receipts.py "talous/laskut ja kuitit/2025 Päivin taksikuitit/"
```

The script processes all `*.pdf` files in the directory in parallel (4 workers by default).

## What It Does

1. **Extracts** the embedded image from each PDF using `pdfimages -j` (keeps JPEG as-is, converts B&W ccitt/PBM to JPG via ImageMagick).
2. **OCRs** each JPG by sending it to `gpt-5.4-nano` via `llm -m openrouter/openai/gpt-5.4-nano … -a image.jpg`, asking for a structured JSON response with date, payee, route, amounts, VAT, card, vehicle details, etc.
3. **Caches** OCR JSON in `<dir>/.receipt-work/` so re-runs are fast. Use `--force` to re-OCR.
4. **Generates** a formatted plaintext `.txt` receipt (TAKSIKUITTI / KUITTI sections).
5. **Renames** all three files to `YYYY-MM-DD Payee description.ext`.
6. **Flags** potential duplicate scans (same date+payee) with `(2)` suffix and a warning.

## Options

```
--model MODEL       Override LLM model (default: openrouter/openai/gpt-5.4-nano)
--force             Re-OCR even if JSON cache exists
--dry-run           Preview proposed renames without writing files
--jobs N            Parallel workers (default: 4)
--work-dir DIR      Cache directory (default: <input-dir>/.receipt-work)
```

## Post-Processing: Manual Corrections

OCR is good but not perfect. After the script runs, review for:

| Issue | What to fix |
|-------|-------------|
| Unreadable date | Rename files; edit `Päivämäärä:` in `.txt` |
| Company name cut off in scan | Rename files; edit `Yritys:` and `payee_short` in `.txt` |
| Typo in payee | Rename files; edit `.txt` |
| Wrong date format (e.g. month/day confused) | Same as above |

**Rename all three extensions in one command:**
```bash
cd "<receipt-dir>"
for ext in pdf jpg txt; do
  mv "OLD NAME.$ext" "NEW NAME.$ext"
done
```

**Edit a single field in a `.txt`:** use the Edit tool (exact text replacement).

## Duplicate Handling

When the same trip is scanned twice (e.g. meter receipt + card terminal receipt), the script names them `… (2)`. To clean up:

1. View both JPGs to identify which is colour (preferred) and which is B&W.
2. The colour one usually has better information; its `.txt` may say "toinen skannaus" (second scan) – copy the primary's `.txt` content over it if the primary has cleaner notes.
3. Delete the B&W set; rename the colour `(2)` files to drop the `(2)` suffix.

```bash
# Keep colour (2), replace its .txt with primary's, delete primary, rename
trip="2025-01-13 Taksikuljetus 3T Oy taksimatka Koivusyrjä-Pasila"
cp "$trip.txt" "$trip (2).txt"
rm "$trip.jpg" "$trip.pdf" "$trip.txt"
for ext in jpg pdf txt; do mv "$trip (2).$ext" "$trip.$ext"; done
```

## OCR Prompt Notes

The prompt instructs the model to:
- Distinguish "Asiakkaan kappale" ("customer copy") from the actual company name.
- Return `null` for any field not visible rather than guessing.
- Use Finnish for the `description` field.
- Return plain JSON (no markdown fences).

The script strips accidental markdown fences before parsing.

## Output Format (.txt)

```
================================================
              TAKSIKUITTI / TAXI RECEIPT
================================================
Yritys:        Karakus Taksipalvelu
Y-tunnus:      2969041-2

Päivämäärä:    2025-02-25
Kellonaika:    07:58

------------------------------------------------
MATKAN TIEDOT
------------------------------------------------
Mistä:         Koivusyrjä, Espoo
Minne:         Ratapihantie, Pasila
Matka:         11.09 km
…
```
