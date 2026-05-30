# reflect-extensions

A session retrospective for Claude Code that turns what just happened into
durable improvements to your setup.

It does the full six-surface audit:

1. **Extract learnings** from the current session — trial-and-error fixes,
   reusable ad-hoc scripts, successful new workflows, and conventions worth
   keeping.
2. **Audit which extensions were used** this session — skills, MCP servers,
   slash commands, subagents, hooks, and plugins — and how each performed.
3. **Map each learning to the right surface** and propose either a new extension
   or an edit to an existing one, applied only after human approval.

## Contents

| Path | Purpose |
|------|---------|
| `commands/reflect-extensions.md` | The `/reflect-extensions` slash command |
| `hooks/hooks.json` | Stop / PreCompact reminder + SessionEnd cleanup |
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
```

The reminder hook nudges you to run it at the end of a working session. It is
debounced: at most once per session, and only after meaningful work (a threshold
of edits, commits, skill/subagent, and MCP calls). `SessionEnd` removes the
per-session marker and prunes stale ones so state never accumulates.

## Reminder configuration (env vars)

| Variable | Default | Effect |
|----------|---------|--------|
| `REFLECT_EXT_MIN_ACTIONS` | `3` | Minimum meaningful actions to trigger on Stop |
| `REFLECT_EXT_REMIND_ONCE` | `1` | At most one reminder per session |
| `REFLECT_EXT_PLAINTEXT` | unset | `1` prints plain text instead of `systemMessage` |
| `REFLECT_EXT_MARKER_TTL_DAYS` | `7` | Prune marker files older than N days |

## Notes

- The script is pure standard library; no dependencies.
- Hooks never block and always exit 0 on error.
- Inspired by the hook wiring in
  [`claude-reflect`](https://github.com/BayramAnnakov/claude-reflect).
