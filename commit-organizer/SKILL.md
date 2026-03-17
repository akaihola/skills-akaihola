---
name: commit-organizer
description: Triage a messy working tree (disk space analysis, gitignore cleanup, generated-file removal) and then organize the remaining changes into a sequence of cohesive Conventional Commits ordered by file mtime. Use when the user asks to organize commits, group changes into related commits, or clean up a large uncommitted diff before sharing or merging.
version: 1.2.0
---

# Commit Organizer Skill

Use when the user asks to "organize commits", "commit in logical groups", "commit organizer", "group changes into commits", or similar.

Turn a messy working tree into a clean series of focused, conventional commits with clear messages.

## When Not to Use

Do not use this skill when:

- the working tree is tiny and one obvious commit is enough
- the user explicitly wants a single squashed commit
- the user only wants help naming or polishing a commit message
- the tree contains unresolved conflicts, broken tests, or half-finished work that should be cleaned up before commit splitting
- the user wants interactive rebasing or history rewriting rather than new commits from the current working tree

---

## Workspace Configuration

This skill is generic. Before planning commits, look for an optional workspace configuration file in this order:

1. `.ai/commit-organizer.yml`
2. `.commit-organizer.yml`

If a config file exists, use it as **heuristics, not hard law**. It may provide:

- preferred commit types and scopes by path
- grouping buckets by path pattern
- `keepSeparate` hints for cleanup-only or rename-heavy batches
- ignore patterns for generated noise
- naming hints for common commit subjects

If no config exists, use the default methodology in this skill.

See `examples/commit-organizer.yml` for a sample.

## Examples

Likely trigger phrases:

- "Organize these changes into logical commits."
- "Use commit organizer on this repo."
- "Group the working tree into cohesive Conventional Commits."
- "Make a clean commit series out of this messy diff."
- "Commit these changes in mtime order."

## Checklist

Use this fast execution checklist during live runs:

- inspect `git status --short --untracked-files=all`
- inspect `git diff --stat-width=120 --stat` and `git diff` if needed
- load workspace config if present
- **triage:** measure disk usage, identify generated/state noise
- **triage:** propose `.gitignore` additions, `git rm --cached` for tracked noise
- **triage:** commit cleanup separately before organizing real work
- identify cohesive file groups among remaining changes
- compute mtimes and order groups by each group's oldest file
- draft Conventional Commit messages
- show the plan before committing
- stage only one group at a time
- commit with specific subject and short explanatory body
- repeat until the tree is clean
- show final `git log --oneline` and confirm cleanliness

## Methodology

### 0. Pre-flight triage: disk space analysis and gitignore cleanup

Before grouping files into commits, identify and remove noise from the working tree. This step prevents generated artifacts, runtime state, and large binaries from polluting commit groups.

Three helper scripts in `scripts/` automate the mechanical parts of triage. Run them via `uv run --with pyyaml`:

```bash
# Step 0a — disk usage + classification table
uv run --with pyyaml scripts/co_triage.py [REPO_DIR]

# Step 0c/0d — propose .gitignore patch + git rm --cached commands
uv run --with pyyaml scripts/co_ignore.py [REPO_DIR]          # dry-run (default)
uv run --with pyyaml scripts/co_ignore.py --apply [REPO_DIR]  # apply changes

# Steps 3–4 — propose commit groups ordered by mtime
uv run --with pyyaml scripts/co_plan.py [REPO_DIR]
```

All three read workspace config automatically (`.ai/commit-organizer.yml` or `.commit-organizer.yml`). Pass `--config PATH` to override. Add `--json` for machine-readable output.

#### 0a. Measure disk usage of all uncommitted changes

Run `co_triage.py` to get a sorted table of every uncommitted file with status, bytes, line churn, and classification (ignorable vs intentional).

If not using the script, measure manually:

For **tracked modified/deleted files**, measure line-level churn:

```bash
git diff --numstat | awk '{add=$1; del=$2; if(add=="-") add=0; if(del=="-") del=0; print add+del "\t+" $1 "\t-" $2 "\t" $3}' | sort -nr | head -20
```

For **untracked files and directories**, measure on-disk byte size:

```python
import os, subprocess
from pathlib import Path
for line in subprocess.check_output(
    ['git', 'status', '--short', '--untracked-files=all'], text=True
).splitlines():
    if not line.startswith('?? '): continue
    p = Path(line[3:])
    if not p.exists(): continue
    if p.is_dir():
        size = sum(f.stat().st_size for f in p.rglob('*') if f.is_file())
    else:
        size = p.stat().st_size
    print(f"{size}\t{p}")
```

Sort by size descending. Present the largest items to the user.

#### 0b. Classify into "safe to ignore" vs "intentional work"

Group every uncommitted file into one of:

| Category | Examples | Action |
|---|---|---|
| Runtime state / logs | `heartbeat-state.json`, `sessions/*.jsonl`, `.blog_tracking.json` | `.gitignore` + `git rm --cached` |
| Generated output | `outputs/`, `tmp/`, rendered HTML/PNG, downloaded PDFs | `.gitignore` |
| Moved / reorganized files | root scripts deleted, replacements in `scripts/` | stage deletion + addition together |
| Intentional content | notes, project pages, skills, config | keep for commit grouping |

If workspace config exists, check its `ignore` patterns first. Flag any tracked files that match `ignore` patterns but are still in the index.

#### 0c. Update `.gitignore`

Run `co_ignore.py` for automated proposals, or compose manually.

Propose new `.gitignore` entries with explanatory comments. Group by category:

```gitignore
# Runtime state files
heartbeat-state.json
sessions/*.jsonl

# Generated / temporary working files
tmp/
outputs/
downloads/
```

Add the kernel note if not already present:

```gitignore
# Kernel note: .gitignore only prevents new files from being tracked – it does
# not affect files already in Git history. Use `git rm --cached <path>` to keep
# generated files on disk while removing them from version control.
```

#### 0d. Untrack already-tracked generated files

For files that match the new ignore patterns but are already tracked:

```bash
git rm --cached -- <file1> <file2> ...
```

This keeps the files on disk but removes them from the index going forward.

#### 0e. Commit the cleanup separately

Stage `.gitignore` changes and all `git rm --cached` removals, then commit before organizing real work:

```bash
git add .gitignore
git commit -m "chore: update gitignore and untrack generated files" \
  -m "- Add ignore patterns for runtime state and generated output" \
  -m "- Remove tracked generated files with git rm --cached"
```

This keeps cleanup history clean and separate from content work.

#### 0f. Skip triage when unnecessary

Skip Phase 0 entirely if:

- the tree is small and obviously clean
- all changes are clearly intentional content
- the user says to skip triage

### 1. Inspect the full working tree

After triage (or skipping it), inspect what remains:

```
git status --short --untracked-files=all
git diff --stat-width=120 --stat
```

If the user wants detail beyond stats, run `git diff` (full) and `git diff --cached`.

### 2. Load workspace config if present

If `.ai/commit-organizer.yml` or `.commit-organizer.yml` exists, read it before grouping files.

Use config to guide:

- path-based grouping buckets
- default commit types/scopes
- ignore lists for generated files
- naming conventions

Still preserve judgment. If a strict config rule would create a worse commit split, keep the logical boundary and explain the exception.

### 3. Identify logical groups

Group files by **cohesion, not just proximity**. Common patterns:

| Group signal              | Examples                                  |
| ------------------------- | ----------------------------------------- |
| Same tool/service area    | all `.claude/skills/*` changes            |
| Same project              | all `pages/Projects/X/*` files            |
| Same content type         | all journals, all scripts, all templates  |
| Same lifecycle event      | deletions together, renames together      |
| Same time-intention batch | vault hygiene pass, project state refresh |

**Split when:**

- a directory has both new features and unrelated edits
- deletions are unrelated to additions (e.g. cleanup vs new work)
- a file appears in multiple logical intents (put each hunk where it belongs conceptually)

**Merge when:**

- small edits across 2–3 files are all the same conceptual change (e.g. frontmatter metadata refresh across project notes)

### 4. Compute mtimes and order chronologically

For every changed/untracked file, get the on-disk mtime:

```python
import os, time
mtime = os.stat(path).st_mtime
print(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime)))
```

For deleted files, use the commit time of the last commit that touched them:

```
git log -1 --format=%ci -- <path>
```

Use the **oldest mtime in each group** as the group's ordering key. Commit from oldest group to newest.

**Exception:** if strict chronological ordering would split a coherent feature into disjoint commits, preserve the logical boundary and note the exception.

### 5. Choose Conventional Commit messages

Format: `<type>(<optional-scope>): <imperative description>`

Body: 2–5 bullet points describing what changed and why.

**Types to use:**

| Type       | When                                                                |
| ---------- | ------------------------------------------------------------------- |
| `feat`     | new files, new capabilities, new tooling                            |
| `fix`      | bugfixes, broken-link corrections                                   |
| `docs`     | documentation-only changes (notes, guides, READMEs, knowledge base) |
| `refactor` | restructuring without changing behavior (renames, reorgs)           |
| `chore`    | generated file removals, dependency churn, config drift             |
| `style`    | whitespace/formatting-only changes                                  |
| `test`     | test additions or changes                                           |

**Scope ideas** (use when helpful, omit when the type is clear enough):

`scripts`, `journal`, `vault`, `projects`, `skills`, `agent`, `intelligence`, `public`, `resources`, `templates`, `<project-name>`

### 6. Plan before committing

Show the user the planned groups **before** any commit:

```
## Planned commits, oldest to newest

1. `feat(scripts): add analysis and publishing helpers`
   - files: scripts/*, mkdocs.sh (removed)
   - oldest mtime basis: 2026-02-13 23:16:22
   - rationale: script additions/removals, tools only

2. `docs(journal): add March journals and update historical notes`
   - files: journals/2026/03/*, memory/HISTORY.md
   - oldest mtime basis: 2026-03-07 07:25:16
   - rationale: documentation batch
```

Wait for confirmation (or proceed if the user said "yes" or "go ahead" already).

### 7. Execute commits

For each group:

```bash
git add <files>
git commit -m "type(scope): short summary" -m "- detail 1" -m "- detail 2"
```

Stage **only** the files in the current group. Do not stage unrelated changes.

If a path contains spaces or special characters, quote it:

```bash
git add "pages/Projects/Agent Commons.md" pages/Projects/Agent\ Commons/
```

### 8. Handle edge cases

**Standalone deletions:** files removed with no related additions (e.g. obsolete docs) get their own commit, usually last.

**Renames:** if git detects a rename (delete + add with high similarity), commit it with the content batch it belongs to, not in a separate "renames" commit.

**Binary files and untracked directories:** stage them with their conceptual group (e.g. review images with review content, downloaded PDFs with their download batch — or skip them if the user says to leave them untracked).

**Cannot cleanly group:** explain why before committing. Do not force-fit files into groups.

### 9. Confirm clean tree

After all commits:

```
git status --short   # expect empty
git log --oneline --max-count=<N>   # show the created commits
```

Show the final commit list with short hashes and messages.

---

## Output template

Before committing, show:

```
Planned commit groups, in creation order:

1. `type(scope): message`
   - rationale: ...
   - ordering basis: oldest mtime <date>

...

Created commits:

- `<hash>` `type(scope): message`
- `<hash>` `type(scope): message`
...

Working tree: clean
```

If anything could not be cleanly grouped, note it here with the reason.
