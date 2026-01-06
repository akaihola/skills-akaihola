#!/usr/bin/env python3
"""
Helper script for the conventional-committer skill.

Collect recent Git commit messages and staged changes, then emit them in
chunks of up to 16384 characters.

If the total output (recent commits + staged diff) fits within the limit,
return a single chunk. Otherwise, split the output into multiple chunks,
preferably at file boundaries in the staged diff, but split within a single
file's diff when that file alone exceeds the limit.

Each invocation prints a single chunk and, when additional chunks exist,
prints the exact command needed to retrieve the next chunk.

Intended usage from the conventional-committer skill directory:

    python3 scripts/git_context_chunks.py
    python3 scripts/git_context_chunks.py --chunk-index 1

This script is intentionally self-contained and does not depend on the rest
of the project code.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import List

CHAR_LIMIT = 16384


def run_git_command(args: List[str]) -> str:
    """Run a Git command with pager disabled and return stdout as text.

    Raises RuntimeError on non-zero exit.
    """
    env = os.environ.copy()
    # Ensure Git never invokes an interactive pager
    env.setdefault("GIT_PAGER", "cat")

    result = subprocess.run(
        ["git", "--no-pager", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed with exit code {result.returncode}:\n"
            f"{result.stderr.strip()}"
        )

    return result.stdout


def get_recent_commits() -> str:
    """Return a formatted section with the 5 most recent commits.

    Uses the format: git log -n5 --format="commit %h%n%B%n--------------"
    """
    format_str = "commit %h%n%B%n--------------"
    output = run_git_command(["log", "-n5", f"--format={format_str}"])

    if not output.strip():
        return "== Recent commits (last 5) ==\n(no commits found)\n\n"

    return "== Recent commits (last 5) ==\n" + output.strip() + "\n\n"


def split_diff_by_file(diff_body: str) -> List[str]:
    """Split a staged diff into blocks per file.

    The input should be the raw output from:
        git --no-pager diff --cached
    """
    blocks: List[str] = []
    current: List[str] = []

    for line in diff_body.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current:
                blocks.append("".join(current))
                current = []
        current.append(line)

    if current:
        blocks.append("".join(current))

    return blocks


def fine_grain_segments(segments: List[str], limit: int) -> List[str]:
    """Ensure no segment is longer than limit, splitting on newlines when possible.

    This is used when a single file's diff (or another logical segment)
    exceeds the limit; in that case, split the segment into multiple pieces,
    trying to cut at newline boundaries while respecting the character limit.
    """
    fine: List[str] = []

    for seg in segments:
        if len(seg) <= limit:
            fine.append(seg)
            continue

        start = 0
        while start < len(seg):
            end = min(start + limit, len(seg))
            # Prefer to cut at the last newline within the allowed window
            newline_pos = seg.rfind("\n", start + 1, end)
            if newline_pos == -1 or newline_pos <= start:
                cut = end
            else:
                cut = newline_pos + 1

            fine.append(seg[start:cut])
            start = cut

    return fine


def build_chunks(char_limit: int) -> List[str]:
    """Build all output chunks within the given character limit."""
    recent_section = get_recent_commits()

    # Collect staged diff once, then structure it for chunking
    raw_diff = run_git_command(["diff", "--cached"])

    segments: List[str] = [recent_section]

    if raw_diff.strip():
        staged_header = "== Staged changes (git --no-pager diff --cached) ==\n"
        segments.append(staged_header)
        file_blocks = split_diff_by_file(raw_diff)
        segments.extend(file_blocks)
    else:
        segments.append(
            "== Staged changes (git --no-pager diff --cached) ==\n(no staged changes)\n"
        )

    full_text = "".join(segments)

    # If everything fits within the limit, return a single chunk
    if len(full_text) <= char_limit:
        return [full_text]

    # Otherwise, ensure individual segments do not exceed the limit, then
    # combine them into chunks while keeping file boundaries when possible.
    fine_segments = fine_grain_segments(segments, char_limit)

    chunks: List[str] = []
    current = ""

    for seg in fine_segments:
        if not current:
            current = seg
            continue

        if len(current) + len(seg) <= char_limit:
            current += seg
        else:
            chunks.append(current)
            current = seg

    if current:
        chunks.append(current)

    return chunks


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Collect recent commits and staged changes and emit them in chunks of "
            f"up to {CHAR_LIMIT} characters."
        )
    )
    parser.add_argument(
        "--chunk-index",
        type=int,
        default=0,
        help="Zero-based index of the chunk to output (default: 0).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=CHAR_LIMIT,
        help=f"Maximum characters per chunk (default: {CHAR_LIMIT}).",
    )

    args = parser.parse_args(argv)

    try:
        chunks = build_chunks(args.limit)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if not chunks:
        print(
            "No Git data available (no commits and no staged changes).", file=sys.stderr
        )
        return 0

    if args.chunk_index < 0 or args.chunk_index >= len(chunks):
        print(
            f"Requested --chunk-index {args.chunk_index} is out of range; "
            f"there are {len(chunks)} chunk(s).",
            file=sys.stderr,
        )
        return 2

    current_index = args.chunk_index
    total = len(chunks)
    chunk = chunks[current_index]

    # Print the selected chunk with simple markers to clarify boundaries
    print(f"[conventional-committer] chunk {current_index + 1}/{total}")
    # Avoid adding an extra newline if the chunk already ends with one
    print(chunk, end="" if chunk.endswith("\n") else "\n")
    print(f"[conventional-committer] end of chunk {current_index + 1}/{total}")

    # If there are more chunks, print the exact command to fetch the next one
    if current_index + 1 < total:
        script_path = (
            os.path.relpath(sys.argv[0]) if os.path.isabs(sys.argv[0]) else sys.argv[0]
        )
        next_index = current_index + 1
        if args.limit != CHAR_LIMIT:
            next_cmd = (
                f"python3 {script_path} --chunk-index {next_index} --limit {args.limit}"
            )
        else:
            next_cmd = f"python3 {script_path} --chunk-index {next_index}"
        print(
            f"[conventional-committer] Next chunk command:\n{next_cmd}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
