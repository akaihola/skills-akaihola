# Use a Skill from the Library

## Context
Install a skill, agent, or prompt from the catalog into the current workspace (or globally): a symlink for a local source, a copy for a GitHub source.

## Input
The user provides a skill name or description. May include "global" to install user-wide.

## Steps

### 1. Record the Workspace Root
Run this in the caller's workspace before any other step:
```bash
WORKSPACE_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
echo "$WORKSPACE_ROOT"
```
No step changes directory. Shell variables may not carry over between commands: set `WORKSPACE_ROOT` (and `TARGET_DIR` from step 5) again in each command that uses them, from the path printed here.

### 2. Sync the Library Repo
```bash
git -C ~/prg/skills-akaihola pull
```

### 3. Find the Entry
- Read `~/prg/skills-akaihola/library/library.yaml`
- Search across `library.skills`, `library.agents`, `library.prompts`
- Match by name (exact) or description (keyword/fuzzy)
- If multiple matches, show them and ask the user to pick
- If no match, suggest `/library search <keyword>`

### 4. Resolve Dependencies
If the entry has a `requires` field, recursively install each dependency first (same workflow).

### 5. Determine Target Directory
- Read `default_dirs` from `library.yaml`
- User said "global" → use the `global` path (e.g. `~/.claude/skills/`)
- Otherwise → use the `default` path under the workspace root from step 1:
  ```bash
  TARGET_DIR="$WORKSPACE_ROOT/.claude/skills"  # for skills
  ```
- For agents: use `.claude/agents/` (default) or `~/.claude/agents/` (global)
- For prompts: use `.claude/commands/` (default) or `~/.claude/commands/` (global)
- If `$TARGET_DIR/<skill_name>` already exists, ask before replacing it: a copy may hold local edits that `/library push` has not sent back. To replace it, run `rm -rf "$TARGET_DIR/<skill_name>"` first: `ln -sfn` onto an existing directory, or `cp -R` onto an existing directory or symlink, puts the new skill inside it, and through a symlink that is the source checkout.

### 6. Resolve Source Path

**If source starts with `~/` or `/` (local path):**
- Expand `~` to `$HOME`
- Get the parent directory of the referenced file (e.g., `~/prg/skills-akaihola/hsl/SKILL.md` → `~/prg/skills-akaihola/hsl/`)
- Create the target directory and the symlink:
  ```bash
  mkdir -p "$TARGET_DIR"
  ln -sfn <expanded_source_parent_dir> "$TARGET_DIR/<skill_name>"
  ```

**If source is a GitHub URL:**
- Parse org, repo, ref and file path from the URL, e.g. `https://github.com/<org>/<repo>/blob/<ref>/<parent_of_file>/SKILL.md`. If the URL names no ref, leave out `--branch <ref>` below to get the default branch.
- Clone that ref, copy the skill directory (not symlink, since it's a remote source) and remove the clone:
  ```bash
  CLONE_DIR=$(mktemp -d)
  git clone --depth 1 --branch <ref> https://github.com/<org>/<repo>.git "$CLONE_DIR"
  mkdir -p "$TARGET_DIR"
  cp -R "$CLONE_DIR/<parent_of_file>" "$TARGET_DIR/<skill_name>"
  rm -rf "$CLONE_DIR"
  ```
- `--branch` takes a branch or tag. For a commit hash, clone without `--depth 1 --branch <ref>` and run `git -C "$CLONE_DIR" checkout <ref>` before copying.
- If the file is at the repository root, delete `"$TARGET_DIR/<skill_name>/.git"` after copying.

### 7. Confirm
Tell the user which skill was installed and where. Example:
```
✓ Installed skill 'hsl' at .claude/skills/hsl -> ~/prg/skills-akaihola/hsl
```
For a symlink, edits in the source checkout show up immediately. A copy from GitHub stays as installed until `/library sync` refreshes it.
