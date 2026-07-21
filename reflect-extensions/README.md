# reflect-extensions

A session retrospective for Claude Code that turns what just happened into
durable improvements to your setup.

It does the full six-surface audit:

1. **Capture as you go.** A `UserPromptSubmit` hook nominates candidate learnings
   — corrections, standing preferences, failure reports — into a per-session
   queue, so a correction survives compaction and abandoned sessions.
2. **Extract learnings** from the session and the queue — trial-and-error fixes,
   reusable ad-hoc scripts, successful new workflows, and conventions worth
   keeping.
3. **Audit which extensions were used** this session — skills, MCP servers,
   slash commands, subagents, hooks, and plugins — and how each performed.
4. **Reconcile the config that already exists** against what the session actually
   did: contradictions, stale references, redundancy, description drift.
5. **Map each learning to the right surface**, behind a confidence gate, and
   propose either a new extension or an edit to an existing one — applied only
   after human approval.

## Contents

| Path | Purpose |
|------|---------|
| `commands/reflect-extensions.md` | The `/reflect-extensions` slash command |
| `hooks/hooks.json` | UserPromptSubmit capture + Stop / PreCompact reminder + SessionEnd cleanup |
| `scripts/capture_learning.py` | Queues candidate learnings as they happen |
| `scripts/reflect_extensions_reminder.py` | Debounced end-of-session reminder |

## Install (as a plugin)

```bash
# Add this repo as a plugin marketplace, then install the plugin
claude plugin marketplace add akaihola/skills-akaihola
claude plugin install reflect-extensions@skills-akaihola
# Restart Claude Code so the hooks load
```

## Usage

```
/reflect-extensions               # audit the current session, propose changes
/reflect-extensions --dry-run     # analyse and propose, write nothing
/reflect-extensions --scope global
/reflect-extensions --min-confidence 0.8   # stricter gate on what gets written
```

The reminder hook nudges you to run it at the end of a working session. It is
debounced: at most once per session, and only after meaningful work (a threshold
of edits, commits, skill/subagent, and MCP calls) *or* at least one queued
learning. `SessionEnd` removes the per-session marker and prunes stale state.

## Capture queue

`capture_learning.py` matches each submitted prompt against cheap regexes
(English and Finnish) for four signal families, and appends any hit to
`~/.claude/reflect-extensions/queue/<session-id>.jsonl`:

| Kind | Confidence | Example trigger |
|------|-----------|-----------------|
| `correction` | 0.90 | "no, use ripgrep instead", "älä käytä pip:iä" |
| `preference` | 0.85 | "from now on always run nextest" |
| `failure` | 0.75 | "that didn't work, still failing" |
| `praise` | 0.60 | "exactly, that's what I meant" |

The hook deliberately over-captures: it is cheap and runs on every prompt, so it
only *nominates*. `/reflect-extensions` applies the semantic filter later, when
it can see what actually happened around each record. Records store a redacted,
truncated excerpt — credential-shaped strings are replaced before anything is
written to disk.

Queues outlive their session on purpose, so `--session <id>` and `--days N` can
drain them later. They are pruned after `REFLECT_EXT_MARKER_TTL_DAYS`.

### Confidence gate

A learning's confidence decides how permanent a home it can earn. Above the
threshold (`--min-confidence`, default `0.7`) it may be written to an on-demand
surface; reaching an always-on file (`CLAUDE.md`, `AGENTS.md`, global rules) also
requires **two independent observations**. Anything below goes to a backlog file
instead of into your context budget.

## Reminder configuration (env vars)

| Variable | Default | Effect |
|----------|---------|--------|
| `REFLECT_EXT_MIN_ACTIONS` | `3` | Minimum meaningful actions to trigger on Stop |
| `REFLECT_EXT_REMIND_ONCE` | `1` | At most one reminder per session |
| `REFLECT_EXT_PLAINTEXT` | unset | `1` prints plain text instead of `systemMessage` |
| `REFLECT_EXT_MARKER_TTL_DAYS` | `7` | Prune marker files and drained queues older than N days |

## Capture configuration (env vars)

| Variable | Default | Effect |
|----------|---------|--------|
| `REFLECT_EXT_CAPTURE` | `1` | `0` disables the capture hook entirely |
| `REFLECT_EXT_QUEUE_MAX` | `200` | Max records kept per session |
| `REFLECT_EXT_EXCERPT_LEN` | `300` | Max characters of prompt stored per record |
| `REFLECT_EXT_CONFIDENCE_THRESHOLD` | `0.7` | Default confidence gate |

## Notes

- Both scripts are pure standard library; no dependencies.
- Hooks never block and always exit 0 on error.
- Inspired by the hook wiring and hybrid regex/semantic detection in
  [`claude-reflect`](https://github.com/BayramAnnakov/claude-reflect), the
  confidence-scored promotion in [`ECC`](https://github.com/affaan-m/ECC), and
  the config-reconciliation phase in
  [`reflect-skill-claude`](https://github.com/hansvangent/reflect-skill-claude).
