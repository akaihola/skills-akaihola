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
