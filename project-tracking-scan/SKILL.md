---
name: project-tracking-scan
description: >-
  Scan Claude Code and Codex session logs for coding work done since the last
  scan, then create or refresh the matching project tracking notes in the
  vault. Use when the user asks which projects they have been working on
  recently, wants project tracking documents brought up to date, asks for a
  periodic or incremental project review, or says "scan since last time".
  Records a per-machine timestamp so each run covers only new work.
---

# Project tracking scan

Answers "what have I been working on, and which tracking notes are out of
date?" — then updates the notes. The scan is incremental: each run covers
work since the previously recorded scan.

## Workflow

### 1. Scan

```bash
cd <this skill dir>
uv run scripts/scan.py --vault agent@gogo:my-knowledge
```

The script does the deterministic half: reads both harnesses' session logs,
groups sessions by git repository, counts commits, lists existing tracking
docs, and prints a Markdown report. `--json` gives the same data machine-
readably. `--since 2026-06-18` overrides the window; `--show-state` prints
the recorded timestamp without scanning.

With no `--since` and no recorded state it falls back to a 28-day window.

### 2. Confirm scope with the user

Present the table and let the user pick which projects to track — not every
directory with sessions deserves a note. Scratch experiments, throwaway
worktrees and one-off questions usually do not. Ask rather than guess; the
`*(dir gone)*` and zero-commit rows in particular are often noise.

### 3. Research each chosen project

The script deliberately does **not** write the notes. It reports activity,
not meaning. Before writing, read the repo: `README.md`, any in-repo plan or
progress docs, `AGENTS.md`/`CLAUDE.md`, `.claude/memory/`, and the actual
commit subjects and bodies. A note that only restates commit counts is worse
than no note.

### 4. Write or update the notes

Notes live in `<vault>/pages/Projects/`. Match the existing conventions:
frontmatter (`type: project`, `status`, `priority`, `roadmap_col`, `created`,
`last_updated`, `tags`, `related`), then Purpose, Current state, Significant
insights, Next, Related. Add an entry to `_index.md` under the right status
heading.

Check the vocabulary in use before inventing values — `status` is one of
Active / Planning / On Hold / Maintenance / Completed / Abandoned, and
`roadmap_col` one of now / next / later / icebox / done.

Wikilinks resolve **vault-wide by filename**, not by heading and not per
directory. `[[Some Note]]` needs `Some Note.md` to exist somewhere in the
vault; when a file's title differs from its filename, link
`[[filename|Title]]`. Verify links resolve against the whole vault before
concluding one is broken.

### 5. Record the scan

Only after the notes are written:

```bash
uv run scripts/scan.py --record --since <same window>
```

`--record-time <ISO>` backfills a specific stamp. Recording before the notes
are done means the next scan silently skips that work.

## What the script will not tell you

Judgement the report cannot make, and past scans got wrong:

- **A renamed project looks like two.** Sessions before and after a rename
  land under different roots; only the commit history reveals they are one
  project.
- **A deleted worktree whose parent repo is also gone** cannot be resolved
  and shows as its own ghost row.
- **Commits are not landings.** A project with sessions and zero commits may
  mean lost work — check whether any branch holds it before assuming
  progress.
- **A note can describe a project that no longer exists.** Verify the
  architecture a stale note claims is still real before refreshing it;
  planned infrastructure is often never built, or built differently.

## Traps

- **Never count session files** — one conversation writes many, because
  subagent and sidechain logs share the parent's session id. One session was
  observed to have written 215 files. The script counts distinct session ids;
  a raw `ls | wc -l` overstates activity by an order of magnitude.
- **Never filter session logs by mtime.** Whole log directories routinely
  carry fresh mtimes from syncs and rewrites, so mtime cannot distinguish
  recent work from old. Only the in-file timestamps are trustworthy. The
  script uses them.
- **`git log ... | wc -l` in a shell may be truncated** by output-filtering
  wrappers, undercounting silently. The script calls git directly and is
  unaffected; if verifying by hand, use `rtk proxy git ...`.
- The timestamp is **per-machine**: session logs only exist on the host that
  ran the agent. A scan on one host says nothing about another. Run the scan
  where the work happened.
- The vault may not be on this machine, and a local copy may be stale. Prefer
  `--vault user@host:path` and check the live copy's git log before trusting
  a local one.

## State

`--record` writes `$XDG_STATE_HOME/project-tracking-scan/state.json`
(default `~/.local/state/...`), holding `last_scan`, `host` and
`previous_scan`. It is kept out of this repo because it names private
projects.
