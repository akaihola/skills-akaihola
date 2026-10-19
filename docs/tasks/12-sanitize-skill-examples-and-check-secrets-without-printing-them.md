Steward issue, 2026-10-19. Goal: agentic-leverage; skills-akaihola is tier 2.

From draft D2 of `docs/reviews/2026-10-19-skills-review.md` (the review in skills-akaihola [9]), which ranks it among the first to do. The draft follows as the reviewer wrote it; read the review's other sections only if this one points there.

## Draft

Evidence: `processing-scanned-receipts/SKILL.md:22`,
`processing-scanned-receipts/SKILL.md:77` and
`processing-scanned-receipts/SKILL.md:100` contain person/business/travel
examples. `youtube-transcription/SKILL.md:143` tells the agent to echo its API
key, and `youtube-transcription/SKILL.md:188` embeds named-person examples.
`claude-session-logs/SKILL.md:54` and `claude-session-logs/SKILL.md:66` include
conversation-like samples. Their provenance is unverified; replace them with
clearly synthetic material. The repository's `AGENTS.md:5` requires protection
of personal information. Identifying values are deliberately not repeated here.

Draft title: **Sanitize skill examples and check secrets without printing them.**
Work: replace identifying content with generic synthetic fixtures and reserved
example domains; replace key echoing with a presence-only check; review the
adjacent references/scripts for the same examples. Acceptance: no copied
personal or message content in changed examples, no command prints a credential,
and a before/after diff passes the repository privacy review. Benefit: prevents
examples and troubleshooting from propagating private content. Estimate:
1 hour. Overlap: none; a current-tree cleanup, not a history rewrite.

## Steward's constraints

- Don't quote the identifying values you remove in commit messages, notes or the issue file.

## Done when

The draft's acceptance holds, lint and tests pass, and the change is merged to `main` as the Rules describe. No push or deploy.
