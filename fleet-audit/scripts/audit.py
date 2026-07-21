#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Audit skill deployments across a fleet of accounts and report only anomalies.

Answers "is every deployment of this skills repo current?" in one command. Sweeps
each configured account over SSH, compares what it finds against the canonical
checkout, and prints nothing but the problems.

The fleet itself lives in a config file supplied by the caller — this script
ships no account names, hostnames, or paths of its own.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess  # noqa: S404
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# Answers "is this commit a descendant of the expected ref?" — i.e. does the
# checkout carry unpushed work rather than lag behind.
Ahead = Callable[[str], bool]

# Emitted per target; keeps the same hashing algorithm on both sides of the
# comparison by running the identical shell function everywhere.
SCANNER = r"""
set -u
skills=$1; surfaces=$2; maxdepth=$3; excludes=${4:-}
printf 'HOME\t%s\n' "$HOME"

# Dead trees — backups, scratch copies, trash — are excluded at the source so
# they never cross the wire.
excluded() {
  for pat in $excludes; do case "$1" in *"$pat"*) return 0;; esac; done
  return 1
}

hashdir() {
  find "$1/" -type f \
      -not -path '*/.git/*' -not -path '*/__pycache__/*' \
      -not -path '*/.venv/*' -not -name '*.pyc' 2>/dev/null \
    | sed "s|^$1/||" | sort \
    | while read -r f; do
        printf '%s ' "$f"; sha256sum "$1/$f" 2>/dev/null | cut -c1-16
      done | sha256sum | cut -c1-12
}

is_skill() { case " $skills " in *" $1 "*) return 0;; esac; return 1; }

# Checkouts of the skills repo itself.
find "$HOME" -maxdepth "$maxdepth" -type d -name .git \
    -not -path '*/node_modules/*' 2>/dev/null |
while read -r g; do
  p=${g%/.git}
  excluded "$p" && continue
  url=$(git -C "$p" config --get remote.origin.url 2>/dev/null) || continue
  case "$url" in
    *"$REPO_SLUG"*)
      printf 'CHECKOUT\t%s\t%s\t%s\t%s\n' "$p" \
        "$(git -C "$p" rev-parse HEAD 2>/dev/null)" \
        "$(git -C "$p" rev-parse --abbrev-ref HEAD 2>/dev/null)" \
        "$(git -C "$p" status --porcelain 2>/dev/null | grep -vc '^??')"
      ;;
  esac
done

# Deployment surfaces: every directory an agent harness reads skills from.
for surface in $surfaces; do
  find "$HOME" -maxdepth "$maxdepth" -type d -path "*/$surface" \
      -not -path '*/node_modules/*' -not -path '*/.git/*' 2>/dev/null |
  while read -r s; do
    excluded "$s" && continue
    for e in "$s"/*; do
      [ -e "$e" ] || [ -L "$e" ] || continue
      n=$(basename "$e"); tgt=""
      [ -L "$e" ] && tgt=$(readlink "$e")
      relevant=0
      is_skill "$n" && relevant=1
      case "$tgt" in *"$REPO_SLUG"*) relevant=1;; esac
      [ "$relevant" = 1 ] || continue
      if [ -L "$e" ]; then
        state=ok; [ -e "$e" ] || state=broken
        printf 'LINK\t%s\t%s\t%s\n' "$e" "$tgt" "$state"
      elif [ -d "$e" ]; then
        printf 'COPY\t%s\t%s\n' "$e" "$(hashdir "$e")"
      fi
    done
  done
done
"""


@dataclass(frozen=True)
class Target:
    """One account to audit. An empty host means "run here, without SSH"."""

    host: str

    @property
    def label(self) -> str:
        """Human-readable name for report headings."""
        return self.host or "local"


@dataclass
class Config:
    """Parsed audit configuration."""

    repo_path: Path
    repo_slug: str
    ref: str
    surfaces: list[str]
    max_depth: int
    exclude: list[str]
    allow_link_prefixes: list[str]
    targets: list[Target]


@dataclass
class Finding:
    """A single anomaly worth a human's attention."""

    target: str
    kind: str
    path: str
    detail: str


@dataclass
class Scan:
    """Raw records returned by one target's scanner run."""

    home: str = ""
    checkouts: list[tuple[str, str, str, int]] = field(default_factory=list)
    links: list[tuple[str, str, str]] = field(default_factory=list)
    copies: list[tuple[str, str]] = field(default_factory=list)


def load_config(path: Path) -> Config:
    """Read the TOML fleet definition."""
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    repo = raw["repo"]
    scan = raw.get("scan", {})
    return Config(
        repo_path=Path(repo["path"]).expanduser(),
        repo_slug=repo["slug"],
        ref=repo.get("ref", "origin/main"),
        surfaces=scan.get("surfaces", [".claude/skills"]),
        max_depth=int(scan.get("max_depth", 8)),
        exclude=scan.get("exclude", []),
        allow_link_prefixes=scan.get("allow_link_prefixes", []),
        targets=[Target(host=t.get("host", "")) for t in raw.get("targets", [])],
    )


def run_scanner(target: Target, cfg: Config, skills: list[str]) -> Scan:
    """Execute the scanner on one target and parse its TSV output."""
    args = [
        " ".join(sorted(skills)),
        " ".join(cfg.surfaces),
        str(cfg.max_depth),
        " ".join(cfg.exclude),
    ]
    inner = f"REPO_SLUG={shlex.quote(cfg.repo_slug)}; " + SCANNER
    command = ["bash", "-s", "--", *args]
    if target.host:
        command = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            target.host,
            "bash -s -- " + " ".join(shlex.quote(a) for a in args),
        ]
    proc = subprocess.run(  # noqa: S603
        command,
        input=inner,
        capture_output=True,
        text=True,
        check=False,
        timeout=900,
    )
    return parse_scan(proc.stdout)


def parse_scan(stdout: str) -> Scan:
    """Turn scanner TSV lines into a Scan."""
    scan = Scan()
    for line in stdout.splitlines():
        parts = line.split("\t")
        match parts:
            case ["HOME", home]:
                scan.home = home
            case ["CHECKOUT", path, sha, branch, dirty]:
                scan.checkouts.append((path, sha, branch, int(dirty or 0)))
            case ["LINK", path, tgt, state]:
                scan.links.append((path, tgt, state))
            case ["COPY", path, digest]:
                scan.copies.append((path, digest))
            case _:
                continue
    return scan


def repo_skills(repo_path: Path) -> list[str]:
    """Names of every skill directory in the canonical checkout."""
    return sorted(p.parent.name for p in repo_path.glob("*/SKILL.md"))


def repo_hashes(repo_path: Path, skills: list[str]) -> dict[str, str]:
    """Per-skill digests, computed by the same shell function the targets use."""
    script = SCANNER.split("is_skill()", maxsplit=1)[0] + "\n".join(
        f'printf "%s\\t%s\\n" {shlex.quote(s)} "$(hashdir {shlex.quote(s)})"'
        for s in skills
    )
    proc = subprocess.run(
        ["bash", "-s", "--", "", "", "1"],  # noqa: S607
        input=f"REPO_SLUG=x; cd {shlex.quote(str(repo_path))}\n{script}",
        capture_output=True,
        text=True,
        check=False,
    )
    out: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        name, _, digest = line.partition("\t")
        if digest and name in set(skills):
            out[name] = digest
    return out


def make_ahead(repo_path: Path, expected: str) -> Ahead:
    """Build a predicate telling whether a sha is a descendant of `expected`.

    Distinguishes a clone carrying unpushed work from one that simply lags. A
    sha the canonical checkout has never heard of counts as behind.
    """

    def ahead(sha: str) -> bool:
        proc = subprocess.run(  # noqa: S603
            ["git", "-C", str(repo_path),  # noqa: S607
             "merge-base", "--is-ancestor", expected, sha],
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.returncode == 0

    return ahead


def canonical_sha(repo_path: Path, ref: str) -> str:
    """Resolve the reference every deployment is expected to match."""
    proc = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo_path), "rev-parse", ref],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def analyse(target: Target, scan: Scan, cfg: Config, expected: str,
            hashes: dict[str, str], ahead: Ahead) -> list[Finding]:
    """Compare one target's scan against the canonical repo state."""
    found: list[Finding] = []
    for path, sha, branch, dirty in scan.checkouts:
        if sha != expected:
            kind = "ahead-checkout" if ahead(sha) else "stale-checkout"
            note = "unpushed commits" if kind == "ahead-checkout" else "behind"
            found.append(Finding(target.label, kind, path,
                                 f"{sha[:7]} on {branch}, {note} vs {expected[:7]}"))
        if dirty:
            found.append(Finding(target.label, "dirty-checkout", path,
                                 f"{dirty} tracked modification(s)"))
    for path, tgt, state in scan.links:
        allowed = any(tgt.startswith(p) for p in cfg.allow_link_prefixes)
        if state == "broken":
            found.append(Finding(target.label, "broken-link", path, f"-> {tgt}"))
        elif tgt.startswith("/") and scan.home and not allowed \
                and not tgt.startswith(scan.home):
            found.append(Finding(target.label, "external-link", path,
                                 f"-> {tgt} (absolute, outside {scan.home})"))
    for path, digest in scan.copies:
        name = Path(path).name
        want = hashes.get(name)
        if want and digest != want:
            found.append(Finding(target.label, "drifted-copy", path,
                                 f"{digest} != repo {want}"))
        elif want:
            found.append(Finding(target.label, "copy-not-link", path,
                                 "matches repo now, but will drift silently"))
    return found


def main() -> int:
    """Run the audit and report anomalies."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="TOML fleet definition")
    parser.add_argument("--quiet", action="store_true",
                        help="suppress the per-target progress line")
    args = parser.parse_args()

    cfg = load_config(args.config)
    skills = repo_skills(cfg.repo_path)
    expected = canonical_sha(cfg.repo_path, cfg.ref)
    hashes = repo_hashes(cfg.repo_path, skills)
    ahead = make_ahead(cfg.repo_path, expected)

    if not args.quiet:
        print(f"canonical {cfg.ref} = {expected[:7]}  ({len(skills)} skills)",
              file=sys.stderr)

    findings: list[Finding] = []
    for target in cfg.targets:
        if not args.quiet:
            print(f"  scanning {target.label} ...", file=sys.stderr)
        findings.extend(
            analyse(target, run_scanner(target, cfg, skills), cfg, expected,
                    hashes, ahead),
        )

    if not findings:
        print("OK - every deployment matches the canonical checkout")
        return 0

    width = max(len(f.kind) for f in findings)
    current = ""
    for finding in sorted(findings, key=lambda f: (f.target, f.kind, f.path)):
        if finding.target != current:
            current = finding.target
            print(f"\n{current}")
        indent = " " * (width + 4)
        print(f"  {finding.kind:<{width}}  {finding.path}\n{indent}{finding.detail}")
    print(f"\n{len(findings)} anomal{'y' if len(findings) == 1 else 'ies'}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
