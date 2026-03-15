#!/usr/bin/env bash
# submit-pr.sh — Read PULL_REQUEST_DRAFT.md, remove it, and create a GitHub PR.
#
# Usage:
#   bash submit-pr.sh [--upstream-repo OWNER/REPO] [--dry-run]
#
# Must be run from the repo root with the PR branch checked out.
# Requires: git, gh (GitHub CLI)

set -euo pipefail

UPSTREAM_REPO=""
DRY_RUN=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --upstream-repo)
            UPSTREAM_REPO="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            echo "Unknown argument: $1" >&2
            echo "Usage: submit-pr.sh [--upstream-repo OWNER/REPO] [--dry-run]" >&2
            exit 1
            ;;
    esac
done

# Auto-detect upstream repo from git remote if not provided
if [[ -z "$UPSTREAM_REPO" ]]; then
    UPSTREAM_URL=$(git remote get-url upstream 2>/dev/null || true)
    if [[ -n "$UPSTREAM_URL" ]]; then
        # Extract OWNER/REPO from https://github.com/OWNER/REPO.git or git@github.com:OWNER/REPO.git
        UPSTREAM_REPO=$(echo "$UPSTREAM_URL" \
            | sed -E 's|.*github\.com[:/]||; s|\.git$||')
        echo "Auto-detected upstream repo: $UPSTREAM_REPO"
    else
        echo "ERROR: Could not detect upstream repo. Pass --upstream-repo OWNER/REPO" >&2
        exit 1
    fi
fi

# Check PULL_REQUEST_DRAFT.md exists
if [[ ! -f "PULL_REQUEST_DRAFT.md" ]]; then
    echo "ERROR: PULL_REQUEST_DRAFT.md not found in $(pwd)" >&2
    echo "Create it before running this script." >&2
    exit 1
fi

# Extract title (first H1 line) and body (everything after)
TITLE=$(grep -m1 '^# ' PULL_REQUEST_DRAFT.md | sed 's/^# //')
BODY=$(awk 'f{print} /^# /{f=1}' PULL_REQUEST_DRAFT.md | sed '1{/^$/d}')

if [[ -z "$TITLE" ]]; then
    echo "ERROR: No H1 title found in PULL_REQUEST_DRAFT.md" >&2
    echo "First line must be: # Your PR Title Here" >&2
    exit 1
fi

# Show current branch
BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo ""
echo "Branch:   $BRANCH"
echo "Target:   $UPSTREAM_REPO"
echo "Title:    $TITLE"
echo ""
echo "=== Body ==="
echo "$BODY"
echo "============"
echo ""

if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY RUN] Would remove PULL_REQUEST_DRAFT.md, commit, push, and create PR."
    echo "Re-run without --dry-run to proceed."
    exit 0
fi

# Confirm
read -r -p "Remove draft, push, and create PR on $UPSTREAM_REPO? [y/N] " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Aborted."
    exit 0
fi

# Remove the draft file and commit
echo ""
echo "--- Removing PULL_REQUEST_DRAFT.md ---"
git rm PULL_REQUEST_DRAFT.md
git commit -m "chore: remove PR draft before submission"

# Push the branch
echo ""
echo "--- Pushing $BRANCH to origin ---"
git push origin "$BRANCH"

# Create the PR
echo ""
echo "--- Creating PR on $UPSTREAM_REPO ---"
gh pr create \
    --repo "$UPSTREAM_REPO" \
    --title "$TITLE" \
    --body "$BODY" \
    --head "akaihola:$BRANCH"

echo ""
echo "✓ PR created successfully."
