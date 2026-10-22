# List Available Skills

## Context
Show the full library catalog with install status in the current workspace.

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

### 3. Read the Catalog
- Read `~/prg/skills-akaihola/library/library.yaml`
- Parse all entries from `library.skills`, `library.agents`, `library.prompts`

### 4. Check Install Status
For each skill:
- Check `$WORKSPACE_ROOT/.claude/skills/<name>` — if symlink: "✓ installed (workspace)", if directory: "✓ installed (copy)"
- Check `~/.claude/skills/<name>` — if exists: "✓ installed (global)"
- Otherwise: "— not installed"

### 5. Display Results

Group by type, one section each:

```
## Skills (N)
| Name | Description | Status |
|------|-------------|--------|
| hsl  | Helsinki public transport | ✓ workspace |
| vr   | Finnish train schedules | — not installed |
...

## Agents (N)
(empty or entries)

## Prompts (N)
(empty or entries)
```

- In WhatsApp/Matrix channels, use bullet lists instead of tables
- Include a count per section in the heading
