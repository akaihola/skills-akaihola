# Pre-flight triage

Remove noise from the working tree before grouping real work into commits.

Three scripts automate the mechanical parts. All read the workspace config
automatically (`--config PATH` to override, `--json` for machine-readable
output):

```bash
uv run --with pyyaml scripts/co_triage.py [REPO_DIR]          # usage + classification table
uv run --with pyyaml scripts/co_ignore.py [REPO_DIR]          # propose .gitignore + git rm --cached
uv run --with pyyaml scripts/co_ignore.py --apply [REPO_DIR]  # apply them
```

## Classify

`co_triage.py` sorts every uncommitted file by size and line churn and marks it
ignorable or intentional. Act on each category:

| Category | Examples | Action |
| --- | --- | --- |
| Runtime state / logs | `heartbeat-state.json`, `sessions/*.jsonl` | `.gitignore` + `git rm --cached` |
| Generated output | `outputs/`, `tmp/`, rendered HTML, downloaded PDFs | `.gitignore` |
| Moved / reorganized | deletions with matching additions elsewhere | stage both together |
| Intentional content | notes, source, config | keep for grouping |

Where the workspace config has `ignore` patterns, check them first and flag any
matching file that is still tracked.

## Untrack and commit the cleanup

`.gitignore` only stops *new* files from being tracked; it does not affect files
already in history. Use `git rm --cached -- <paths>` to keep them on disk while
dropping them from the index.

Commit the cleanup on its own, before any content work:

```bash
git add .gitignore
git commit -m "chore: update gitignore and untrack generated files"
```

Triage is done when every remaining uncommitted file is intentional content.
