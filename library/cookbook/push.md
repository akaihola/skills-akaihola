# Push Local Changes Back to Source

## Context
The user has improved a skill locally and wants to update the source repository.

## Input
The skill name and optionally a description of what changed.

## Steps

### 1. Record the Workspace Root
Run this in the caller's workspace before any other step:
```bash
WORKSPACE_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
echo "$WORKSPACE_ROOT"
```
No step changes directory. Shell variables may not carry over between commands: set `WORKSPACE_ROOT` again in each command that uses it, from the path printed here.

### 2. Find the Entry
- Read `~/prg/skills-akaihola/library/library.yaml`
- Locate the entry by name

### 3. Determine Source Location

**If source is a local path in `skills-akaihola`** (starts with `~/prg/skills-akaihola/`):
- The skill is already in skills-akaihola. Just commit and push:
  ```bash
  git -C ~/prg/skills-akaihola add <skill_directory>/
  git -C ~/prg/skills-akaihola commit -m "library: updated <name> — <what changed>"
  git -C ~/prg/skills-akaihola push
  ```

**If source is a local path outside skills-akaihola** (e.g., `~/.claude/skills/<name>/`):
- Stage and commit from wherever the source lives, using `git -C <source_dir>`. If it's in a git repo, commit there.
- If it's not in a git repo, offer to move it into skills-akaihola.

**If source is a GitHub URL** (external repo):
1. Parse org, repo, ref and file path from the URL as in the `use` cookbook. The local version is the copy at `$WORKSPACE_ROOT/.claude/skills/<name>` (or `~/.claude/skills/<name>` if installed globally).
2. Clone that ref, overwrite the skill directory in the clone with the local version, commit, push and clean up:
   ```bash
   CLONE_DIR=$(mktemp -d)
   git clone --depth 1 --branch <ref> https://github.com/<org>/<repo>.git "$CLONE_DIR"
   rm -rf "$CLONE_DIR/<skill_path>"
   cp -R "$WORKSPACE_ROOT/.claude/skills/<name>" "$CLONE_DIR/<skill_path>"
   git -C "$CLONE_DIR" add <skill_path>/
   git -C "$CLONE_DIR" commit -m "library: updated <name> — <what changed>"
   git -C "$CLONE_DIR" push
   rm -rf "$CLONE_DIR"
   ```

### 4. Confirm
Tell the user which repository was updated and what was pushed.
