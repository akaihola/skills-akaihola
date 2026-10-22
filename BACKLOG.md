# skills-akaihola Backlog

Ideas and high-level plans for new skills, repo-wide workflow improvements, and cross-skill infrastructure.

---

## Ideas

### JMAP mail skill backed by mailjail
**Status:** idea; an initial workspace-specific reference exists

Generalize the existing [jmap/SKILL.md] into a portable `jmap` skill for reading and triaging mail through the local `mailjail` JMAP proxy, with multi-account use as a first-class design goal.

Why this is interesting:
- A direct JMAP skill would let the agent list, search, inspect, and summarize mail without ad-hoc curl or Python snippets.
- The existing reference assumes a local tunnel and a fixed account default. Its sync helper lives in another workspace and is not bundled here; current proxy capabilities need separate verification.
- A shared skill would make mail workflows reusable across workspaces instead of depending on local session knowledge.

High-level plan:
- Clarify the skill UX: expected commands such as list today’s mail, filter by sender, fetch previews, show full message, and summarize across accounts.
- Decide the first multi-account architecture: one `mailjail` instance per account with aggregation in the skill, or future native multi-account support in `mailjail`.
- Add a skill-specific privacy model so sender names, addresses, and message content are only surfaced when the user explicitly asks.
- Define failure handling for partial results, unavailable accounts, auth failures, and rate/size limits.
- After verifying the proxy’s multi-account capabilities, replace the workspace-specific guidance and bundle any helper scripts the skill needs.

Amendment from [the README alignment task] (2026-10-22):

- [jmap/SKILL.md] directs agents to a workspace-relative sync helper
  that is not bundled in this repository, and assumes a fixed account and a reverse SSH tunnel on port
  8895. Treat helper packaging, configurable account/base URL and tunnel
  prerequisites as portability acceptance criteria for this existing proposal.
  Verify these against the actual proxy before replacing the guidance.

## Ordered backlog

### Adopt modern task-tracking principles

**Status:** backlog, user-requested; tracker adoption is partial

[TASKS.md] and [AGENTS.md] now define the canonical pacer workflow. Migration
of these older planning records and [library/BACKLOG.md] remains pending; the
[adoption task] still describes the earlier distributed-backlog proposal.
Reconcile that proposal before changing its acceptance criteria.

[jmap/SKILL.md]: jmap/SKILL.md
[TASKS.md]: TASKS.md
[AGENTS.md]: AGENTS.md
[library/BACKLOG.md]: library/BACKLOG.md
[adoption task]: docs/tasks/adopt-task-tracking-principles.md

[the README alignment task]: docs/tasks/22-make-the-himalaya-email-manager-readme-match-its-five-wrappers.md
