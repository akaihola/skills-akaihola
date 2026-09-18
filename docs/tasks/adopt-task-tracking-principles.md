# Adopt modern task-tracking principles

Status: backlog
Requested by: user, 2026-09-18

## Reference principles

Compare the current `TASKS.md` rules in these repositories:

- `/home/agent/prg/kandev-pacer`
- `/home/agent/prg/filemill`
- `/home/agent/prg/kandev-config`
- `/home/agent/prg/syncop`

Adopt their principles, resolving differences rather than copying a tracker
verbatim. Use an Astra- or Fable-class model for the design and migration.

- Separate unverified ideas from reviewed, ordered work. Only a human promotes
  proposals; deduplicate exact proposals and consolidate overlapping ones.
- Give each issue one canonical record and one lifecycle state: proposal,
  backlog, scheduled, in progress, completed, or human-accepted. Define how the
  existing format represents these states and when human-accepted records and
  their obsolete detail files are retired.
- Select only reviewed, unblocked backlog work. Record explicit dependencies,
  keep ordering consistent, and exclude already scheduled or active work.
- Keep simple items concise; link stable identifiers to detailed descriptions
  and acceptance criteria when needed. Keep dependency metadata consistent.
- Commit scheduling on the base branch. Rebase a task worktree before changing
  its state, do implementation there, and record completion after merge.
- Preserve identifiers, text, and wrapping during state moves. Resolve tracker
  conflicts from the base branch, reapply only the current issue's move, and
  check that no issue appears twice. Document maintenance and validation.

## Repository adaptation

Keep root `BACKLOG.md` for repository-wide work and `library/BACKLOG.md`
for library-specific work. Extend their headings and explicit status fields;
do not duplicate skill-owned issues in a central queue. Preserve existing ideas
as unverified, give cross-skill dependencies explicit references, and document
how agents or an existing scheduler find approved work in both scopes. Keep the repository's privacy
rules when writing examples or descriptions.

## Done when

Agent instructions identify the authoritative tracker and its review boundary.
The existing mechanism documents the adopted lifecycle, review gate, dependency
selection, and Git workflow. Every prior item retains its meaning and state;
all detailed links resolve and no issue has multiple canonical records. Verify
a sample scheduling/start/completion transition and conflict resolution without
actually starting unrelated work. Record any deliberate differences from the
reference rules.
