# Push Local Changes Back to Source

## Context
The user has improved a skill locally and wants to update the source repository.

## Input
The skill name and optionally a description of what changed.

## Steps

### 1. Find the Entry
- Read `~/prg/skills-akaihola/library/library.yaml`
- Locate the entry by name

### 2. Determine Source Location

**If source is a local path in `skills-akaihola`** (starts with `~/prg/skills-akaihola/`):
- The skill is already in skills-akaihola. Just commit and push:
  ```bash
  cd ~/prg/skills-akaihola
  git add <skill_directory>/
  git commit -m "library: updated <name> — <what changed>"
  git push
  ```

**If source is a local path outside skills-akaihola** (e.g., `~/.claude/skills/<name>/`):
- Stage and commit from wherever the source lives. If it's in a git repo, commit there.
- If it's not in a git repo, offer to move it into skills-akaihola.

**If source is a GitHub URL** (external repo):
1. Clone into a temp dir: `git clone --depth 1 <clone_url> /tmp/lib-push-<name>`
2. Overwrite the skill directory in the clone with the local version
3. Stage and commit:
   ```bash
   cd /tmp/lib-push-<name>
   git add <skill_path>/
   git commit -m "library: updated <name> — <what changed>"
   git push
   ```
4. Clean up: `rm -rf /tmp/lib-push-<name>`

### 3. Confirm
Tell the user which repository was updated and what was pushed.
