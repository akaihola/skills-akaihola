# Remove an Entry from the Library

## Context
Remove a skill, agent, or prompt from the catalog, and optionally unlink it locally.

## Input
The skill name to remove.

## Steps

### 1. Record the Workspace Root
Run this in the caller's workspace before any other step:
```bash
WORKSPACE_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
echo "$WORKSPACE_ROOT"
```
No step changes directory. Shell variables may not carry over between commands: set `WORKSPACE_ROOT` again in each command that uses it, from the path printed here.

### 2. Sync the Library Repo
```bash
git -C ~/prg/skills-akaihola pull
```

### 3. Find the Entry
- Read `~/prg/skills-akaihola/library/library.yaml`
- Locate the entry by name
- If not found, tell the user

### 4. Confirm Intent
Ask: "Remove `<name>` from the catalog? Also unlink from the current workspace? (y/n/both)"

### 5. Remove from Catalog (if confirmed)
- Edit `~/prg/skills-akaihola/library/library.yaml` to remove the entry from the appropriate section
- Commit and push:
  ```bash
  git -C ~/prg/skills-akaihola add library/library.yaml
  git -C ~/prg/skills-akaihola commit -m "library: removed <type> <name>"
  git -C ~/prg/skills-akaihola push
  ```

### 6. Unlink Locally (if confirmed)
```bash
TARGET="$WORKSPACE_ROOT/.claude/skills/<name>"
if [ -L "$TARGET" ]; then
  rm "$TARGET"
  echo "Unlinked $TARGET"
elif [ -d "$TARGET" ]; then
  echo "Warning: $TARGET is a copy, not a symlink. Remove manually if desired."
fi
```

### 7. Confirm
Tell the user what was removed and where.
