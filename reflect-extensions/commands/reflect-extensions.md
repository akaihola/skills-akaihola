---
description: Audit the current session for reusable learnings and map each one onto the right Claude Code extension surface — skills, MCP servers, slash commands, subagents, hooks, or plugins — then propose new or updated extensions with human approval. Extends /reflect-skills.
argument-hint: "[--dry-run] [--scope project|global|both] [--session <id|current>] [--days N]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, AskUserQuestion
---

# /reflect-extensions

A session retrospective that does the full six-surface audit: it reads what
happened this session, figures out which Claude Code extensions were actually
used, extracts reusable learnings, and proposes the *right* place to put each
learning — a new extension or an edit to an existing one.

This is a superset of `/reflect-skills`. Where `/reflect-skills` only generates
skills/commands from repeated patterns, this command also covers MCP servers,
subagents, hooks, and plugins, and it explicitly reviews the extensions that were
invoked during the session so it can improve them, not just create new ones.

## Arguments

- `--dry-run` — analyze and propose, but write nothing. Default behavior is to
  propose and then apply only what the user approves.
- `--scope project|global|both` — where proposed extensions should live.
  `project` = `.claude/...`, `global` = `~/.claude/...`. Default: `both`
  (decide per item; project conventions stay local, generic learnings go global).
- `--session <id|current>` — which session transcript to analyze. Default:
  `current`.
- `--days N` — when scanning beyond the current session, look back N days.
  Default: current session only.

## Phase 0 — Gather context

Establish what extensions exist and where they live before judging what was used.

Locate the session transcript(s). Claude Code stores sessions as JSONL under
`~/.claude/projects/<sanitized-cwd>/<session-uuid>.jsonl`. For `current`, use the
active session; the conversation is also already in context, so use both the
in-context history and the transcript file (the transcript is the source of truth
for tool calls).

Enumerate every installed extension across all six surfaces and note its config
path. The inspection commands below are pre-run via the `` !`…` `` syntax, so their
output is already injected here before your first turn — read these results rather
than re-running the commands yourself.

**Skills** (project, global, and plugin):

!`ls -1d .claude/skills/*/(N) ~/.claude/skills/*/(N) ~/.claude/plugins/cache/*/*/*/skills/*/(N) 2>/dev/null`

**Slash commands** (project, global, and plugin):

!`ls -1 .claude/commands/(N) ~/.claude/commands/(N) ~/.claude/plugins/cache/*/*/*/commands/(N) 2>/dev/null`

**Subagents** (project, global, and plugin):

!`ls -1 .claude/agents/(N) ~/.claude/agents/(N) ~/.claude/plugins/cache/*/*/*/agents/(N) 2>/dev/null`

**Hooks** (the `hooks` key from project, global, and plugin settings):

!`for f in .claude/settings.json ~/.claude/settings.json ~/.claude/plugins/cache/*/*/*/hooks/hooks.json(N); do [ -f "$f" ] && { echo "== $f =="; jq '.hooks // .' "$f" 2>/dev/null || cat "$f"; }; done 2>/dev/null`

**MCP servers** (resolved set, project config, and user-scope server names):

!`claude mcp list 2>/dev/null; echo "== .mcp.json =="; cat .mcp.json 2>/dev/null; echo "== ~/.claude.json mcpServers =="; jq '.mcpServers | keys' ~/.claude.json 2>/dev/null`

**Plugins** (installed plugins and marketplace manifests):

!`ls -1 ~/.claude/plugins/ 2>/dev/null; for m in ~/.claude/plugins/cache/*/*/*/.claude-plugin/marketplace.json ~/.claude/plugins/marketplaces/*/marketplace.json; do [ -f "$m" ] && { echo "== $m =="; cat "$m"; }; done 2>/dev/null`

Build an inventory table from the above: `surface | name | scope | config path`.

## Phase 1 — Usage audit (which extensions were used this session)

Parse the transcript to determine which of the inventoried extensions were
actually invoked, and how each performed. Detection signals:

- Skill / slash command → `Skill` tool calls and slash-command invocations.
  Plugin items appear namespaced as `plugin-name:command`.
- MCP tool → tool names matching `mcp__<server>__<tool>`. Group by `<server>`.
- Subagent → `Task` tool calls; capture the `subagent_type` and whether the
  returned summary was used.
- Hook → hooks fire automatically and are not always visible as tool calls; infer
  from hook-injected system messages, pre/post-tool side effects, and which
  lifecycle events occurred (SessionStart, PreToolUse, PostToolUse, Stop,
  PreCompact). Cross-reference against the configured hooks from Phase 0.
- Plugin → any of the above resolving to a path under `~/.claude/plugins/`.

For each used extension, record an outcome flag: `worked cleanly`,
`needed correction` (user had to redirect it), `failed / errored`, or
`partially used` (invoked but its output was discarded). These flags drive the
"improve existing extension" proposals in Phase 4.

## Phase 2 — Learning extraction

Read the session and extract reusable learnings into these four buckets. Be
concrete: quote the trigger from the session, then state the generalized learning.

1. **Trial → error → solution.** Anywhere the first approach failed and a working
   fix was found. Capture: what was attempted, why it failed, the fix, and the
   generalizable rule. Also capture corrections the user made ("no, use X").
2. **Good ad-hoc scripts.** Any bash/python/one-liner written during the session
   that solved a real problem and could be reused. Capture the script, its job,
   and how it was invoked.
3. **Successful new workflows.** Any multi-step sequence that worked well and is
   worth making repeatable (e.g. research → scan → write → verify).
4. **Other smoothing learnings.** Conventions, preferences, environment facts,
   gotchas, and naming/path knowledge that would make future work faster.

Filter out one-off, context-specific instructions and anything non-reusable. Keep
only learnings with future value.

## Phase 3 — Surface mapping (the decision rules)

For each learning, choose the *single best* surface. Apply this decision tree in
order; the first match wins. The goal is to put each learning where Claude Code
will actually use it.

1. Is it a **fact, preference, or convention** (not a procedure)?
   → Memory (`CLAUDE.md`). If it concerns one specific extension that was used,
     add it to that extension's own guardrails instead (see rule 7).
2. Is it a **repeatable multi-step procedure** you'd want triggered
   automatically when relevant?
   → **Skill** (`SKILL.md`, model-invocable via its `description`).
3. Is it a repeatable procedure you want to fire **only on explicit demand**?
   → **Slash command** (`.claude/commands/<name>.md`,
     or a skill with `disable-model-invocation: true`).
4. Should it run **automatically on a lifecycle event** as a deterministic gate
   (lint after edit, block dangerous commands, notify on stop, remind on
   SessionStart)?
   → **Hook** (in `settings.json`).
5. Does it require **connecting to an external system/API/data source** that was
   reached for manually this session (calls to a service, a DB, a SaaS)?
   → **MCP server**.
6. Does the work need **isolated or parallel context** (verbose exploration, log
   analysis, fan-out research that polluted the main thread)?
   → **Subagent** (`.claude/agents/<name>.md`).
7. Did an **existing extension underperform** (Phase 1 flagged it `needed
   correction` / `failed` / `partially used`)?
   → **Edit that extension in place.** A correction during `/deploy` becomes a new
     step or guardrail in `deploy`'s file; a flaky MCP call becomes a usage note;
     a subagent that returned noise gets a tighter task prompt.
8. Are several related learnings worth **packaging and sharing** (commands +
   skills + hooks that belong together for a team)?
   → **Plugin** (bundle them, add a marketplace manifest).

Tie-breakers: prefer editing an existing extension over creating a new one when
the learning fits one that already exists; prefer a Skill over a bare command when
auto-triggering is desirable; keep project-specific items in `.claude/` and
generic ones in `~/.claude/`.

## Phase 4 — Opportunity synthesis

Produce a proposal for every learning. Each proposal must be concrete enough to
apply without further questions:

- `surface` and whether it is **NEW** or an **EDIT**
- exact target file path (and scope)
- for NEW: the full file content (with proper frontmatter for skills/commands/
  agents, or the JSON block for hooks/MCP)
- for EDIT: the specific diff — which section/step/guardrail is added or changed,
  shown as before/after
- the source learning it came from (quote the session trigger)
- a one-line rationale referencing which Phase 3 rule selected this surface

Group proposals by surface and present them as a single review table:

```
#  | surface   | action | target                                  | learning
1  | skill     | NEW    | .claude/skills/db-migrate/SKILL.md      | repeated migrate→seed→verify flow
2  | command   | EDIT   | ~/.claude/commands/deploy.md            | add "run tests first" (correction)
3  | hook      | NEW    | .claude/settings.json (PostToolUse)     | auto-lint after Edit on *.py
4  | mcp       | NEW    | .mcp.json (postgres)                    | manual psql calls → MCP server
5  | subagent  | EDIT   | .claude/agents/explorer.md              | tighten task prompt (returned noise)
6  | memory    | NEW    | ./CLAUDE.md                             | "staging URL is …" convention
```

## Phase 5 — Human review and apply

Never write without confirmation. Use `AskUserQuestion` to let the user select
which proposals to apply (multi-select), and for each NEW skill/command/subagent,
confirm scope (project vs global) when `--scope both`.

When applying:
- Back up any file before editing it (`<file>.bak` or note the prior content).
- For EDITs, make the minimal change; preserve existing structure and frontmatter.
- For hooks and MCP, merge into the existing JSON — never clobber the whole file.
- After writing, print a summary of created/edited paths and remind the user to
  `/reload-skills` (and restart for new hooks/plugins) so changes take effect.

If `--dry-run`, stop after presenting the table and write nothing.

## Guardrails

- **No fabrication.** Only propose extensions backed by something that actually
  happened in the session. If a bucket is empty, say so and move on.
- **Secrets.** Never write credentials, tokens, or keys into any extension file.
  For MCP servers, reference env vars; for scripts, parameterize secrets.
- **Idempotency.** Before proposing a NEW extension, check the Phase 0 inventory —
  if a near-duplicate exists, propose an EDIT to it instead.
- **One surface per learning.** Don't scatter the same learning across memory and a
  skill and a hook; pick the best home per the decision tree.
- **Scope discipline.** Project conventions → `.claude/`; reusable general behavior
  → `~/.claude/`.
- **Respect the user's setup.** Match the naming, structure, and frontmatter style
  already used by their existing extensions.

## Output contract

End every run with:
1. The usage-audit summary (which extensions were used + outcome flags).
2. The learnings table (four buckets).
3. The proposal table (Phase 4).
4. What was applied vs skipped, with reload/restart reminders.
