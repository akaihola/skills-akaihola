#!/usr/bin/env python3
"""
process_receipts.py – Extract JPGs from scanned receipt PDFs, OCR via LLM,
generate structured plaintext receipt files, and rename everything with a
descriptive YYYY-MM-DD Payee description.ext scheme.

Prerequisites:
    pdfimages  (poppler-utils / poppler)
    magick     (ImageMagick)
    llm        (with openrouter plugin and key configured)

Usage:
    uv run process_receipts.py <directory> [options]

Options:
    --model MODEL       LLM model (default: openrouter/openai/gpt-5.4-nano)
    --force             Re-OCR even when JSON cache exists
    --dry-run           Show proposed renames without writing anything
    --jobs N            Parallel OCR jobs (default: 4)
    --work-dir DIR      Cache directory (default: <directory>/.receipt-work)
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from textwrap import dedent

DEFAULT_MODEL = "openrouter/openai/gpt-5.4-nano"

OCR_PROMPT = dedent("""\
    You are analyzing a scanned receipt image. Extract ALL visible details.
    Return a JSON object with exactly these fields:
    - date: YYYY-MM-DD string, or null if unreadable
    - time: HH:MM string if visible, else null
    - payee: the actual company/business name printed on the receipt.
      NOTE: "Asiakkaan kappale" means "customer copy" – it is NOT a company name.
      Look for the real company name, usually at the very top.
    - payee_short: abbreviated payee suitable for a filename, max 25 chars
    - description: what was purchased or the service type, in Finnish, max 40 chars
    - route_from: departure address/location for transport receipts, else null
    - route_to: destination address/location for transport receipts, else null
    - total_amount: total charged as a numeric string e.g. "23.50"
    - currency: currency code e.g. "EUR"
    - netto: net amount before VAT as numeric string, else null
    - vat_amount: VAT amount as numeric string, else null
    - vat_rate: VAT percentage e.g. "14%" or "25.5%", else null
    - payment_method: e.g. "Visa Contactless", "Visa Debit", "Cash", else null
    - card_last4: last 4 digits of payment card if visible, else null
    - car_reg: vehicle registration plate e.g. "SPH-233", else null
    - car_number: taxi car number if visible, else null
    - driver_number: taxi driver number (kuljettajanumero) if visible, else null
    - receipt_number: receipt/kuittinro if visible, else null
    - business_id: Finnish Y-tunnus in format XXXXXXX-X, else null
    - is_taxi_receipt: true or false
    - distance_km: trip distance as string e.g. "12.6", else null
    - duration: trip duration as string e.g. "0:22", else null
    - notes: any other relevant details as a single line string, else null

    Return ONLY valid JSON. No markdown fences. No extra text before or after.
""")


# ---------------------------------------------------------------------------
# Image extraction
# ---------------------------------------------------------------------------

def extract_jpg_from_pdf(pdf_path: Path, work_dir: Path) -> Path:
    """Extract the first embedded image from *pdf_path*, returning a .jpg."""
    stem = pdf_path.stem
    prefix = work_dir / stem

    subprocess.run(
        ["pdfimages", "-j", str(pdf_path), str(prefix)],
        check=True,
        capture_output=True,
    )

    # pdfimages names outputs <prefix>-000.jpg / .pbm / .ppm etc.
    candidates = sorted(work_dir.glob(f"{_glob_escape(stem)}-*"))
    if not candidates:
        raise FileNotFoundError(f"pdfimages produced no output for {pdf_path.name}")

    extracted = candidates[0]

    if extracted.suffix.lower() in (".jpg", ".jpeg"):
        return extracted

    # Convert non-JPEG (B&W ccitt → PBM, colour non-JPEG → PPM) to JPG
    jpg_path = extracted.with_suffix(".jpg")
    subprocess.run(
        ["magick", str(extracted), str(jpg_path)],
        check=True,
        capture_output=True,
    )
    extracted.unlink()
    return jpg_path


def _glob_escape(s: str) -> str:
    """Escape glob metacharacters in a path component."""
    return re.sub(r"([\[\]*?])", r"[\1]", s)


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

def ocr_receipt(jpg_path: Path, model: str) -> dict:
    """Call *llm* with the image; return parsed JSON dict."""
    result = subprocess.run(
        ["llm", "-m", model, OCR_PROMPT, "-a", str(jpg_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    raw = result.stdout.strip()
    # Strip accidental markdown fences if the model wraps anyway
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Receipt text generation
# ---------------------------------------------------------------------------

def make_receipt_text(r: dict) -> str:
    """Render *r* (OCR JSON) as a human-readable plaintext receipt."""
    SEP = "=" * 48
    DIV = "-" * 48
    currency = r.get("currency") or "EUR"

    def row(label: str, value) -> str:
        return f"{label:<15}{value}"

    lines = [SEP]
    if r.get("is_taxi_receipt"):
        lines.append("              TAKSIKUITTI / TAXI RECEIPT")
    else:
        lines.append("              KUITTI / RECEIPT")
    lines += [SEP, ""]

    lines.append(row("Yritys:", r.get("payee") or "—"))
    if r.get("business_id"):
        lines.append(row("Y-tunnus:", r["business_id"]))
    lines.append("")

    date_str = r.get("date") or "PÄIVÄMÄÄRÄ EPÄSELVÄ"
    lines.append(row("Päivämäärä:", date_str))
    if r.get("time"):
        lines.append(row("Kellonaika:", r["time"]))
    lines.append("")

    if r.get("is_taxi_receipt"):
        lines += [DIV, "MATKAN TIEDOT", DIV]
        if r.get("route_from"):
            lines.append(row("Mistä:", r["route_from"]))
        if r.get("route_to"):
            lines.append(row("Minne:", r["route_to"]))
        if r.get("distance_km"):
            lines.append(row("Matka:", f"{r['distance_km']} km"))
        if r.get("duration"):
            lines.append(row("Kesto:", r["duration"]))
        if r.get("car_reg"):
            lines.append(row("Rek.tunnus:", r["car_reg"]))
        if r.get("car_number"):
            lines.append(row("Auton nro:", r["car_number"]))
        if r.get("driver_number"):
            lines.append(row("Kuljettaja nro:", r["driver_number"]))
        lines.append("")

    lines += [DIV, "MAKSUTIEDOT", DIV]
    lines.append(row("Yhteensä:", f"{r.get('total_amount', '—')} {currency}"))
    if r.get("netto"):
        lines.append(row("Veroton:", f"{r['netto']} {currency}"))
    if r.get("vat_amount") and r.get("vat_rate"):
        vat_label = f"ALV {r['vat_rate']}:"
        lines.append(row(vat_label, f"{r['vat_amount']} {currency}"))
    lines.append("")

    if r.get("payment_method"):
        lines.append(row("Maksutapa:", r["payment_method"]))
    if r.get("card_last4"):
        lines.append(row("Kortti:", f"****{r['card_last4']}"))
    if r.get("receipt_number"):
        lines.append(row("Kuittinro:", r["receipt_number"]))

    if r.get("notes"):
        lines += ["", DIV, row("Lisätiedot:", r["notes"])]

    lines += ["", SEP]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Filename helpers
# ---------------------------------------------------------------------------

def _sanitize(s: str) -> str:
    """Strip/replace characters unsafe in filenames."""
    s = re.sub(r'[/\\:*?"<>|]', "-", s.strip())
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip(" -")


def make_base_name(r: dict) -> str:
    """Return  YYYY-MM-DD Payee description  (no extension)."""
    date = r.get("date") or "XXXX-XX-XX"
    payee = _sanitize((r.get("payee_short") or r.get("payee") or "tuntematon")[:30])
    desc = _sanitize((r.get("description") or "kuitti")[:50])
    return f"{date} {payee} {desc}"


def unique_name(base: str, seen: dict) -> str:
    """Append (2), (3) … to *base* when it collides with an earlier entry."""
    if base not in seen:
        seen[base] = 1
        return base
    seen[base] += 1
    return f"{base} ({seen[base]})"


# ---------------------------------------------------------------------------
# Per-PDF processing
# ---------------------------------------------------------------------------

def process_one(pdf_path: Path, work_dir: Path, model: str, force: bool) -> tuple[Path, dict]:
    """Extract image + OCR for one PDF.  Returns (jpg_path, ocr_dict)."""
    stem = pdf_path.stem
    json_cache = work_dir / f"{stem}.json"
    jpg_cache_candidates = sorted(work_dir.glob(f"{_glob_escape(stem)}-*.jpg"))
    jpg_path = jpg_cache_candidates[0] if jpg_cache_candidates else None

    if jpg_path is None or force:
        jpg_path = extract_jpg_from_pdf(pdf_path, work_dir)

    if not json_cache.exists() or force:
        data = ocr_receipt(jpg_path, model)
        json_cache.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        data = json.loads(json_cache.read_text())

    return jpg_path, data


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="OCR-process scanned receipt PDFs and rename them descriptively."
    )
    parser.add_argument("directory", help="Directory containing scanned receipt PDFs")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"LLM model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--force", action="store_true",
                        help="Re-OCR even when JSON cache already exists")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print proposed renames without writing files")
    parser.add_argument("--jobs", type=int, default=4,
                        help="Parallel OCR workers (default: 4)")
    parser.add_argument("--work-dir",
                        help="Directory for intermediate files (default: <directory>/.receipt-work)")
    args = parser.parse_args()

    target_dir = Path(args.directory).expanduser().resolve()
    if not target_dir.is_dir():
        sys.exit(f"Error: {target_dir} is not a directory")

    work_dir = (
        Path(args.work_dir).expanduser().resolve()
        if args.work_dir
        else target_dir / ".receipt-work"
    )
    work_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(target_dir.glob("*.pdf"))
    if not pdfs:
        sys.exit(f"No PDF files found in {target_dir}")

    print(f"Found {len(pdfs)} PDF(s) – OCR model: {args.model}\n")

    # --- parallel OCR ---
    results: list[tuple[Path, Path, dict]] = []  # (pdf, jpg, data)
    errors: list[tuple[Path, str]] = []

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {
            pool.submit(process_one, pdf, work_dir, args.model, args.force): pdf
            for pdf in pdfs
        }
        for future in as_completed(futures):
            pdf = futures[future]
            try:
                jpg_path, data = future.result()
                results.append((pdf, jpg_path, data))
                print(f"  ✓  {pdf.name}")
            except Exception as exc:
                errors.append((pdf, str(exc)))
                print(f"  ✗  {pdf.name}: {exc}", file=sys.stderr)

    if errors:
        print(f"\n{len(errors)} file(s) failed – skipped.", file=sys.stderr)

    # Sort by proposed date so output is chronological
    results.sort(key=lambda t: (t[2].get("date") or "9999", t[0].name))

    # --- build rename plan ---
    seen: dict[str, int] = {}
    plan: list[tuple[Path, Path, str, dict]] = []  # (pdf, jpg, base_name, data)

    print()
    for pdf_path, jpg_path, data in results:
        base = unique_name(make_base_name(data), seen)
        plan.append((pdf_path, jpg_path, base, data))
        print(f"  {pdf_path.name}")
        print(f"    → {base}.{{pdf,jpg,txt}}")

    if args.dry_run:
        print("\nDry run – no files written.")
        return

    # --- write files ---
    print()
    for pdf_path, jpg_path, base, data in plan:
        txt_path = target_dir / f"{base}.txt"
        jpg_dest = target_dir / f"{base}.jpg"
        pdf_dest = target_dir / f"{base}.pdf"

        txt_path.write_text(make_receipt_text(data), encoding="utf-8")
        shutil.copy2(jpg_path, jpg_dest)
        pdf_path.rename(pdf_dest)
        print(f"  Created: {base}.{{pdf,jpg,txt}}")

    # --- duplicate warning ---
    dupes = [base for base, count in seen.items() if count > 1]
    if dupes:
        print("\n⚠️  Possible duplicate scans (same trip):")
        for d in dupes:
            print(f"   {d}  →  (1) and (2) copies")
        print(
            "   Review both, keep the colour/higher-quality image,\n"
            "   copy the .txt from the kept copy if needed, then delete the other."
        )

    print("\nDone.")


if __name__ == "__main__":
    main()
