---
name: learn
description: Extract actionable learnings from this conversation and persist them where they will be found again.
disable-model-invocation: true
allowed-tools: Bash(*), Read(*), Write(*), Edit(*)
---

# Learn from this conversation

**MOST IMPORTANT: focus on behavior, memory, and avoiding future trial-and-error.**

Identify learnings that will help coding agents:

1. **Behave differently** — what new approach or practice should they adopt?
2. **Remember for next time** — what patterns should they recognize automatically?
3. **Avoid trial-and-error** — what would have shortcut the path found the hard way?
4. **Automate** — what frequent or complex task should become a script or skill?
5. **Adopt better principles** — what workflow improvements matter?

**SECONDARY: technical solutions and project details.** Document these too, but they matter less than the behavioral learnings above.

## User-highlighted focus

$ARGUMENTS

If the user provided text above, pay **special attention** to the topics, mistakes, or patterns they called out, in addition to anything else you discover.

## Step 1: Find the friction

Read the conversation from the beginning. **Friction** is the signal — the places the work went slower than it should have:

- Commands or scripts that failed first try — what was the root cause?
- Retries and corrections — what changed between failing and succeeding?
- Tool misuse — wrong tool, wrong flags, wrong parameter order?
- Path confusion — symlinks, dotfiles, nix store paths?
- Repeated lookups — anything figured out more than once?
- Domain rules that had to be discovered — NixOS, Home Manager, uv, packaging gotchas?

Also capture the opposite: patterns that worked elegantly and should be repeated.

Done when every friction point in the conversation is either written down as a candidate or consciously discarded.

## Step 2: Filter for quality

For each candidate, ask:

1. **Actionable?** Would knowing this change future behavior concretely?
2. **Durable?** Will it still apply in a month?
3. **Non-obvious?** Would a knowledgeable developer already know it?
4. **Specific?** Vague reminders ("be careful") are useless; precise rules ("stage new files before `nix flake show`") are valuable.

Discard candidates that are trivial, already documented, or too narrow to recur.

## Step 3: Load workspace conventions

Read `LEARN.md` or `.claude/LEARN.md` from the workspace root if either exists. It defines where *this* workspace keeps memory notes, backlogs and conventions, and overrides the defaults below. Prefer its paths whenever it supplies them.

## Step 4: Choose a destination

| Format | When to use | Where it lives |
| --- | --- | --- |
| **Script** | Multi-step routine that repeats exactly | `~/bin/` or project `bin/` |
| **Skill** | Capability needing instructions and judgment | `.claude/skills/<name>/SKILL.md` |
| **Memory note** | Fact, preference, lesson, context | per `LEARN.md`; else the project's notes files |
| **AGENTS.md update** | Workflow pattern, convention, behavioral rule | `AGENTS.md` at repo root |
| **Improvement backlog** | Idea needing discussion first | per `LEARN.md` |

Then classify by scope:

- References a file, tool, or pattern **unique to this repo** → project-level.
- Would help in **any** coding session → home-level (`~/.config/coding-agents/AGENTS.md` for always-loaded rules, or a skill there for on-demand knowledge).
- When in doubt, prefer the narrower scope.

> **Always-loaded vs on-demand:** an always-loaded `AGENTS.md` is injected into every session — reserve it for rules every agent must follow unconditionally. Larger, context-specific knowledge belongs in a skill, and should merely be *mentioned* in `AGENTS.md` so agents know it exists.

## Step 5: Capture

1. **Read the destination file first** to match its structure and avoid duplication.
2. **Update an existing entry** where one covers the same ground; create a new file only when nothing fits.
3. **Write concisely**, in the imperative.
   - Good: "Stage new files with `git add` before running `nix flake show`"
   - Bad: "It may be helpful to consider staging files"
4. Scripts: make them executable, idempotent, and safe to re-run.
5. Where a learning is ambiguous, record the uncertainty as uncertainty rather than inventing a rule.

Leave existing content in place unless it is factually wrong, restrict edits to documentation, and leave committing to the user.

Done when every surviving learning is written to a destination.

## Step 6: Report

```
## What I learned

**[Learning 1]**: [concise description — focus on behavior/memory]
→ Captured as: [script/skill/memory note/AGENTS.md] in `[path]`
```

If nothing meaningful was learned, say so — an honest empty report is the correct output for a conversation without friction.

Then **stop**, and wait for the user before resuming any previous task.

## Examples

> "This project needs `nix-shell -p gnumake go` to build — neither is on PATH. Captured in memory."
> "The pull-build-install-restart cycle is a routine. Created `bin/rebuild.sh`."
> "The nonce regression came from a stale cache header. Added to memory to check that pattern next time."
