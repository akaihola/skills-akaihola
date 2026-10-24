Steward issue, 2026-10-25 02:43 refill (steward decisions D43, D68 and D95). Goal: agentic-leverage (skills-akaihola is tier 2 in the steward vault's `pages/Goals.md`). Labelled `review`. Estimated 1 h.

## Why

[The 2026-10-22 docs review](../reviews/2026-10-22-docs-review.md) matched the documents to the code at `278d0d1`. Since then seven source commits changed three skills that agents load: `secrets-scan` fails when a requested scanner doesn't finish; `read-as-markdown` isolates external document caches and reports failures; `t3-start-thread` retired its V1 transport (keeping saved requests readable), reconciles launches and sends through one record path, reuses observed shells when checking messages, consolidated its test fakes, and discovers and trusts the local runtime origin ([28]). An agent follows a skill's text literally, so a stale command, flag, default or failure message there costs a retry in every session that loads it.

## What to do

1. List the source commits since `278d0d1` (`git log --no-merges --reverse 278d0d1..main -- . ':!docs' ':!*.md'`) and, for each, what it changed in commands, flags, defaults, files written, messages or failure behaviour.
2. Read `README.md`, `AGENTS.md`, and the `SKILL.md` and `references/` files of `t3-start-thread`, `read-as-markdown` and `secrets-scan` against current `main` for those changes.
3. Fix plain discrepancies and stale statements. Where two documents explain the same thing, keep one explanation and link to it from the other. Prefer shorter text: delete statements the code no longer supports rather than adding caveats. Keep every rule, warning and runnable example that is still true; a skill's instructions change only where they are wrong or duplicated.
4. Where it's unclear whether the code or the text is wrong, don't guess: list it with the evidence and a proposed answer in `docs/reviews/<run date>-docs-recheck.md`. That file also lists each change you made, by document, with the commit or code it now matches, and ends with a `## Draft issues` section for anything larger than a documentation fix. Don't file those issues; the steward decides.

## Constraints

- Documentation only: no script or test changes, except a formatting-only change a required check demands. Leave task files and earlier reviews as they are.
- Don't send, settle or launch any T3 thread, and don't run a scanner over another repository.
- Keep private paths out of committed docs and code; the check receipt is exempt.
- Memory: follow your launch prompt's memory rule. Run one heavy command at a time.

## Acceptance

- The review file is on `main`, every document named in step 2 was read, and each change it lists names the commit or code it now matches.
- The diff touches only Markdown outside `docs/tasks/` and `docs/reviews/`, plus this task's record and the new review file.
- The tests `AGENTS.md` asks for, including `tests/test_secrets_scan.py`, `tests/test_read_as_markdown.py` and the `t3-start-thread` tests, pass before merging. Handoff: a short outcome; details go in the review file and this task record.

Tracker: [skills-akaihola's tracker](../../TASKS.md).

[28]: 28-let-the-t3-helper-find-and-authenticate-to-the-local-server-when-it-is.md
