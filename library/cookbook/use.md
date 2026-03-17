# Use a Skill from the Library

## Context
Symlink a skill, agent, or prompt from the catalog into the current workspace (or globally).

## Input
The user provides a skill name or description. May include "global" to install user-wide.

## Steps

### 1. Sync the Library Repo
```bash
cd ~/prg/skills-akaihola && git pull
```

### 2. Find the Entry
- Read `~/prg/skills-akaihola/library/library.yaml`
- Search across `library.skills`, `library.agents`, `library.prompts`
- Match by name (exact) or description (keyword/fuzzy)
- If multiple matches, show them and ask the user to pick
- If no match, suggest `/library search <keyword>`

### 3. Resolve Dependencies
If the entry has a `requires` field, recursively install each dependency first (same workflow).

### 4. Determine Target Directory
- Read `default_dirs` from `library.yaml`
- User said "global" → use the `global` path (e.g. `~/.claude/skills/`)
- Otherwise → use the `default` path relative to current workspace root:
  ```bash
  WORKSPACE_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
  TARGET_DIR="$WORKSPACE_ROOT/.claude/skills"  # for skills
  ```
- For agents: use `.claude/agents/` (default) or `~/.claude/agents/` (global)
- For prompts: use `.claude/commands/` (default) or `~/.claude/commands/` (global)

### 5. Resolve Source Path

**If source starts with `~/` or `/` (local path):**
- Expand `~` → `/home/agent`
- Get the parent directory of the referenced file (e.g., `~/prg/skills-akaihola/hsl/SKILL.md` → `~/prg/skills-akaihola/hsl/`)
- Create symlink:
  ```bash
  ln -sfn <expanded_source_parent_dir> "$TARGET_DIR/<skill_name>"
  ```

**If source is a GitHub URL:**
- Parse org, repo, branch, file_path from the URL
- Clone into a temp dir: `git clone --depth 1 https://github.com/<org>/<repo>.git /tmp/lib-install-<name>`
- Copy the skill directory (not symlink, since it's a remote source):
  ```bash
  cp -R /tmp/lib-install-<name>/<parent_of_file> "$TARGET_DIR/<skill_name>"
  rm -rf /tmp/lib-install-<name>
  ```

### 6. Confirm
Tell the user which skill was installed and where. Example:
```
✓ Installed skill 'hsl' at .claude/skills/hsl -> ~/prg/skills-akaihola/hsl
```
Note: Since this is a symlink, updates to skills-akaihola automatically propagate — no manual sync needed.
