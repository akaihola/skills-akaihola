# Reviewing receipt output

Implementation: [processing-scanned-receipts/process_receipts.py].

## Post-Processing: Manual Corrections

OCR is good but not perfect. After the script runs, review for:

| Issue | What to fix |
|-------|-------------|
| Unreadable date | Rename files; edit `Päivämäärä:` in `.txt` |
| Company name cut off in scan | Rename files; edit `Yritys:` in `.txt`; `payee_short` is a JSON cache field |
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

When two receipts produce the same complete basename in one run, the script
adds `(2)`, `(3)`, and so on. A matching date/payee with a different
description is not flagged. Existing destination files are not protected
against overwrites; review the cached preview before rerunning. To clean up:

1. View both JPGs to identify which is colour (preferred) and which is B&W.
2. The colour one usually has better information; its `.txt` may say "toinen skannaus" (second scan) – copy the primary's `.txt` content over it if the primary has cleaner notes.
3. Delete the B&W set; rename the colour `(2)` files to drop the `(2)` suffix.

```bash
# Keep colour (2), replace its .txt with primary's, delete primary, rename
trip="2030-01-01 Example taxi synthetic trip"
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
Yritys:        Example taxi
Y-tunnus:      XXXXXXX-X

Päivämäärä:    2030-01-01
Kellonaika:    12:00

------------------------------------------------
MATKAN TIEDOT
------------------------------------------------
Mistä:         Synthetic origin
Minne:         Synthetic destination
Matka:         10.00 km
…
```

[processing-scanned-receipts/process_receipts.py]: ../process_receipts.py
