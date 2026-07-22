---
name: commit-organizer
description: Organize a messy working tree into a series of cohesive conventional commits, ordered by modification time.
disable-model-invocation: true
allowed-tools: Bash(git:*)
---

Go through all uncommitted changes in the repository at `$ARGUMENTS` (or the current directory if no path was given) and create a series of commits with clear Conventional Commit messages.

## When not to use

Skip this workflow if one obvious commit is enough, the user wants a single squashed commit, or the tree has unresolved conflicts or half-finished work that should be cleaned up first.

## Inspect the tree

On Claude Code the two commands below run automatically and their output is injected here — rely on it. **If the blocks are empty** (opencode, Roo, or any harness without the injection syntax), run the same commands yourself with your shell tool before proceeding.

!`git -C ./$ARGUMENTS --no-pager status --short --untracked-files=all`

!`git -C ./$ARGUMENTS --no-pager diff --stat`

The diff above is a `--stat` overview only, so a large lockfile or bulk deletion doesn't dump hundreds of KB into context. Pull full hunks per file yourself (`git -C <path> --no-pager diff -- <file>`) for the groups you are actually building.

Use `git -C <path>` throughout to avoid changing the working directory.

## Triage first when the tree is noisy

Generated artifacts, runtime state and large binaries pollute commit groups. When the tree holds any of that, run the triage pass in [`TRIAGE.md`](TRIAGE.md) and commit the cleanup **before** organizing real work.

Skip triage when the tree is small, all changes are clearly intentional, or the user says to skip it.

## Load workspace config

Before grouping, look for a config file in this order:

1. `.ai/commit-organizer.yml`
2. `.commit-organizer.yml`

It may supply path-based grouping buckets, default types and scopes, `keepSeparate` hints, `ignore` patterns for generated noise, and naming hints. See [`examples/commit-organizer.yml`](examples/commit-organizer.yml).

Treat it as heuristics, not hard law: if a strict config rule would produce a worse split, keep the logical boundary and explain the exception.

## Group by cohesion

Group files into cohesive commit sets, favouring **cohesion over proximity**. Useful signals: same project, same tool or service area, same content type, same rename or deletion event, same time-intention batch.

- Split a group when a directory mixes unrelated intents. If one file's hunks belong to different intents, stage them separately with `git add -p`.
- Merge only when several files clearly represent one conceptual change.
- Stage **one group at a time**, and only that group's files.
- Rewrite code only where it is needed to make commit boundaries clean.

For message content and formatting — `type(scope): subject` rules, body guidance, agent identity, the `git commit -F-` heredoc and the `Co-Authored-By` trailer — follow the `commit` skill. This skill decides only how changes are *grouped and ordered*.

## Order chronologically

Order the commit groups by file modification time, oldest first. Where a workspace config defines buckets, `uv run --with pyyaml scripts/co_plan.py [REPO_DIR]` does this mechanically — it assigns files to buckets, computes mtimes and emits the ordered plan (`--json` for machine-readable output). Treat its output as a proposal and correct it where cohesion demands.

- Modified and untracked files: use the on-disk mtime.
- Deleted files: use `git log -1 --format=%ci -- <path>`.
- Each group's ordering key is the **oldest** mtime among its files.
- If a file splits across groups, keep the logical split and place each commit as close as possible to the file's chronological position.
- Where strict chronology would break a coherent change apart, keep the logical boundary and say why before committing.

Standalone deletions with no related additions usually earn their own cleanup commit. Renames belong with the content batch they serve, not in a rename-only commit.

## Report

Before committing, show the planned groups in creation order, each with a short rationale and its ordering basis. Name anything that could not be grouped cleanly, and why.

Creating commits is done when every intended change is committed, the planned list has been shown, and `git -C <path> --no-pager status --short` is empty. Finish by showing the created commits with their short hashes.

Do not push, create branches, or open PRs.
