Steward issue, 2026-10-22 03:00 refill. Goal: agentic-leverage (skills-akaihola is tier 2). Estimated 1 h. Source: draft D7 of [the 2026-10-22 docs review](../reviews/2026-10-22-docs-review.md#draft-issues).

The `library` skill's cookbooks lose the caller's workspace. `library/cookbook/use.md`, `list.md`, `remove.md` and `sync.md` `cd` into the library checkout and then work out the workspace's target paths from there. `use.md` parses a branch from a GitHub URL but clones the default branch (`git clone --depth 1` without `--branch`), and copies into a target directory it never creates.

## What to do

1. In every cookbook under `library/cookbook/`, work out the workspace context (target paths) before any `cd`, or reach the library with `git -C` and absolute paths so the shell never leaves the workspace.
2. In `use.md` (and any other cookbook that installs), create the target directory before copying, and clone the parsed ref (`--branch <ref>`).
3. Agents and prompts: how they should be laid out is not specified. Leave their current handling and add the open question to [the library backlog](../../library/BACKLOG.md) next to the related entries; don't decide it here.
4. Check each cookbook against `library/SKILL.md` and the catalog, and fix plain mismatches.

## Constraints and acceptance

- Cookbooks and `library/BACKLOG.md` only. No network: walk the changed steps through in a temporary workspace with a local fixture repository standing in for GitHub (`git clone --branch` works on a local path), and record the walk-through in this task record.
- Before merging, run the tests and checks the Rules and `AGENTS.md` ask for.
- Memory: before each command, wait up to 10 minutes for `MemAvailable` of at least 2 GiB; if it doesn't come, start the command anyway when at least 1.5 GiB is available. Stop a running command when `MemAvailable` falls below 1 GiB or swap grows by more than 512 MiB. Run one heavy command at a time, and bound any background job you start.
- Handoff: a short outcome and the checks run; detail goes in this task record.
- Acceptance: no cookbook step computes a workspace path after a `cd` into the library; the walk-through installs a skill from a non-default branch into a fresh target directory; the open layout question is in the library backlog.

Tracker: [the skills-akaihola tracker](../../TASKS.md).


## Task record

Implemented 2026-10-22 in the isolated task worktree.

- **Workspace context:** no cookbook changes directory any more. [use], [list],
  [remove], [sync] and [push] start by printing the caller's workspace root and
  reach the library with `git -C ~/prg/skills-akaihola`; [add] does the same for
  its pull and commit. Each says that shell variables may not carry over between
  commands and should be set again from the printed path. [search] now points to
  the `list` steps it borrows for install status. [install] had no `cd` and is
  unchanged.
- **Installing:** [use] creates the target directory before linking or copying,
  clones the URL's ref with `--branch <ref>` into a `mktemp -d` directory, notes
  that a commit hash needs a full clone and checkout, and asks before replacing
  an existing install: `cp -R` onto an existing directory or symlink nests the
  copy, and through a symlink it writes into the source checkout (checked with a
  throwaway directory). [push] clones the same ref, takes the local copy from the
  recorded workspace root and cleans up in the same command.
- **Plain mismatches fixed:** [sync] claimed one pull updates everything;
  [the skill] says it updates only sources in this repository, so the step and
  its report now separate those symlinks from symlinks to other local sources.
  Its copy listing uses `find ! -type l` instead of `ls -la | grep -v`, which
  also listed `total`, `.` and `..`. [use] no longer calls every install a
  symlink or expands `~` to a fixed home. [add] resolves a relative source path
  against the caller's directory into the absolute or home-relative form the
  catalog uses.
- **Agents and prompts:** handling unchanged. [The library backlog] has a new
  open question, "Decide how agents and prompts are laid out", next to
  "Catalog agents and prompts", which now notes that it is blocked on it.

[use]: ../../library/cookbook/use.md
[list]: ../../library/cookbook/list.md
[remove]: ../../library/cookbook/remove.md
[sync]: ../../library/cookbook/sync.md
[push]: ../../library/cookbook/push.md
[add]: ../../library/cookbook/add.md
[search]: ../../library/cookbook/search.md
[install]: ../../library/cookbook/install.md
[the skill]: ../../library/SKILL.md
[The library backlog]: ../../library/BACKLOG.md

### Walk-through

A throwaway script (kept outside the repository) extracted every fenced `bash`
block from each cookbook and ran them in order, one `bash -e` process per block.
Each block started in the directory the previous one ended in, as an agent's
shell does, and shell variables were set again from printed values as the
cookbooks instruct. Placeholders were filled with fixture values; no network
was used.

- **Fixtures** under `$TMPDIR/hai21-walk-new/`: a bare repository standing in for
  GitHub, whose default branch `main` holds `skills/demo/SKILL.md` with
  `version: main` and whose branch `feature-x` holds `version: feature-x` plus
  `extra.txt`; a bare library origin and its clone standing in for
  `~/prg/skills-akaihola`, with a catalog naming
  `https://github.com/example-org/fixture-skills/blob/feature-x/skills/demo/SKILL.md`
  and a local-path entry; a fresh Git workspace with no `.claude/` directory.
  The agent's shell started in a subdirectory of the workspace.
- **Parsed URL values:** org `example-org`, repo `fixture-skills`, ref
  `feature-x`, parent of file `skills/demo`; the clone URL was replaced by the
  fixture's `file://` URL so `--depth 1` applies.
- **Results with the new cookbooks:** 33 checks passed, none failed. [use]
  printed the workspace root (not the subdirectory), and its pull left the shell
  where it was. Its GitHub block created `.claude/skills/` and installed the
  `feature-x` copy with `extra.txt` and without `.git`; the temporary clone was
  gone afterwards. The local entry was installed as a symlink to its source
  directory. [list] reported the copy and the symlink; [sync] listed only the
  copy. [push] sent a local edit to `feature-x` and left `main` unchanged.
  [remove] and [add] committed and pushed catalog edits to the library origin;
  [remove] unlinked the symlink, kept its source, and warned on the copy. After
  every block the shell was still in the starting directory, and no cookbook
  block contains `cd`.
- **The same walk on `main`'s cookbooks**, for comparison: the first block left
  the shell in the library, the workspace root then came out as the library
  checkout, the inline clone fetched `version: main`, and the copy failed because
  the target directory did not exist; `list` also took the library as the
  workspace. Four checks failed, as expected.

### Checks and review

- `pytest tests -q`: 55 passed, using the shared checkout's virtual environment.
- `python scripts/check_skill_metadata.py`: 48 skill frontmatters valid.
- `python .github/scripts/check_symlinks.py`: passed.
- `git diff --check`: passed.
- Topology check (the CI `git grep`): still matches the five task documents
  that HAI-20 recorded (19, 6, 7, 8 and the adoption proposal); nothing under
  `library/` or in this record matches. Left untouched as out of scope.
- Reviewed the full diff against the issue and the PII checklist: fixture data
  uses `example-org` and `example.org` only.
- Hai loaded all 22 issues with unique stable IDs and references; all 22
  numbered detail links resolve. The start move was committed on shared
  `main` as `bcc773a` and left no uncommitted tracker changes; the worktree
  was rebased onto it.

### Memory record

The checks ran serially through a guard script: 600-second admission window,
2048 MiB normal and 1536 MiB fallback admission, a 300-second timeout, and
process-group termination below 1024 MiB available or above 512 MiB swap
growth. The walk-through runs Git on tiny fixture repositories and was not
treated as heavy. Nothing was stopped or skipped.

- `pytest tests -q`: **started at once**, wait 0.00 s; admission MemAvailable
  2450 MiB, final 2399 MiB; starting swap 2368 MiB, growth 0 MiB; elapsed
  2.50 s; exit 0.
- `python scripts/check_skill_metadata.py`: **started at once**, wait 0.00 s;
  admission 2463 MiB, final 2463 MiB; starting swap 2368 MiB, growth 0 MiB;
  elapsed 0.50 s; exit 0.
- `python .github/scripts/check_symlinks.py`: **started at once**, wait 0.00 s;
  admission 2463 MiB, final 2463 MiB; starting swap 2368 MiB, growth 0 MiB;
  elapsed 0.50 s; exit 0.
- Topology `git grep` over the tree: **started at once**, wait 0.00 s; admission
  2462 MiB, final 2462 MiB; starting swap 2368 MiB, growth 0 MiB; elapsed
  0.50 s; exit 0 for the counting pipeline (the grep matched the pre-existing
  files above).

### Merge and completion

Fast-forwarded `main` to the implementation commit `f227af5`, then moved the
issue to Completed / Accepted through Hai in `1b1ce1d`, with the acceptance
box left unchecked. The tracker then loaded with 22 unique issues and left no
uncommitted changes. The task worktree and branch are kept.

### Follow-ups for the steward

- [The skill] still says to capture the workspace root "before any cookbook
  step changes directory"; no step does now. That sentence could be simplified,
  which this issue's scope (cookbooks and backlog only) did not allow.
