# Install the Library (First-Time Setup)

## Context
Bootstrap the library on a new device or workspace that doesn't yet have `skills-akaihola` cloned.

## Steps

### 1. Check if Already Installed
```bash
ls ~/prg/skills-akaihola/library/library.yaml 2>/dev/null && echo "already installed"
```
If it exists, skip to step 3.

### 2. Clone skills-akaihola
```bash
mkdir -p ~/prg
git clone https://github.com/akaihola/skills-akaihola.git ~/prg/skills-akaihola
```

### 3. Symlink the Library Skill Into Current Workspace
```bash
WORKSPACE_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
mkdir -p "$WORKSPACE_ROOT/.claude/skills"
ln -sfn ~/prg/skills-akaihola/library "$WORKSPACE_ROOT/.claude/skills/library"
echo "Library installed at $WORKSPACE_ROOT/.claude/skills/library"
```

### 4. Confirm
Tell the user:
- The library skill is now available as `/library`
- Run `/library list` to see all available skills
- Run `/library use <name>` to install any skill into the current workspace
