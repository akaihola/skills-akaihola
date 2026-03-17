# List Available Skills

## Context
Show the full library catalog with install status in the current workspace.

## Steps

### 1. Sync the Library Repo
```bash
cd ~/prg/skills-akaihola && git pull
```

### 2. Read the Catalog
- Read `~/prg/skills-akaihola/library/library.yaml`
- Parse all entries from `library.skills`, `library.agents`, `library.prompts`

### 3. Check Install Status
For each entry, determine install status in the current workspace:
```bash
WORKSPACE_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
```

For each skill:
- Check `$WORKSPACE_ROOT/.claude/skills/<name>` — if symlink: "✓ installed (workspace)", if directory: "✓ installed (copy)"
- Check `~/.claude/skills/<name>` — if exists: "✓ installed (global)"
- Otherwise: "— not installed"

### 4. Display Results

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
