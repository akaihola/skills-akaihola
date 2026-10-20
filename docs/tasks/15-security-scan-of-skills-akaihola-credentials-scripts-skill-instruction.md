Steward issue, 2026-10-20 22:30. Goal: agentic-leverage (skills-akaihola is tier 2 on [the goals page](http://hopeli/my-knowledge/pages/Goals.md?f)). Labelled `security` (security reviews stay on Claude, steward decision D68). Estimated 1.5 h.

Agents load these skills and run their scripts, often with the agent account's full access and sometimes unsandboxed. Several skills handle credentials: `t3-start-thread` mints T3 sessions and drives other threads; `jmap`, `himalaya-email-manager` and `email-mailbox-analyzer` reach mailboxes; `asana`, `brave-search`, `gemini-vision`, `nano-banana-image` and `context7-skill` use API keys; `fleet-audit`, `sync-plugin-cache`, `library` and `rebase-all` change other repositories and caches. The repository had a skills review on 2026-10-19 ([docs/reviews/2026-10-19-skills-review.md](../reviews/2026-10-19-skills-review.md)) but never a security review. A whole-repository scan is on [the steward's improvement menu](http://hopeli/my-knowledge/agents/steward/spare-quota.md?f).

## Work

1. Use the `security-review` skill over the tree, starting with the skills named above, then every other skill with a `scripts/` directory, then `scripts/`, `tests/` and `.github/`.
2. Look for: a token, session or API key that can reach output an agent prints, a log, a cache file or a commit; secret files written without owner-only permissions; shell commands built from untrusted text (web pages, emails, tracker text, thread messages) without quoting; instructions in a `SKILL.md` that would have an agent run fetched content, disable its sandbox or skip a confirmation without need; destructive git or file operations that could touch work they shouldn't; network calls to hosts taken from input without checks; and secrets committed in the tree or history (`git log -p` searches: name the file and commit, never the value).
3. Write the report to `docs/reviews/2026-10-21-security-review.md`: findings ranked by impact and likelihood, each with file and line evidence, and a drafted issue (title, work, acceptance) for each fix worth making. Link paths as relative links. Don't fix anything in this issue.
4. A live credential in the tree or history is urgent: say so first in your completion message, with its location only.

## Acceptance

- The report exists, covers every area in step 1 or says why it was skipped, and drafts an issue for each finding worth fixing.
- No secret value appears in the report, the commit or the thread.
- Read-only: no code change, credential use, network call to a service, push or service restart. Don't read `~/.config/secrets/` or credential files; the code tells you how they're used.
