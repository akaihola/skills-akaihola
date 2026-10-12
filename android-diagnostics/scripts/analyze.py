#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Parse a collected workdir into analysis.json: metrics, tables and findings.

Input is a workdir written by collect.py (live/*.txt, bugreport*.zip,
manifest.json). To analyse a bugreport zip obtained elsewhere, pass
--bugreport ZIP and a new workdir: the zip is linked into it. Any zip in the
workdir that holds a dumpstate text is used, whatever its name. Inputs that
cannot be read (a truncated zip, a broken manifest.json) are left out and
listed under "notes".

Exit codes:
  0  all analyzers ran or were skipped for missing inputs
  2  usage error, or the workdir holds no usable data
  3  at least one analyzer failed with an exception (analysis.json is still
     written; failures are listed under "errors")
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from androiddiag.common import PackageMap
from androiddiag.model import (
    SEVERITY_RANK,
    Context,
    Result,
    SkipError,
    Windows,
    run_order,
)
from androiddiag.registry import load_analyzers
from androiddiag.source import Bugreport, Sources, Workdir

if sys.version_info < (3, 11):  # ruff: ignore[outdated-version-block] - message for users of old Python
    sys.exit("analyze.py needs Python 3.11 or newer")


def build_packages(sources: Sources) -> PackageMap:
    """Merge every available UID-to-package listing.

    ``third_party`` comes from ``pm list packages -3``; without it, from the
    packages that ``dumpsys package`` does not flag as SYSTEM.
    """
    packages = PackageMap.empty()
    third_party: frozenset[int] = frozenset()
    for key in ("packages_uid", "packages_3p"):
        if text := sources.get(key):
            listed = PackageMap.from_pm_list(text.text)
            packages = packages.merge(listed)
            if key == "packages_3p":
                third_party = frozenset(listed.by_app_id)
    if text := sources.get("package"):
        dump = PackageMap.from_package_dump(text.text)
        packages = packages.merge(dump)
        third_party = third_party or dump.third_party
    if text := sources.get("batterystats_checkin"):
        packages = packages.merge(PackageMap.from_checkin(text.text))
    packages.third_party = third_party
    return packages


# Header fields that identify the build, not the person: the bugreport header
# also carries the kernel command line with the serial number and Wi-Fi MAC.
DEVICE_FIELDS = (
    "dumpstate_time",
    "build",
    "build_fingerprint",
    "android_sdk_version",
    "radio",
    "kernel",
    "uptime",
)


def device_from_header(bugreport: Bugreport | None) -> dict[str, str]:
    """Return the non-identifying build fields of a bugreport header."""
    if bugreport is None:
        return {}
    return {k: v for k, v in bugreport.header.items() if k in DEVICE_FIELDS}


def run(workdir: Workdir, only: set[str] | None) -> dict:
    """Run the analyzers and return the analysis document."""
    sources = Sources(workdir)
    registry, import_errors = load_analyzers()
    ctx = Context(
        sources=sources,
        packages=build_packages(sources),
        windows=Windows(),
    )
    errors: dict[str, str] = {f"module {m}": e for m, e in import_errors.items()}
    for reg in run_order(registry):
        if only and reg.name not in only and reg.name != "windows":
            continue
        missing = [k for k in reg.requires if not sources.has(k)]
        if missing:
            result = Result(
                reg.name,
                status="skipped",
                reason=f"missing inputs: {', '.join(missing)}",
            )
        else:
            try:
                result = reg.func(ctx)
            except SkipError as exc:
                result = Result(reg.name, status="skipped", reason=str(exc))
            except Exception as exc:  # ruff: ignore[blind-except] - keep other analyzers
                tb = traceback.format_exc(limit=-3)
                result = Result(reg.name, status="error", reason=f"{exc!r}")
                errors[reg.name] = tb
        ctx.results[reg.name] = result

    findings = [f for r in ctx.results.values() for f in r.findings]
    findings.sort(key=lambda f: (SEVERITY_RANK.get(f.severity, 9), f.id))
    br = workdir.bugreport
    doc = {
        "schema": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "workdir": str(workdir.root),
        "device": workdir.manifest.get("device") or device_from_header(br),
        "windows": ctx.windows.to_dict(),
        "sources": sources.available(),
        "results": {name: r.to_dict() for name, r in ctx.results.items()},
        "findings": [
            {**f.__dict__, "evidence": [e.__dict__ for e in f.evidence]}
            for f in findings
        ],
        "errors": errors,
    }
    # Read last: opening the bugreport and the manifest records their problems.
    doc["notes"] = workdir.problems
    return doc


def json_default(value: object) -> object:
    """Serialise sets as sorted lists (deterministic output); str() the rest."""
    if isinstance(value, set | frozenset):
        return sorted(value, key=str)
    return str(value)


# Keep the terminal summary short: harnesses truncate long tool output.
MAX_SUMMARY_FINDINGS = 12


def summarize(doc: dict, out: Path) -> str:
    """Return a compact text summary for the terminal."""
    results = doc["results"].values()
    counts = {
        status: sum(1 for r in results if r["status"] == status)
        for status in ("ok", "skipped", "error")
    }
    lines = [
        f"analysis: {out}",
        (
            f"analyzers: {counts['ok']} ok, {counts['skipped']} skipped, "
            f"{counts['error']} failed"
        ),
    ]
    lines += [f"  note: {note}" for note in doc.get("notes", [])]
    lines.extend(
        f"{finding['title']}: {finding['summary'].splitlines()[0]}"
        for finding in doc["findings"]
        if finding["id"].startswith("bottom_line.") and finding["summary"]
    )
    ranked = [f for f in doc["findings"] if f["severity"] in {"high", "medium"}]
    lines += [
        f"  [{f['severity']}/{f['basis']}] {f['id']}: {f['title']}"
        for f in ranked[:MAX_SUMMARY_FINDINGS]
    ]
    if len(ranked) > MAX_SUMMARY_FINDINGS:
        lines.append(
            f"  ... {len(ranked) - MAX_SUMMARY_FINDINGS} more high/medium findings "
            "in analysis.json",
        )
    lines += [
        f"  error in {name}: {error.strip().splitlines()[-1]}"
        for name, error in doc["errors"].items()
    ]
    lines.append("next: report.py renders the full Markdown report")
    return "\n".join(lines)


def main() -> int:
    """Parse arguments, run the analysis and write analysis.json."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "workdir",
        type=Path,
        nargs="?",
        help="directory from collect.py (not needed with --list)",
    )
    parser.add_argument(
        "--bugreport",
        type=Path,
        help="analyse this bugreport zip; it is linked into WORKDIR",
    )
    parser.add_argument(
        "--only",
        help="comma-separated analyzer names to run (windows always runs)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="where to write the JSON (default: WORKDIR/analysis.json)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list analyzers and their required inputs, then exit",
    )
    args = parser.parse_args()

    if args.list:
        registry, import_errors = load_analyzers()
        for reg in run_order(registry):
            needs = ", ".join(reg.requires) or "-"
            print(f"{reg.name:32} {reg.module.rsplit('.', 1)[-1]:16} needs: {needs}")
        for module, error in import_errors.items():
            print(f"(module {module}: {error})")
        return 0
    if args.workdir is None:
        parser.error("WORKDIR is required (except with --list)")

    workdir_path: Path = args.workdir
    if args.bugreport:
        if not zipfile.is_zipfile(args.bugreport):
            parser.error(f"{args.bugreport} is not a zip file")
        workdir_path.mkdir(parents=True, exist_ok=True)
        link_bugreport(workdir_path, args.bugreport)
    if not workdir_path.is_dir():
        parser.error(f"{workdir_path} is not a directory")
    workdir = Workdir(workdir_path)
    if workdir.bugreport is None and not workdir.live_dir.is_dir():
        problems = "; ".join(workdir.problems)
        reason = f" ({problems})" if problems else ""
        print(
            f"{workdir_path}: no live/ dumps and no readable bugreport zip{reason}",
            file=sys.stderr,
        )
        return 2

    only = set(args.only.split(",")) if args.only else None
    doc = run(workdir, only)
    out = args.output or workdir_path / "analysis.json"
    out.write_text(
        json.dumps(doc, indent=1, ensure_ascii=False, default=json_default),
        encoding="utf-8",
    )
    print(summarize(doc, out))
    return 3 if doc["errors"] else 0


def link_bugreport(workdir: Path, zip_path: Path) -> Path:
    """Link ``zip_path`` into ``workdir`` under its own name, or bugreport.zip.

    Workdir finds any ``*.zip`` holding a dumpstate text, so only names that
    do not end in ``.zip`` are replaced.
    """
    name = zip_path.name if zip_path.suffix.lower() == ".zip" else "bugreport.zip"
    link = workdir / name
    if not (link.exists() or link.is_symlink()):
        link.symlink_to(zip_path.resolve())
    return link


if __name__ == "__main__":
    sys.exit(main())
