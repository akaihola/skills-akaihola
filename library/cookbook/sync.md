# Sync All Installed Skills

## Context
Pull the latest versions of all skills from their sources.

## Steps

### 1. Pull skills-akaihola
Since most skills are symlinked directly from `skills-akaihola`, a single pull updates everything:
```bash
cd ~/prg/skills-akaihola && git pull
```

### 2. Handle GitHub-sourced Skills (Non-Symlinked)
For any skill installed as a copy (from an external GitHub URL), re-run the `use` workflow to refresh it.

Check which installed skills are copies vs symlinks:
```bash
WORKSPACE_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
ls -la "$WORKSPACE_ROOT/.claude/skills/" | grep -v "^l"   # non-symlinks
```

For each non-symlink, re-fetch from source using the `use` cookbook steps.

### 3. Confirm
Report:
- `skills-akaihola` pulled to commit `<hash>`
- Any additional skills refreshed
- Total symlinked skills that auto-updated (count)
