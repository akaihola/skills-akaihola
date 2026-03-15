---
name: upstream-pr
description: >-
  Prepare and submit a pull request to an upstream repository from a fork.
  Creates a clean branch on top of upstream/main, maintains a PULL_REQUEST_DRAFT.md
  in every commit as live PR documentation, and submits via `gh pr create` after
  git-removing the draft file. Use when the user says "prepare a PR for upstream",
  "contribute this fix to upstream", "create a PR branch", "open a PR on the upstream
  repo", or asks to submit changes from a fork to the original project.
---

# Upstream PR Workflow

This skill manages the full lifecycle of contributing a fix from a fork back to an
upstream repository, following a **draft-in-tree** convention: a `PULL_REQUEST_DRAFT.md`
file lives in every commit on the PR branch and is `git rm`'d immediately before
submission.

## The PULL_REQUEST_DRAFT.md Convention

Every commit on a PR branch **must** contain `PULL_REQUEST_DRAFT.md` at the repo root.

Format:

```markdown
# PR Title Here (this line → `gh pr create --title`)

Everything below this line becomes the PR body (`--body`).

## Problem
…

## Solution
…

## Testing
…
```

- The first `# H1` line is the PR title.
- All remaining content is the PR body (GitHub Markdown).
- The file is committed so every intermediate state of the branch is self-documenting.
- **Do NOT `.gitignore` it** — it must be visible in `git log` and reviewable.
- **Remove it with `git rm` just before creating the PR** (see Submission step).

## Remotes Convention

In a fork, always name remotes:

| Remote     | Points to                |
|------------|--------------------------|
| `origin`   | Your fork (read/write)   |
| `upstream` | The original project     |

If `upstream` is not configured:
```bash
git remote add upstream https://github.com/OWNER/REPO.git
git fetch upstream
```

## Workflow

### 1. Identify the change

Determine what needs contributing. Common sources:
- A commit in your fork's `main` not in `upstream/main`
- A bug fix applied locally but never submitted
- An enhancement developed in a feature branch

Useful commands:
```bash
# Commits in fork's main not in upstream
git log --oneline upstream/main..main

# Diff a specific file between fork and upstream
git diff upstream/main..main -- path/to/file.go

# Check if content already merged upstream (empty = already there)
git cherry -v upstream/main <your-branch>
```

**Always verify the change is not already in upstream before creating a PR branch.**
Upstream may have merged the content under different commit SHAs. Use
`git diff upstream/main...<your-branch>` (three dots = content diff from merge base)
to confirm actual differences exist.

### 2. Fetch upstream

```bash
git fetch upstream
```

### 3. Create a clean branch from upstream/main

```bash
git checkout -b <branch-name> upstream/main
```

Branch naming convention:
- `fix/<short-description>` for bug fixes
- `feat/<short-description>` for new features
- `chore/<short-description>` for non-functional changes
- `docs/<short-description>` for documentation

### 4. Apply the change

Choose the cleanest approach:

**a) Cherry-pick** (when the commit applies cleanly):
```bash
git cherry-pick <commit-sha>
# Resolve any conflicts if needed
```

**b) Apply a file diff** (when cherry-pick would drag in unrelated changes):
```bash
git diff upstream/main..main -- path/to/file > /tmp/fix.patch
git apply /tmp/fix.patch
git add path/to/file
git commit -m "fix: description of the fix"
```

**c) Implement fresh** (when rewriting is cleaner than patching):
Just make the changes and commit normally.

### 5. Add PULL_REQUEST_DRAFT.md to the commit

After the fix commit exists (or as part of it), add `PULL_REQUEST_DRAFT.md`:

```bash
cat > PULL_REQUEST_DRAFT.md << 'EOF'
# fix: concise imperative title matching upstream's commit style

## Problem

Describe what was broken and why it mattered.

## Solution

Explain what the fix does. Reference the functions/files changed.

## Testing

How to verify the fix works. Include commands if applicable.
EOF

git add PULL_REQUEST_DRAFT.md
git commit --amend --no-edit   # or: git commit -m "..." if draft is a separate commit
```

For multi-commit PRs, include `PULL_REQUEST_DRAFT.md` in **every** commit
(use `git commit --amend` or update it at each step). The file should always
reflect the PR's current intended title and description.

### 6. Push the branch to origin

```bash
git push origin <branch-name>
```

Note: the agent cannot push to GitHub. Remind the user to run `ghpp` on atom
or use `git push` from a machine with push access.

### 7. Submit the PR (submission step)

When the branch is ready to submit, use the helper script:

```bash
# From the repo root, with the PR branch checked out:
bash /path/to/skills-akaihola/upstream-pr/scripts/submit-pr.sh [--upstream-repo OWNER/REPO]
```

The script:
1. Reads `PULL_REQUEST_DRAFT.md` and extracts title + body
2. Shows a preview and asks for confirmation
3. Runs `git rm PULL_REQUEST_DRAFT.md && git commit -m "chore: remove PR draft before submission"`
4. Runs `git push origin <branch>` (if needed)
5. Runs `gh pr create --repo OWNER/REPO --title "..." --body "..."`

**Manual equivalent** (if not using the script):
```bash
TITLE=$(grep -m1 '^# ' PULL_REQUEST_DRAFT.md | sed 's/^# //')
BODY=$(tail -n +2 PULL_REQUEST_DRAFT.md | sed '1{/^$/d}')
git rm PULL_REQUEST_DRAFT.md
git commit -m "chore: remove PR draft before submission"
git push origin <branch>
gh pr create --repo OWNER/REPO --title "$TITLE" --body "$BODY"
```

## Handling Conflicts

When cherry-picking produces conflicts:
1. Inspect the conflict with `git diff` and understand both sides.
2. Resolve by keeping the most correct version — usually upstream's recent refactors
   plus your new logic on top.
3. `git add` resolved files, then `git cherry-pick --continue`.
4. Do **not** use `--strategy-option theirs/ours` blindly — read the conflict.

## Verifying the Branch is Clean

Before pushing, confirm the branch only contains what you intend:

```bash
# Should list only your PR commits
git log --oneline upstream/main..<branch>

# Should show only your intended file changes
git diff --stat upstream/main...<branch>

# PULL_REQUEST_DRAFT.md must be present
git show HEAD:PULL_REQUEST_DRAFT.md | head -3
```

## Keeping Branches Updated

If upstream/main advances while your PR is under review:
```bash
git fetch upstream
git rebase upstream/main
# Update PULL_REQUEST_DRAFT.md if anything changed
git push --force-with-lease origin <branch>
```

## Example: Full Single-Fix PR

```bash
cd ~/mitto
git fetch upstream
git checkout -b fix/my-bug-fix upstream/main
git cherry-pick abc1234

cat > PULL_REQUEST_DRAFT.md << 'EOF'
# fix(web): correct the thing that was broken

## Problem
Widget exploded when user did X.

## Solution
Guard against nil pointer in `handleFoo()`.

## Testing
`go test ./internal/web/...` passes. Manually verified: X no longer explodes.
EOF

git add PULL_REQUEST_DRAFT.md
git commit --amend --no-edit

git push origin fix/my-bug-fix
# Then ask the user to push with `ghpp` on atom, or run the submit script
```

## Notes

- Always target `upstream/main` as the base, not `origin/main` or `main`.
- Always verify the fix is not already upstream before creating a branch.
- If the upstream repo uses squash-merge, a single commit per PR is cleaner.
- Keep PR branches focused: one logical change per branch.
- Close the corresponding upstream issue in the PR body with `Fixes #N`.
