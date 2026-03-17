# Remove an Entry from the Library

## Context
Remove a skill, agent, or prompt from the catalog, and optionally unlink it locally.

## Input
The skill name to remove.

## Steps

### 1. Sync the Library Repo
```bash
cd ~/prg/skills-akaihola && git pull
```

### 2. Find the Entry
- Read `~/prg/skills-akaihola/library/library.yaml`
- Locate the entry by name
- If not found, tell the user

### 3. Confirm Intent
Ask: "Remove `<name>` from the catalog? Also unlink from the current workspace? (y/n/both)"

### 4. Remove from Catalog (if confirmed)
- Edit `library.yaml` to remove the entry from the appropriate section
- Commit and push:
  ```bash
  cd ~/prg/skills-akaihola
  git add library/library.yaml
  git commit -m "library: removed <type> <name>"
  git push
  ```

### 5. Unlink Locally (if confirmed)
```bash
WORKSPACE_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
TARGET="$WORKSPACE_ROOT/.claude/skills/<name>"
if [ -L "$TARGET" ]; then
  rm "$TARGET"
  echo "Unlinked $TARGET"
elif [ -d "$TARGET" ]; then
  echo "Warning: $TARGET is a copy, not a symlink. Remove manually if desired."
fi
```

### 6. Confirm
Tell the user what was removed and where.
