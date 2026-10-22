# Sync All Installed Skills

## Context
Pull the latest versions of all skills from their sources.

## Steps

### 1. Record the Workspace Root
Run this in the caller's workspace before any other step:
```bash
WORKSPACE_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
echo "$WORKSPACE_ROOT"
```
No step changes directory. Shell variables may not carry over between commands: set `WORKSPACE_ROOT` again in each command that uses it, from the path printed here.

### 2. Pull skills-akaihola
Symlinks to sources in `skills-akaihola` update with a single pull:
```bash
git -C ~/prg/skills-akaihola pull
```
Symlinks to local sources elsewhere already show their own checkout; this pull does not update them.

### 3. Handle GitHub-sourced Skills (Non-Symlinked)
For any skill installed as a copy (from an external GitHub URL), re-run the `use` workflow to refresh it.

Check which installed skills are copies, not symlinks:
```bash
find "$WORKSPACE_ROOT/.claude/skills" -mindepth 1 -maxdepth 1 ! -type l
```

For each copy, re-fetch from source using the `use` cookbook steps, which ask before replacing an existing copy.

### 4. Confirm
Report:
- `skills-akaihola` pulled to commit `<hash>`
- Any additional skills refreshed
- Symlinked skills updated by the pull (count), and symlinks to other local sources (count)
