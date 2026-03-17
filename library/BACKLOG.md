# Library Skill Backlog

Ideas for improving the library meta-skill. Inspired by
[disler/the-library](https://github.com/disler/the-library) and our own adoption notes.

---

## Ideas

### Script-backed list and search
**Status:** idea

The `/library list` and `/library search` commands currently rely on the agent reading `library.yaml` and reasoning about install status. A small Python or bash script could do this deterministically — parse the YAML, check for symlinks/dirs in workspace `.claude/skills/`, and print a formatted table. Faster, more reliable, no hallucination risk. Script could live at `library/scripts/list.py`.

---

### Migrate workspace-specific skills into skills-akaihola
**Status:** idea

Skills like `dev-workflow`, `investigate-stuck`, `kernel-audit`, `prompting-guide`, `vr`, `usage-analyzer`, `schedule-channel-report` currently live only in `my-knowledge/.claude/skills/` and aren't in the shared repo. Moving them to `skills-akaihola` would:
- Make the library catalog fully portable (no local-only sources)
- Enable installing them on new devices via `/library use`
- Reduce divergence risk if they're ever edited in-place

Do one at a time. Start with `vr` (cleanest, most standalone).

---

### Catalog agents and prompts
**Status:** idea

`library.yaml` currently has empty `agents: []` and `prompts: []` sections. There are likely prompt files (`.md` command files) scattered across workspaces. Inventory and register them:
- Walk `~/.claude/commands/` and workspace `.claude/commands/` dirs
- Add each to the `prompts` section with source path
- Same for any `.claude/agents/` files

---

### `/library add` auto-detection from cursor position
**Status:** idea

When the agent is already inside a skill directory (CWD contains `SKILL.md`), `/library add` could auto-detect the skill name, description, and source path without the user providing them. Just confirm and commit.

---

### Multi-workspace install in one command
**Status:** idea

`/library use <name> --all-workspaces` could walk all known workspaces (`my-knowledge`, `pipsa`, `paivi`, `coleaders`, `testi`) and create symlinks in each. Useful when adding a new skill to `skills-akaihola` and wanting it available everywhere immediately.

---

### Stale-source detection in `/library list`
**Status:** idea

If a source path in `library.yaml` no longer exists (moved skill, deleted file), `/library list` should flag it as `⚠ source missing`. Helps catch catalog drift over time.

---

### `/library status` — full sync health check
**Status:** idea

A dedicated command that reports:
- `skills-akaihola` git status (commits ahead/behind, dirty files)
- Which installed skills are symlinks (good) vs copies (may be stale)
- Which catalog entries have missing sources
- Which installed workspace skills are NOT in the catalog (undocumented)

Gives a quick health overview when returning to the library after a long gap.
