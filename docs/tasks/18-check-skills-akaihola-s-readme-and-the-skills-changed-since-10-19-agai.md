Steward issue, 2026-10-22 01:58 refill. Goal: agentic-leverage (skills-akaihola is tier 2 on the goals page; agents load these skills, the steward included). Labelled `review` (steward D68). Estimated 1.5 h.

About 50 commits have landed on `main` since 2026-10-19. Since then the files of these skills changed: `t3-start-thread`, `processing-scanned-receipts`, `ecb-rates`, `secrets-scan`, `himalaya-email-manager`, `youtube-transcription`, `read-as-markdown` and `library` (`git log --since=2026-10-19 --name-only main`). A `SKILL.md` that disagrees with its scripts sends every agent that loads it down the wrong path. The same documentation check has run for kandev-pacer, Hai, Filemill, pi-akaihola and mailjail.

## What to do

1. Read `README.md`, `AGENTS.md` and `BACKLOG.md`, and the `SKILL.md` and `references/` of each skill named above, against the code on current `main`: script names, flags and their defaults, environment variables, file layout, test and check commands, and what each document says is done or planned. Check each skill's examples against its script's `--help` where the script runs without credentials or network.
2. Fix plain discrepancies and stale statements in those files. Keep each `SKILL.md` short, with detail behind its references, and keep its frontmatter valid.
3. Where it's unclear whether the code or the text is wrong, don't guess: list it in `docs/reviews/<run date>-docs-review.md` with the evidence and a proposed answer.
4. That file also lists each change you made, by document, with the code it now matches, and ends with a `## Draft issues` section for anything larger than a documentation fix, including other skills' documents you noticed were stale. Don't file those issues; the steward decides.

## Constraints and acceptance

- Documentation only: no script or test changes. Leave task files and earlier reviews as they are, and leave `.claude/CLAUDE.md` alone.
- Don't run a skill against a live service, mailbox or account; `--help`, dry runs and the existing tests only.
- Run `uv run --no-project --with pyyaml python scripts/check_skill_metadata.py` and the Pre-Commit Checklist in `AGENTS.md` before merging.
- Memory: before each command, wait up to 10 minutes for `MemAvailable` of at least 2 GiB; if it doesn't come, start the command anyway when at least 1.5 GiB is available. Stop a running command when `MemAvailable` falls below 1 GiB or swap grows by more than 512 MiB. Run one heavy command at a time, and bound any background job you start.
- Never print a credential's value; name the file and line instead.
- Handoff: a short outcome and the checks run; detail goes in the review file and this task record.
- Acceptance: the review file is on `main`, every document named in step 1 was read, the metadata check passes, and each change it lists names the code it now matches.

Tracker: [the skills-akaihola tracker](../../TASKS.md).
