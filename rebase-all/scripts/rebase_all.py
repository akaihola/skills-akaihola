#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Deterministic helpers for rebasing every branch of a repo onto its base branch.

The judgement calls -- resolving conflicts, rewording commits, deciding what to
delete -- stay with the agent or the human. Everything mechanical lives here so
it behaves identically in every repo, on every machine.

Usage:
    ./rebase_all.py report                       # branch status vs. base
    ./rebase_all.py plan                         # JSON plan incl. stack order
    ./rebase_all.py snapshot --out refs.txt      # record tips, for undo
    ./rebase_all.py rebase BRANCH --map map.txt  # rebase, capture old->new
    ./rebase_all.py rewrite-refs --map map.txt   # fix hash mentions, commit
    ./rebase_all.py restore refs.txt             # undo the whole run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess  # noqa: S404
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import TracebackType

DESCRIPTION = "Rebase every branch onto the base branch, keeping stacks intact."

# A commit mention is 7-40 standalone hex characters. Below 7, abbreviations are
# too ambiguous to rewrite safely; git itself defaults to 7 or more.
MENTION_RE = re.compile(r"\b[0-9a-f]{7,40}\b")

# Branches that are never rebased, even when they are behind the base branch.
DEFAULT_PROTECTED = ("main", "master", "trunk", "develop", "HEAD")

# "<old-sha> <new-sha>" -- two fields are the minimum for a usable map line.
MAP_FIELDS = 2


class GitError(RuntimeError):
    """A git invocation failed, or the repository is not in a usable state."""


def git(
    *args: str,
    cwd: Path | str | None = None,
    check: bool = True,
    stdin: str | None = None,
) -> str:
    """Run git and return its stdout, stripped.

    git is invoked as a subprocess rather than through a shell, so
    command-rewriting shell hooks cannot reshape the output being parsed.
    """
    proc = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        input=stdin,
        check=False,
    )
    if check and proc.returncode != 0:
        detail = proc.stderr.strip()
        message = f"git {' '.join(args)} failed ({proc.returncode}):\n{detail}"
        raise GitError(message)
    return proc.stdout.strip()


def git_ok(*args: str, cwd: Path | str | None = None) -> bool:
    """Run git purely for its exit status."""
    proc = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


# ---------------------------------------------------------------------------
# Repository state
# ---------------------------------------------------------------------------


@dataclass
class Worktree:
    """A checkout attached to the repository."""

    path: Path
    head: str
    branch: str | None
    dirty: bool = False


@dataclass
class Branch:
    """A local branch, measured against the base branch."""

    name: str
    tip: str
    ahead: int  # commits on the branch that the base lacks
    behind: int  # commits on the base that the branch lacks
    worktree: Path | None = None
    dirty: bool = False
    parent: str | None = None  # nearest unmerged branch this one is stacked on
    skip_reason: str | None = None

    @property
    def merged(self) -> bool:
        """Whether every commit of this branch is already in the base branch."""
        return self.ahead == 0


def detect_base_branch(repo: Path, override: str | None = None) -> str:
    """Find the branch that everything else should sit on top of."""
    if override:
        return override
    # origin/HEAD is authoritative wherever the remote publishes it.
    head = git(
        "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", cwd=repo, check=False
    )
    if head:
        return head.rsplit("/", 1)[-1]
    for candidate in ("main", "master", "trunk"):
        if git_ok("rev-parse", "--verify", f"refs/heads/{candidate}", cwd=repo):
            return candidate
    message = "Could not detect a base branch; pass --base explicitly."
    raise GitError(message)


def read_worktrees(repo: Path) -> dict[str, Worktree]:
    """Map each checked-out branch name to the worktree holding it."""
    out = git("worktree", "list", "--porcelain", cwd=repo)
    trees: dict[str, Worktree] = {}
    path: Path | None = None
    head: str | None = None
    branch: str | None = None
    for line in [*out.splitlines(), ""]:
        if line.startswith("worktree "):
            path = Path(line.removeprefix("worktree "))
        elif line.startswith("HEAD "):
            head = line.removeprefix("HEAD ")
        elif line.startswith("branch refs/heads/"):
            branch = line.removeprefix("branch refs/heads/")
        elif not line.strip() and path is not None:
            if branch:
                # Untracked files never block a rebase, so they must not
                # count as dirty; only tracked modifications do.
                dirty = bool(
                    git(
                        "status",
                        "--porcelain",
                        "--untracked-files=no",
                        cwd=path,
                        check=False,
                    )
                )
                trees[branch] = Worktree(
                    path=path, head=head or "", branch=branch, dirty=dirty
                )
            path = head = branch = None
    return trees


def read_branches(
    repo: Path, base: str, protected: tuple[str, ...]
) -> dict[str, Branch]:
    """Collect every local branch with its ahead/behind counts and worktree."""
    raw = git(
        "for-each-ref",
        "--format=%(objectname) %(refname:short)",
        "refs/heads",
        cwd=repo,
    )
    trees = read_worktrees(repo)
    branches: dict[str, Branch] = {}
    for line in raw.splitlines():
        tip, name = line.split(" ", 1)
        if name in protected:
            continue
        counts = git(
            "rev-list", "--left-right", "--count", f"{base}...{name}", cwd=repo
        )
        behind, ahead = (int(n) for n in counts.split())
        tree = trees.get(name)
        branches[name] = Branch(
            name=name,
            tip=tip,
            ahead=ahead,
            behind=behind,
            worktree=tree.path if tree else None,
            dirty=tree.dirty if tree else False,
        )
    return branches


def detect_stacks(repo: Path, branches: dict[str, Branch]) -> None:
    """Record, for each branch, the nearest unmerged branch it is stacked on.

    Only unmerged branches can be stack parents. A branch whose commits already
    reached the base contributes nothing to its descendants, so treating it as a
    parent would invent a stack that does not exist.
    """
    candidates = [b for b in branches.values() if not b.merged]
    for child in candidates:
        best: Branch | None = None
        best_depth = -1
        for parent in candidates:
            if parent.name == child.name:
                continue
            if not git_ok(
                "merge-base", "--is-ancestor", parent.tip, child.tip, cwd=repo
            ):
                continue
            # The nearest parent is the one contributing the most commits.
            depth = int(git("rev-list", "--count", parent.tip, cwd=repo))
            if depth > best_depth:
                best, best_depth = parent, depth
        child.parent = best.name if best else None


def rebase_order(branches: dict[str, Branch]) -> list[str]:
    """Order branches so a stack parent is always rebased before its child."""
    order: list[str] = []
    seen: set[str] = set()

    def visit(name: str, trail: tuple[str, ...] = ()) -> None:
        if name in seen:
            return
        if name in trail:
            message = f"Cycle in branch stack: {' -> '.join((*trail, name))}"
            raise GitError(message)
        branch = branches[name]
        if branch.parent:
            visit(branch.parent, (*trail, name))
        seen.add(name)
        order.append(name)

    for name in sorted(branches):
        visit(name)
    return order


def classify(branches: dict[str, Branch], ancient: int) -> None:
    """Attach a skip_reason to every branch that must not be rebased."""
    for branch in branches.values():
        if branch.merged and branch.behind == 0:
            branch.skip_reason = "already up to date with base"
        elif branch.merged:
            branch.skip_reason = "merged into base; cleanup candidate, not a rebase"
        elif branch.dirty:
            branch.skip_reason = f"uncommitted changes in {branch.worktree}"
        elif ancient and branch.behind > ancient:
            branch.skip_reason = f"ancient: {branch.behind} behind base (> {ancient})"


# ---------------------------------------------------------------------------
# Worktree handling
# ---------------------------------------------------------------------------


class BranchCheckout:
    """A directory in which a branch is checked out and can be rebased.

    A branch already checked out somewhere is rebased in place, because git
    refuses to move it from anywhere else. A branch with no worktree gets a
    temporary one, so the caller's own checkout is never disturbed.
    """

    def __init__(self, repo: Path, branch: Branch) -> None:
        """Prepare a checkout handle for `branch` in `repo`."""
        self.repo = repo
        self.branch = branch
        self.temp: Path | None = None

    def __enter__(self) -> Path:
        """Return a worktree path where the branch is checked out."""
        if self.branch.worktree:
            return self.branch.worktree
        self.temp = Path(tempfile.mkdtemp(prefix="rebase-all-"))
        target = self.temp / "wt"
        git("worktree", "add", str(target), self.branch.name, cwd=self.repo)
        return target

    def keep(self) -> None:
        """Stop the temporary worktree from being removed on exit."""
        self.temp = None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Remove the temporary worktree, if one was created."""
        if self.temp:
            git(
                "worktree",
                "remove",
                "--force",
                str(self.temp / "wt"),
                cwd=self.repo,
                check=False,
            )
            shutil.rmtree(self.temp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Rewrite map
# ---------------------------------------------------------------------------

HOOK_BODY = dedent(
    """\
    #!/usr/bin/env bash
    # git feeds "<old-sha> <new-sha>" per rewritten commit on stdin.
    out="$REBASE_ALL_MAP"
    while read -r old new _; do printf '%s %s\\n' "$old" "$new" >> "$out"; done
    """
)


class RewriteCapture:
    """A throwaway hooks directory recording git's own old->new commit map.

    This is the only exact source of commit identity across a rebase. Pairing up
    commit lists from before and after guesses wrong the moment a commit is
    dropped, skipped or squashed.
    """

    def __init__(self, map_path: Path) -> None:
        """Record where the captured map should be appended."""
        self.map_path = map_path
        self.dir: Path | None = None

    def __enter__(self) -> Path:
        """Create the hooks directory and return its path."""
        self.dir = Path(tempfile.mkdtemp(prefix="rebase-all-hooks-"))
        hook = self.dir / "post-rewrite"
        hook.write_text(HOOK_BODY, encoding="utf-8")
        hook.chmod(0o755)
        return self.dir

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Remove the hooks directory."""
        if self.dir:
            shutil.rmtree(self.dir, ignore_errors=True)


def load_map(map_path: Path) -> dict[str, str]:
    """Read the captured pairs and collapse them transitively to old -> final.

    An amend, or a second rebase of the same branch, appends another hop
    (A->B, then B->C). Without collapsing, documents would be rewritten to B,
    a commit that no longer exists.
    """
    if not map_path.exists():
        return {}
    pairs: dict[str, str] = {}
    for line in map_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= MAP_FIELDS:
            pairs[parts[0]] = parts[1]

    collapsed: dict[str, str] = {}
    for old, first in pairs.items():
        seen = {old}
        new = first
        while new in pairs and new not in seen:
            seen.add(new)
            new = pairs[new]
        if new != old:
            collapsed[old] = new
    return collapsed


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def load_state(args: argparse.Namespace) -> tuple[Path, str, dict[str, Branch]]:
    """Resolve the repo, base branch and classified branch set from CLI args."""
    repo = Path(args.repo).resolve()
    base = detect_base_branch(repo, args.base)
    branches = read_branches(repo, base, tuple(args.protected))
    detect_stacks(repo, branches)
    classify(branches, args.ancient)
    return repo, base, branches


def cmd_plan(args: argparse.Namespace) -> int:
    """Emit a JSON plan describing what would be rebased, and in what order."""
    repo, base, branches = load_state(args)
    order = [n for n in rebase_order(branches) if not branches[n].skip_reason]
    plan = {
        "repo": str(repo),
        "base": base,
        "base_tip": git("rev-parse", base, cwd=repo),
        "order": order,
        "branches": [
            {
                "name": b.name,
                "tip": b.tip,
                "ahead": b.ahead,
                "behind": b.behind,
                "merged": b.merged,
                "worktree": str(b.worktree) if b.worktree else None,
                "dirty": b.dirty,
                "parent": b.parent,
                "skip_reason": b.skip_reason,
            }
            for b in sorted(branches.values(), key=lambda b: b.name)
        ],
    }
    print(json.dumps(plan, indent=2))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Print a human-readable status of every branch against the base."""
    repo, base, branches = load_state(args)
    width = max((len(b) for b in branches), default=10)
    print(f"base: {base} @ {git('rev-parse', '--short', base, cwd=repo)}\n")
    for b in sorted(branches.values(), key=lambda b: b.name):
        state = "rebased" if b.ahead and not b.behind else b.skip_reason or "TO REBASE"
        stack = f"  (stacked on {b.parent})" if b.parent else ""
        print(f"{b.name:<{width}}  +{b.ahead:<3} -{b.behind:<4} {state}{stack}")
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    """Record every branch tip so the whole run can be undone later."""
    repo = Path(args.repo).resolve()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    refs = git(
        "for-each-ref", "--format=%(objectname) %(refname)", "refs/heads", cwd=repo
    )
    out.write_text(refs + "\n", encoding="utf-8")
    print(f"Snapshotted {len(refs.splitlines())} branches to {out}")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    """Reset branches back to the tips recorded in a snapshot."""
    repo = Path(args.repo).resolve()
    trees = read_worktrees(repo)
    restored = blocked = 0
    for line in Path(args.snapshot).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        sha, ref = line.split(" ", 1)
        name = ref.removeprefix("refs/heads/")
        current = git("rev-parse", "--verify", "--quiet", ref, cwd=repo, check=False)
        if current == sha:
            continue
        tree = trees.get(name)
        if tree and tree.dirty:
            print(f"SKIP {name}: worktree dirty ({tree.path})", file=sys.stderr)
            blocked += 1
            continue
        if tree:
            git("reset", "--hard", sha, cwd=tree.path)
        else:
            git("update-ref", ref, sha, cwd=repo)
        print(f"restored {name} -> {sha[:12]}")
        restored += 1
    print(f"{restored} restored, {blocked} blocked")
    return 1 if blocked else 0


def cmd_rebase(args: argparse.Namespace) -> int:
    """Rebase one branch onto the base, capturing git's own rewrite map."""
    repo, base, branches = load_state(args)
    if args.branch not in branches:
        print(f"No such branch: {args.branch}", file=sys.stderr)
        return 1
    branch = branches[args.branch]
    if branch.dirty:
        print(f"Refusing: {branch.worktree} has uncommitted changes", file=sys.stderr)
        return 1

    map_path = Path(args.map).resolve()
    map_path.parent.mkdir(parents=True, exist_ok=True)

    checkout = BranchCheckout(repo, branch)
    with checkout as tree, RewriteCapture(map_path) as hooks:
        env = {**os.environ, "REBASE_ALL_MAP": str(map_path)}
        cmd = ["git", "-c", f"core.hooksPath={hooks}", "rebase"]
        if args.onto:
            # Stacked branch: replay only this branch's own commits onto the
            # already-rebased parent, cutting at the parent's OLD tip.
            cmd += ["--onto", args.onto, args.upstream or base]
        else:
            cmd += [base]
        proc = subprocess.run(  # noqa: S603
            cmd, cwd=str(tree), env=env, text=True, capture_output=True, check=False
        )
        sys.stderr.write(proc.stderr)
        sys.stdout.write(proc.stdout)
        if proc.returncode != 0:
            conflicts = git(
                "diff", "--name-only", "--diff-filter=U", cwd=tree, check=False
            )
            # A temporary worktree has to survive so the conflict can be fixed.
            checkout.keep()
            print(
                dedent(
                    f"""
                    CONFLICT rebasing {branch.name}
                    worktree: {tree}
                    files:
                    {conflicts or "  (none reported)"}

                    Resolve there, `git add` them, then `git rebase --continue`
                    -- or `git rebase --abort` to leave the branch untouched.
                    """
                ).strip(),
                file=sys.stderr,
            )
            return 2

    print(f"rebased {branch.name} onto {base}")
    return 0


def iter_text_files(worktree: Path) -> list[Path]:
    """List every tracked file in a worktree."""
    files = git("ls-files", "-z", cwd=worktree).split("\0")
    return [worktree / f for f in files if f]


def cmd_rewrite_refs(args: argparse.Namespace) -> int:
    """Rewrite commit-hash mentions in tracked files, then commit the result."""
    repo = Path(args.repo).resolve()
    worktree = Path(args.worktree).resolve() if args.worktree else repo
    mapping = load_map(Path(args.map))
    if not mapping:
        print("Empty rewrite map; nothing to do.")
        return 0

    changed: list[Path] = []
    edits: list[tuple[str, str, str]] = []
    current: Path = worktree

    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        hits = [old for old in mapping if old.startswith(token)]
        if len(hits) != 1:
            # Unknown commit, or ambiguous between two rewritten commits.
            return token
        # Ask git for an abbreviation of the same length; git lengthens it on
        # its own if that would be ambiguous in the rewritten history.
        short = git("rev-parse", f"--short={len(token)}", mapping[hits[0]], cwd=repo,
                    check=False)
        if not short:
            return token
        edits.append((token, short, str(current.relative_to(worktree))))
        return short

    for path in iter_text_files(worktree):
        current = path
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        new_text = MENTION_RE.sub(replace, text)
        if new_text != text:
            if not args.dry_run:
                path.write_text(new_text, encoding="utf-8")
            changed.append(path)

    for old, new, where in edits:
        print(f"{where}: {old} -> {new}")
    if not changed:
        print("No commit-hash mentions needed rewriting.")
        return 0
    print(f"{len(edits)} mentions in {len(changed)} files")
    if args.dry_run:
        return 0

    git("add", "--", *[str(p) for p in changed], cwd=worktree)
    message = args.message or dedent(
        """\
        docs: update commit hash references after rebase

        Mentions of commits rewritten by the rebase now point at their new
        hashes. Generated by the rebase-all skill.
        """
    )
    # A separate trailing commit, never an amend: amending would rewrite the
    # very hashes just written into these documents.
    git("commit", "--no-verify", "-m", message, cwd=worktree)
    print("committed hash-reference fixups")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Construct the command-line parser."""
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("--repo", default=".", help="repository or worktree path")
    parser.add_argument("--base", help="base branch (default: autodetect)")
    parser.add_argument(
        "--protected",
        nargs="*",
        default=list(DEFAULT_PROTECTED),
        help="branches that are never rebased",
    )
    parser.add_argument(
        "--ancient",
        type=int,
        default=300,
        help="skip branches this far behind base (0 disables)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("plan", help="emit a JSON rebase plan").set_defaults(func=cmd_plan)
    sub.add_parser("report", help="human-readable branch status").set_defaults(
        func=cmd_report
    )

    p = sub.add_parser("snapshot", help="record branch tips for undo")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_snapshot)

    p = sub.add_parser("restore", help="reset branches to a snapshot")
    p.add_argument("snapshot")
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("rebase", help="rebase one branch, capturing the rewrite map")
    p.add_argument("branch")
    p.add_argument("--map", required=True, help="rewrite map file, appended to")
    p.add_argument("--onto", help="new parent tip, for a stacked branch")
    p.add_argument("--upstream", help="old parent tip, for a stacked branch")
    p.set_defaults(func=cmd_rebase)

    p = sub.add_parser("rewrite-refs", help="fix commit-hash mentions in documents")
    p.add_argument("--map", required=True)
    p.add_argument("--worktree", help="where to rewrite (default: --repo)")
    p.add_argument("--message", help="commit message override")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_rewrite_refs)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the chosen subcommand."""
    args = build_parser().parse_args(argv)
    try:
        result: int = args.func(args)
    except GitError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
