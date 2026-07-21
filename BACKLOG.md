# skills-akaihola Backlog

Ideas and high-level plans for new skills, repo-wide workflow improvements, and cross-skill infrastructure.

---

## Ideas

### JMAP mail skill backed by mailjail
**Status:** idea

Create a dedicated `jmap` skill for reading and triaging mail through the local `mailjail` JMAP proxy, with multi-account use as a first-class design goal.

Why this is interesting:
- A direct JMAP skill would let the agent list, search, inspect, and summarize mail without ad-hoc curl or Python snippets.
- `mailjail` already exposes a useful localhost JMAP surface, but today it appears to model only a single IMAP account per server process.
- A shared skill would make mail workflows reusable across workspaces instead of depending on local session knowledge.

High-level plan:
- Clarify the skill UX: expected commands such as list today’s mail, filter by sender, fetch previews, show full message, and summarize across accounts.
- Decide the first multi-account architecture: one `mailjail` instance per account with aggregation in the skill, or future native multi-account support in `mailjail`.
- Add a skill-specific privacy model so sender names, addresses, and message content are only surfaced when the user explicitly asks.
- Define failure handling for partial results, unavailable accounts, auth failures, and rate/size limits.
- After `mailjail` has a stable multi-account story, draft `SKILL.md` usage guidance and any helper scripts the skill needs.
