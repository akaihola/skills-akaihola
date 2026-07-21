---
name: fleet-audit
description: Check whether every deployment of a skills repo is current across a fleet of accounts and machines. Use when the user asks "are my skills up to date everywhere", "audit skill deployments", "find stale or broken skill links", or after changing how skills are deployed. Reports only anomalies — stale checkouts, broken symlinks, cross-user absolute links, and copies that have drifted from the repo.
---

# fleet-audit

Answers one question in one command: **is every deployment of this skills repo
current?**

Skills get deployed to many places — a user-level `~/.claude/skills/`, per-project
`.claude/skills/`, other harnesses' surfaces (`~/.codex/skills/`), plugin
marketplace caches, and other accounts entirely. Each is a symlink farm or a copy
that can silently rot. Sweeping them by hand costs a lot of output for a handful
of real findings, so this skill sweeps them mechanically and prints **only the
anomalies**.

## Usage

The fleet definition is a private TOML file the caller supplies — this skill
ships no hostnames, accounts, or paths of its own.

```bash
fleet-audit/scripts/audit.py path/to/fleet.toml
```

Start from `references/fleet.example.toml`. Keep the real one outside any public
repo, next to your other environment/topology notes.

Exit status is `0` when everything matches and `1` when anything is off, so it
works as a cron job or CI step. Progress goes to stderr, findings to stdout;
`--quiet` suppresses the progress lines.

## What it reports

| Finding | Meaning |
| --- | --- |
| `stale-checkout` | A clone's HEAD differs from the canonical ref. |
| `dirty-checkout` | Tracked modifications in a deployed clone. |
| `broken-link` | A skill symlink whose target does not resolve. |
| `external-link` | An absolute symlink pointing outside the account's own `$HOME` — works for one user, dead for every other. |
| `drifted-copy` | A copied skill directory whose contents no longer match the repo. |
| `copy-not-link` | A copy that matches the repo *today*. Not yet broken, but nothing keeps it that way. |

Anything not on this list is not printed. A clean fleet produces one `OK` line.

## How it works

For each target the script pipes one shell scanner over `ssh … bash -s` (run
locally for the local account) and parses its TSV output. The scanner:

1. finds clones of the repo by matching `remote.origin.url` against `repo.slug`;
2. finds every configured surface under `$HOME`;
3. reports only entries whose name is a skill in the repo, or whose symlink
   target mentions the repo — everything else in those directories (third-party
   skills, vendored marketplaces) is filtered out at the source rather than
   shipped back and discarded.

Copies are compared by a digest over relative path plus content. The **same
shell function** computes the digest on the targets and on the canonical
checkout, so the two sides can never disagree because of an implementation
mismatch.

## Design notes

- **Filter at the source.** The scanner discards irrelevant entries before they
  cross the wire. An unfiltered sweep returns hundreds of lines to find a
  handful of problems.
- **One round trip per account.** Discovery, hashing, and git state come back in
  a single scanner run rather than a conversation of individual probes.
- **Symlinks beat copies.** With symlink-only deployment this question reduces
  to `git rev-parse` in N clones. Copies force a content hash of every tree, and
  they are the only deployments that can drift without anyone touching them —
  hence `copy-not-link` is reported even when the copy is currently correct.

## Related

Keeping links *relative* is what stops `external-link` findings from being
created in the first place; `.github/workflows/check-symlinks.yml` in this repo
enforces that for committed symlinks.
