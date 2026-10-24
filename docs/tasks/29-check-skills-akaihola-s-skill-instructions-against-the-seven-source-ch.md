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

## Implementation record

Read all eight requested documents and the seven source commits. Corrected
T3 discovery/authentication and exception guidance, removed a private
preference-path assumption, and consolidated repeated settings, cache and
scanner explanations. Preserved valid rules and examples; production scripts,
tests, other task records and earlier reviews are unchanged. The
[documentation recheck][recheck] maps every edit to code and records one
unfiled proposal for nested scanner-result validation. No coordination message,
thread mutation or repository scan was performed.

### Checks before merge

- **Regression suites:** 158 passed across the required scanner, converter
  and T3 suites, plus metadata and security-boundary tests.
- **Metadata:** 48 tracked skill frontmatters validated.
- **Help:** eight offline parser probes passed (T3 root and its five
  subcommands, converter and scanner).
- **Documents:** all eight requested source documents read; local links,
  heading lengths, diff whitespace, allowed file scope, new-text privacy and
  committed symlinks passed. A manual diff review checked preservation of
  warnings and runnable examples.
- **Tracker:** Hai read found 29 unique issues with resolving detail links;
  this issue was In Progress and unaccepted after start commit `f35e0f6`.

The repository has no lockfile. An external requirements lock pins the test
packages; it and the document-check helper are declared SHA-256 dependencies
in the evidence receipt. No editable package was used. Test execution is
network-isolated; dependency preparation alone used package-network access.
An initial offline preparation failed because Typer was absent from the UV
cache. A first attempted regression command also stopped during dependency
resolution, before tests, because a provisional freeze included unrelated
system packages. Compiling a dedicated requirements lock fixed that setup;
the subsequent 158-test run passed. Neither failure was a test failure.

Reproduction commands from the repository root; `CHECKS` denotes the external
check-artifact directory named in the receipt. The document helper validates
this task's allowed diff, links, headings and new-text privacy.

```bash
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH= PYTHONNOUSERSITE=1
unshare -rn uv run --offline --no-project --with-requirements "$CHECKS/requirements.lock" python scripts/check_skill_metadata.py
unshare -rn uv run --offline --no-project --with-requirements "$CHECKS/requirements.lock" pytest -p no:cacheprovider tests/test_skill_metadata.py tests/test_secrets_scan.py tests/test_read_as_markdown.py tests/test_security_boundaries.py t3-start-thread/tests -q
unshare -rn uv run --offline --no-project --with-requirements "$CHECKS/requirements.lock" bash -e <<'BASH'
python t3-start-thread/scripts/start_thread.py --help
for action in inspect start send settle resume; do
  python t3-start-thread/scripts/start_thread.py "$action" --help || exit
done
python read-as-markdown/scripts/read_as_markdown.py --help
python secrets-scan/scripts/scan.py --help
BASH
python3 "$CHECKS/check-docs.py"
python3 .github/scripts/check_symlinks.py
git diff --check
```

### Memory before merge

Heavy commands ran sequentially with a 600-second admission limit (2,048 MiB,
then a 1,536 MiB fallback). The guard polled every 0.2 seconds and stopped the
process group below 1,024 MiB available or above 512 MiB swap growth. Commands
had 120–300-second timeouts and process-group cleanup. No fallback or running
stop occurred. These measurements contain no command output.

| Command | Outcome | Wait (s) | Admission / final available (MiB) | Starting swap / growth (MiB) | Elapsed (s) | Status |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Offline dependency preparation | started at once | 0.0 | 57583.3 / 57588.6 | 0.5 / 0 | 0.2 | exit 1 |
| Online dependency preparation | started at once | 0.0 | 57611.4 / 57590.2 | 0.5 / 0 | 0.4 | exit 0 |
| Initial regression command (resolution only) | started at once | 0.0 | 57597.2 / 57586.6 | 0.5 / 0 | 0.2 | exit 1 |
| Compile dedicated requirements lock | started at once | 0.0 | 57561.6 / 57565.5 | 0.5 / 0 | 0.2 | exit 0 |
| Regression suites | started at once | 0.0 | 57584.7 / 57560.5 | 0.5 / 0 | 2.81 | exit 0 |
| Metadata validator | started at once | 0.0 | 57709.9 / 57706.6 | 0.5 / 0 | 0.2 | exit 0 |
| Eight help probes | started at once | 0.0 | 57706.6 / 57649.1 | 0.5 / 0 | 0.8 | exit 0 |
| Document and symlink checks | started at once | 0.0 | 57658.2 / 57651.7 | 0.5 / 0 | 0.2 | exit 0 |
| Final document and symlink checks | started at once | 0.0 | 57690.6 / 57685.6 | 0.5 / 0 | 0.2 | exit 0 |

[recheck]: ../reviews/2026-10-25-docs-recheck.md
