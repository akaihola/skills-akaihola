Steward issue, 2026-10-19. Goal: agentic-leverage; skills-akaihola is tier 2.

From draft D18 of `docs/reviews/2026-10-19-skills-review.md` (the review in skills-akaihola [9]), which ranks it among the first to do. The draft follows as the reviewer wrote it; read the review's other sections only if this one points there.

## Draft

Evidence: `processing-scanned-receipts/SKILL.md:41` promises a write-free
preview. `processing-scanned-receipts/process_receipts.py:282` creates the
work directory, `processing-scanned-receipts/process_receipts.py:296` submits
OCR work, and `processing-scanned-receipts/process_receipts.py:326` checks
`dry_run` only afterward. `processing-scanned-receipts/process_receipts.py:116`
invokes the paid OCR CLI. This was traced statically; no receipts were processed.

Draft title: **Make receipt dry-run use cached metadata without side effects.**
Work: check preview mode before directory creation or extraction; use existing
metadata to show renames and report cache misses explicitly. Acceptance: with
synthetic cached and uncached inputs, dry-run performs no subprocess calls,
creates no files and preserves source hashes; normal processing still works
with mocked OCR. Benefit: previews become safe cost-free checks. Estimate:
1 hour. Overlap: none.

## Steward's constraints

- Never call the paid OCR CLI or process real receipts; use mocks and synthetic files.

## Done when

The draft's acceptance holds, lint and tests pass, and the change is merged to `main` as the Rules describe. No push or deploy.
