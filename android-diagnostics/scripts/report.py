#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Write a readable report from analysis.json.

The report opens with a short bottom line for the phone's owner and gets more
precise further down: the drain budget, ranked battery and slowness findings
with evidence, the time windows behind every number, an action list and
follow-up checks. The strongest findings of each list are shown in full, the
rest in one line each. A finding linked through related to a stronger one
(the same fact seen by another analyzer) is listed under it, not numbered
again. --appendix adds the key metrics of every analyzer; analysis.json
keeps everything.

Input is WORKDIR/analysis.json, written by analyze.py; it is created first
when it is missing (or always with --refresh). Output is WORKDIR/report.md
(or report.json with --format json-summary); the path is printed.

--redact replaces MAC addresses, IP addresses, network names, serial-like
numbers, e-mail addresses and phone numbers with stable placeholders such as
<ip:3f2a> before anything is written. Use it for every report that leaves the
owner's computer; the analysis.json and the dumps themselves stay unredacted.

Exit codes:
  0  report written
  2  usage error, or no analysis could be read or produced
"""

from __future__ import annotations

import argparse
import json
import operator
import re
import subprocess  # ruff: ignore[suspicious-subprocess-import] - runs analyze.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from androiddiag.budget import (
    first_sentence,
    fmt_span,
    owner_map,
    rank_key,
    strength,
    window_label,
)
from androiddiag.model import SEVERITY_RANK, WINDOWS
from androiddiag.redact import Redactor

if sys.version_info < (3, 11):  # ruff: ignore[outdated-version-block] - message for users of old Python
    sys.exit("report.py needs Python 3.11 or newer")

SCRIPTS = Path(__file__).resolve().parent
# Entries per list: findings, actions, follow-ups, facts. Lower-ranked ones
# stay in analysis.json, which keeps a full capture's report near 35 KB.
DEFAULT_MAX_ROWS = 12
# Findings per list shown in full (summary, evidence, advice); the rest of the
# list gets one line each.
DEFAULT_DETAIL = 6
# A one-line entry quotes the first sentence of the summary up to this length.
BRIEF_CHARS = 160
# analyze.py exits 3 when an analyzer failed but analysis.json was written.
ANALYZE_OK_CODES = (0, 3)
# Evidence lines shown per finding, and the longest excerpt quoted.
MAX_EVIDENCE = 2
MAX_EXCERPT = 120
OWN_PREFIXES = ("bottom_line.", "drain_budget.")
ACTION_SEVERITIES = ("high", "medium", "low")
BASIS_TEXT = {
    "measured": "measured",
    "modelled": "modelled (power-model estimate)",
    "inferred": "inferred",
}
HOW_TO_READ = (
    "**How to read this report.** *Severity* says how much a finding matters "
    "(high, medium, low, info). *Basis* says how it is known: **measured** "
    "values were counted by the phone's battery gauge, kernel or system "
    "counters; **modelled** values are Android's own power estimate (the one "
    "behind Settings > Battery usage); **inferred** means a likely explanation "
    "that the data does not show directly. *Window* is the stretch of time a "
    "number covers; the section 'Windows and data coverage' explains each one."
)
ACTION_ORDER_NOTE = (
    "Ordered by the strongest finding behind each action (severity, then "
    "measured before modelled before inferred); the finding numbers refer to "
    "the battery and slowness lists above."
)
APPENDIX_HINT = (
    "The metrics, tables and notes of every analyzer are in analysis.json; "
    "`report.py --appendix` adds their key metrics to this report."
)
NON_ADDITIVE = (
    "These rows overlap: a trigger starts a wake, a multiplier stretches each "
    "wake, a consequence is the cost of the wakes. Their shares have different "
    "denominators and must not be added up."
)


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def run_analyze(workdir: Path, out: Path) -> None:
    """Run analyze.py on ``workdir``, writing ``out``; exit on failure."""
    cmd = [
        sys.executable,
        str(SCRIPTS / "analyze.py"),
        str(workdir),
        "--output",
        str(out),
    ]
    print(f"running analyze.py on {workdir} ...", file=sys.stderr)
    proc = subprocess.run(cmd, check=False)  # ruff: ignore[subprocess-without-shell-equals-true] - argv list
    if proc.returncode not in ANALYZE_OK_CODES or not out.exists():
        sys.exit(f"analyze.py failed with exit code {proc.returncode}")


def load_analysis(workdir: Path | None, analysis: Path | None, refresh: bool) -> dict:
    """Return the analysis document, running analyze.py first when needed."""
    path = analysis or (workdir / "analysis.json" if workdir else None)
    if path is None:
        sys.exit("give WORKDIR or --analysis FILE")
    if refresh or not path.exists():
        if workdir is None:
            sys.exit(f"{path} not found; give WORKDIR so analyze.py can create it")
        run_analyze(workdir, path)
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Building the report structure (shared by both output formats)
# --------------------------------------------------------------------------


def is_own(finding: dict) -> bool:
    """Return whether a finding comes from the budget analyzers themselves."""
    return str(finding.get("id", "")).startswith(OWN_PREFIXES)


def ranked(findings: list[dict], symptom: str) -> list[dict]:
    """Return non-info findings for ``symptom`` (or both), most important first."""
    chosen = [
        f
        for f in findings
        if f.get("symptom") in {symptom, "both"} and f.get("severity") != "info"
    ]
    return sorted(
        chosen,
        key=lambda f: rank_key(f["id"], f["severity"], f["basis"], symptom),
    )


def own_finding(doc: dict, finding_id: str) -> dict | None:
    """Return a bottom_line or drain_budget finding by id."""
    analyzer = finding_id.split(".", 1)[0]
    result = doc.get("results", {}).get(analyzer, {})
    return next(
        (f for f in result.get("findings", []) if f.get("id") == finding_id),
        None,
    )


def related_groups(findings: list[dict]) -> dict[str, list[dict]]:
    """Return ``{owner id: member findings}`` from the findings' ``related`` ids.

    A member states the same fact as its owner (another analyzer's view, or
    a finding the owner subsumes), so it is listed under the owner.
    """
    owners = owner_map(
        [
            (f["id"], strength(f["severity"], f["basis"], f["window"]), f["related"])
            for f in findings
        ],
    )
    groups: dict[str, list[dict]] = {}
    for f in findings:
        if f["id"] in owners:
            groups.setdefault(owners[f["id"]], []).append(f)
    for members in groups.values():
        members.sort(key=lambda f: strength(f["severity"], f["basis"], f["window"]))
    return groups


def actions(findings: list[dict]) -> list[dict]:
    """Deduplicate recommendations, ordered by severity, then basis."""
    grouped: dict[str, dict] = {}
    for f in findings:
        text = " ".join(str(f.get("recommendation", "")).split())
        if not text or f.get("severity") not in ACTION_SEVERITIES:
            continue
        key = text.casefold()
        entry = grouped.setdefault(
            key,
            {"text": text, "finding_ids": [], "rank": None},
        )
        entry["finding_ids"].append(f["id"])
        rank = rank_key(f["id"], f["severity"], f["basis"], f.get("symptom", ""))
        if entry["rank"] is None or rank < entry["rank"]:
            entry.update(rank=rank, severity=f["severity"], basis=f["basis"])
    ordered = sorted(grouped.values(), key=operator.itemgetter("rank"))
    for entry in ordered:
        del entry["rank"]
    return ordered


def followups(findings: list[dict], extra: list[str]) -> list[dict]:
    """Deduplicate follow-up checks in finding order, then ``extra``."""
    seen: dict[str, dict] = {}
    for f in findings:
        for text in f.get("followups", []):
            key = " ".join(str(text).split()).casefold()
            if key not in seen:
                seen[key] = {"text": text, "finding_id": f["id"]}
    for text in extra:
        seen.setdefault(text.casefold(), {"text": text, "finding_id": None})
    return list(seen.values())


def coverage(doc: dict) -> dict:
    """Summarise analyzer status, windows and caveats."""
    results = doc.get("results", {})
    status = {name: r.get("status") for name, r in results.items()}
    windows_notes = results.get("windows", {}).get("notes", [])
    gaps = own_finding(doc, "bottom_line.not_determined")
    return {
        "analyzers_ok": sum(s == "ok" for s in status.values()),
        "skipped": {
            n: results[n].get("reason", "") for n, s in status.items() if s == "skipped"
        },
        "failed": {
            n: results[n].get("reason", "") for n, s in status.items() if s == "error"
        },
        "errors": doc.get("errors", {}),
        "windows": doc.get("windows", {}),
        "windows_used": sorted({f.get("window", "") for f in doc.get("findings", [])}),
        "caveats": gaps["summary"].splitlines() if gaps else list(windows_notes),
        "sources": sorted(doc.get("sources", {})),
    }


def build(doc: dict) -> dict:
    """Turn an analysis document into the report structure."""
    every: list[dict] = [
        {**f, "related": list(f.get("related") or ())}
        for f in doc.get("findings", [])
        if not is_own(f)
    ]
    related = related_groups(every)
    members = {f["id"] for group in related.values() for f in group}
    findings = [f for f in every if f["id"] not in members]
    ranked_all = sorted(
        (f for f in findings if f.get("severity") != "info"),
        key=lambda f: rank_key(f["id"], f["severity"], f["basis"], f["symptom"]),
    )
    gaps = own_finding(doc, "bottom_line.not_determined")
    return {
        "device": doc.get("device", {}),
        "related": related,
        "bottom_line": {
            key: own_finding(doc, f"bottom_line.{key}")
            for key in ("battery", "slowness", "not_determined")
        },
        "budget": doc.get("results", {}).get("drain_budget"),
        "budget_findings": [
            own_finding(doc, f"drain_budget.{key}")
            for key in ("where_it_went", "wake_chain", "capacity_effect")
        ],
        "battery": ranked(findings, "battery"),
        "slowness": ranked(findings, "slowness"),
        "facts": sorted(
            (f for f in findings if f.get("severity") == "info"),
            key=operator.itemgetter("id"),
        ),
        "actions": actions(ranked_all),
        "followups": followups(ranked_all, gaps.get("followups", []) if gaps else []),
        "coverage": coverage(doc),
        "results": {
            name: {
                "status": r.get("status"),
                "reason": r.get("reason", ""),
                "window": r.get("window", ""),
                "metrics": r.get("metrics", {}),
                "notes": r.get("notes", []),
                "table_rows": {t: len(rows) for t, rows in r.get("tables", {}).items()},
            }
            for name, r in doc.get("results", {}).items()
        },
    }


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------


def cell(value: object) -> str:
    """Format a value for a Markdown table cell."""
    if value is None:
        text = "-"
    elif isinstance(value, float):
        text = f"{value:,.3f}".rstrip("0").rstrip(".")
    elif isinstance(value, list | dict):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def table(
    rows: list[dict], columns: list[str], headers: list[str] | None = None
) -> list[str]:
    """Return Markdown table lines for ``rows`` restricted to ``columns``."""
    head = headers or columns
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join(cell(r.get(c)) for c in columns) + " |" for r in rows]
    return lines


def code(text: str) -> str:
    """Return ``text`` as an inline code span (backticks replaced)."""
    return "`" + str(text).replace("`", "'") + "`"


def labels(f: dict) -> str:
    """Return the severity, basis and window line of a finding."""
    basis = BASIS_TEXT.get(f.get("basis", ""), f.get("basis"))
    window = window_label(f.get("window", ""))
    return (
        f"*Severity {f.get('severity', '?')}; basis {basis}; window {window}.* "
        f"{code(f['id'])}"
    )


def short_labels(f: dict) -> str:
    """Return ``*(high, measured, since boot)*`` and the id of a finding."""
    window = window_label(f.get("window", ""))
    return f"*({f.get('severity', '?')}, {f.get('basis')}, {window})* {code(f['id'])}"


def related_lines(f: dict, related: dict[str, list[dict]]) -> list[str]:
    """Render the findings folded into ``f`` as one line each."""
    return [
        f"- Also reported: **{m.get('title', m['id'])}**: "
        f"{first_sentence(m.get('summary', ''), BRIEF_CHARS)} {short_labels(m)}"
        for m in related.get(f["id"], [])
    ]


def evidence_lines(f: dict) -> list[str]:
    """Render the first evidence citations of a finding."""
    evidence = f.get("evidence", [])[:MAX_EVIDENCE]
    lines = []
    for e in evidence:
        excerpt = " ".join(str(e.get("excerpt", "")).split())
        if len(excerpt) > MAX_EXCERPT:
            excerpt = excerpt[:MAX_EXCERPT] + " ..."
        lines.append(
            f"- Evidence: {code(e.get('ref', ''))}"
            + (f" {code(excerpt)}" if excerpt else ""),
        )
    more = len(f.get("evidence", [])) - len(evidence)
    if more > 0:
        lines.append(f"- Evidence: {more} more in analysis.json")
    return lines


def finding_block(n: int, f: dict, related: dict[str, list[dict]]) -> list[str]:
    """Render one finding with labels, summary, evidence and recommendation."""
    lines = [
        f"#### {n}. {f.get('title', f['id'])}",
        "",
        labels(f),
        "",
        f.get("summary", ""),
    ]
    detail = evidence_lines(f) + related_lines(f, related)
    if detail:
        lines += ["", *detail]
    if f.get("recommendation"):
        lines += ["", f"**What to do:** {f['recommendation']}"]
    return [*lines, ""]


def finding_line(n: int, f: dict, related: dict[str, list[dict]]) -> str:
    """Render one finding in a single line: title, first sentence, labels."""
    also = [code(m["id"]) for m in related.get(f["id"], [])]
    return (
        f"{n}. **{f.get('title', f['id'])}**: "
        f"{first_sentence(f.get('summary', ''), BRIEF_CHARS)} "
        f"{short_labels(f)}" + (f"; also reported as {', '.join(also)}" if also else "")
    )


def finding_list(
    items: list[dict],
    related: dict[str, list[dict]],
    *,
    max_rows: int,
    detail: int,
    skip: dict[str, str],
) -> list[str]:
    """Render ranked findings: the first ``detail`` in full, the rest in a line.

    Ids in ``skip`` are shown in another list and get a pointer instead.
    """
    if not items:
        return ["No findings in this group.", ""]
    lines: list[str] = []
    brief: list[str] = []
    shown = 0
    for n, f in enumerate(items[:max_rows], 1):
        title = f.get("title", f["id"])
        if brief or shown >= detail:
            pointer = skip.get(f["id"])
            brief.append(
                f"{n}. **{title}**: see {pointer}."
                if pointer
                else finding_line(n, f, related),
            )
        elif f["id"] in skip:
            lines += [f"#### {n}. {title}", "", f"See {skip[f['id']]}.", ""]
        else:
            lines += finding_block(n, f, related)
            shown += 1
    if brief:
        lines += [*brief, ""]
    if len(items) > max_rows:
        lines += [
            f"{len(items) - max_rows} lower-ranked findings are in analysis.json.",
            "",
        ]
    return lines


def summary_lines(finding: dict | None) -> list[str]:
    """Render a multi-line bottom-line summary as Markdown."""
    if not finding:
        return ["Not available: the bottom_line analyzer did not run.", ""]
    lines = [
        line if line[:1].isdigit() else f"{line}\n"
        for line in finding.get("summary", "").splitlines()
    ]
    return [*lines, ""]


def bottom_line_section(report: dict) -> list[str]:
    """Render the plain-language top of the report."""
    bl = report["bottom_line"]
    lines = ["## Bottom line", "", "### Battery", ""]
    lines += summary_lines(bl["battery"])
    lines += ["### Slowness", ""]
    lines += summary_lines(bl["slowness"])
    lines += ["### What could not be determined", ""]
    gaps = bl["not_determined"]
    if gaps:
        lines += [f"- {line}" for line in gaps.get("summary", "").splitlines()]
    else:
        lines.append("- Not available: the bottom_line analyzer did not run.")
    return [*lines, "", HOW_TO_READ, ""]


def budget_section(report: dict) -> list[str]:
    """Render the drain budget: where the charge went and what keeps it awake.

    Its tables are shown whole; the analyzer caps them.
    """
    budget = report.get("budget") or {}
    if budget.get("status") != "ok":
        reason = budget.get("reason", "the drain_budget analyzer did not run")
        return [f"No drain budget: {reason}.", ""]
    tables = budget.get("tables", {})
    where, chain, capacity = report["budget_findings"]
    lines = ["### Where the charge went", ""]
    if where:
        lines += [where["summary"], ""]
    if tables.get("discharge"):
        lines += table(
            tables["discharge"],
            ["part", "hours", "mah", "mah_per_h", "pct_of_discharge", "basis"],
            ["Part", "Hours", "mAh", "mAh/h", "% of discharge", "Basis"],
        )
        lines.append("")
    lines += ["### What keeps the phone awake with the screen off", ""]
    if chain:
        lines += [chain["summary"], ""]
    if tables.get("wake_chain"):
        rows = [
            {**row, "window": window_label(str(row.get("window", "")))}
            for row in tables["wake_chain"]
        ]
        lines += table(
            rows,
            ["layer", "item", "value", "unit", "window", "basis"],
            ["Layer", "Item", "Value", "Unit", "Window", "Basis"],
        )
        lines += ["", NON_ADDITIVE, ""]
    if capacity:
        lines += ["### Battery wear and runtime", "", capacity["summary"], ""]
    return lines


def stamp(value: object) -> str | None:
    """Return a device timestamp without fractions of a second."""
    return None if value is None else str(value)[:19]


def duration(seconds: object) -> str | None:
    """Return seconds as ``5h02m``, or None when unknown."""
    return fmt_span(float(seconds)) if isinstance(seconds, int | float) else None


def windows_section(report: dict) -> list[str]:
    """Render what each window means and the capture caveats."""
    cov = report["coverage"]
    w = cov["windows"]
    on_battery = w.get("on_battery_at_capture")
    anchors = [
        ("Capture time", stamp(w.get("dump_time"))),
        ("Last boot", stamp(w.get("boot_time"))),
        ("Last full charge (unplugged)", stamp(w.get("since_charge_start"))),
        ("Time on battery since then", duration(w.get("on_battery_s"))),
        ("of which screen off", duration(w.get("screen_off_on_battery_s"))),
        ("Plugged in at", stamp(w.get("plugged_at"))),
        ("On battery at capture", {True: "yes", False: "no"}.get(on_battery)),
        ("UTC offset", w.get("utc_offset")),
    ]
    lines = ["## Windows and data coverage", ""]
    lines += table(
        [{"anchor": a, "value": v} for a, v in anchors],
        ["anchor", "value"],
        ["Time anchor", "Value"],
    )
    lines += ["", "Each number in this report covers one of these windows:", ""]
    lines += [
        f"- **{window_label(key)}** ({code(key)}): "
        + WINDOWS.get(key, "see the analyzer notes")
        for key in cov["windows_used"]
        if key
    ]
    if report["bottom_line"]["not_determined"] is None:
        # Otherwise the caveats are listed under 'What could not be determined'.
        lines += ["", "### Capture caveats", ""]
        lines += [f"- {c}" for c in cov["caveats"]] or ["- None recorded."]
    lines += ["", "### Analyzers", "", f"{cov['analyzers_ok']} analyzers ran."]
    for label, entries in (("Skipped", cov["skipped"]), ("Failed", cov["failed"])):
        if entries:
            lines += ["", f"{label}:", ""]
            lines += [f"- {code(n)}: {reason}" for n, reason in sorted(entries.items())]
    if cov["errors"]:
        lines += ["", "Errors (details in analysis.json):", ""]
        lines += [f"- {code(n)}" for n in sorted(cov["errors"])]
    lines += [
        "",
        f"{len(cov['sources'])} inputs were found: " + ", ".join(cov["sources"]) + ".",
        "",
    ]
    return lines


def finding_refs(finding_ids: list[str], refs: dict[str, tuple[str, int]]) -> str:
    """Return ``battery 1, 4; slowness 2`` for findings numbered in the lists.

    Findings outside the lists are named by id.
    """
    numbers: dict[str, list[str]] = {}
    for fid in dict.fromkeys(finding_ids):
        label, n = refs.get(fid, (code(fid), 0))
        numbers.setdefault(label, []).append(str(n) if n else "")
    return "; ".join(
        f"{label} {', '.join(ns)}" if any(ns) else label
        for label, ns in numbers.items()
    )


def action_section(
    report: dict,
    max_rows: int,
    refs: dict[str, tuple[str, int]],
) -> list[str]:
    """Render the deduplicated action list; ``refs`` numbers the listed findings."""
    items = report["actions"]
    lines = ["## Action list", ""]
    if not items:
        return [*lines, "No actions: no finding above info severity.", ""]
    lines += [ACTION_ORDER_NOTE, ""]
    for n, a in enumerate(items[:max_rows], 1):
        sources = finding_refs(a["finding_ids"], refs)
        lines.append(
            f"{n}. {a['text']} *({a['severity']}, {a['basis']}; for {sources})*"
        )
    if len(items) > max_rows:
        lines.append(
            f"\n{len(items) - max_rows} more actions are in analysis.json, in the "
            "findings' recommendations."
        )
    return [*lines, ""]


def followup_section(report: dict, max_rows: int) -> list[str]:
    """Render follow-up checks that would confirm or refine the findings."""
    items = report["followups"]
    lines = ["## Follow-ups", ""]
    if not items:
        return [*lines, "None.", ""]
    for item in items[:max_rows]:
        source = f" ({code(item['finding_id'])})" if item["finding_id"] else ""
        lines.append(f"- {item['text']}{source}")
    if len(items) > max_rows:
        lines.append(f"- ... and {len(items) - max_rows} more in analysis.json")
    return [*lines, ""]


def appendix_section(report: dict, max_rows: int) -> list[str]:
    """Render the key metrics of every analyzer, capped at ``max_rows``."""
    lines = ["## Appendix: key metrics per analyzer", "", APPENDIX_HINT, ""]
    for name in sorted(report["results"]):
        r = report["results"][name]
        if r.get("status") != "ok":
            lines += [
                f"### {name}",
                "",
                f"*{r.get('status')}*: {r.get('reason', '')}",
                "",
            ]
            continue
        window = r.get("window")
        lines += [f"### {name}" + (f" ({window_label(window)})" if window else ""), ""]
        metrics = list(r.get("metrics", {}).items())
        if metrics:
            lines += table(
                [{"metric": k, "value": v} for k, v in metrics[:max_rows]],
                ["metric", "value"],
                ["Metric", "Value"],
            )
        if len(metrics) > max_rows:
            lines.append(
                f"\n{len(metrics) - max_rows} more metrics are in analysis.json."
            )
        tables = r.get("table_rows", {})
        if tables:
            listed = ", ".join(f"{t} ({n} rows)" for t, n in tables.items())
            lines.append(f"\nTables in analysis.json: {listed}.")
        lines += [f"- Note: {note}" for note in r.get("notes", [])[:max_rows]]
        lines.append("")
    return lines


def header_lines(report: dict) -> list[str]:
    """Render the title and the device line."""
    device = report["device"]
    parts = [
        f"build {device['build']}" if device.get("build") else "",
        f"Android SDK {device['android_sdk_version']}"
        if device.get("android_sdk_version")
        else "",
        f"captured {device['dumpstate_time']}" if device.get("dumpstate_time") else "",
    ]
    line = ", ".join(p for p in parts if p) or "device details not recorded"
    return ["# Phone battery and performance report", "", f"Device: {line}.", ""]


_CODE_SPAN_RE = re.compile(r"(`[^`\n]*`)")


def escape_prose(markdown: str) -> str:
    """Escape ``<`` outside code spans so that ``<app>`` or ``<ip:3f2a>`` stay text.

    Markdown renderers would otherwise drop them as HTML tags or turn them
    into links.
    """
    lines = []
    for line in markdown.splitlines():
        parts = _CODE_SPAN_RE.split(line)
        lines.append(
            "".join(p if p.startswith("`") else p.replace("<", "\\<") for p in parts),
        )
    return "\n".join(lines) + "\n"


def facts_section(report: dict, max_rows: int) -> list[str]:
    """Render info findings by title; their summaries are in analysis.json."""
    facts = report["facts"]
    if not facts:
        return []
    lines = ["## Other facts", ""]
    lines += [
        f"- **{f.get('title', f['id'])}** {short_labels(f)}" for f in facts[:max_rows]
    ]
    if len(facts) > max_rows:
        lines.append(f"- ... and {len(facts) - max_rows} more in analysis.json")
    return [*lines, ""]


def render_markdown(
    report: dict,
    max_rows: int,
    *,
    detail: int = DEFAULT_DETAIL,
    appendix: bool = False,
) -> str:
    """Return the Markdown report; ``appendix`` adds every analyzer's metrics."""
    refs: dict[str, tuple[str, int]] = {}
    for symptom in ("battery", "slowness"):
        for n, f in enumerate(report[symptom][:max_rows], 1):
            refs.setdefault(f["id"], (symptom, n))
    pointers = {
        fid: f"battery finding {n} above"
        for fid, (symptom, n) in refs.items()
        if symptom == "battery"
    }
    related = report["related"]
    lines = header_lines(report) + bottom_line_section(report)
    lines += ["## Battery drain", ""]
    lines += budget_section(report)
    lines += ["### Battery findings, most important first", ""]
    lines += finding_list(
        report["battery"], related, max_rows=max_rows, detail=detail, skip={}
    )
    lines += ["## Slowness", "", "### Slowness findings, most important first", ""]
    lines += finding_list(
        report["slowness"], related, max_rows=max_rows, detail=detail, skip=pointers
    )
    lines += facts_section(report, max_rows)
    lines += windows_section(report)
    lines += action_section(report, max_rows, refs)
    lines += followup_section(report, max_rows)
    lines += appendix_section(report, max_rows) if appendix else [APPENDIX_HINT]
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------
# JSON summary
# --------------------------------------------------------------------------

SUMMARY_FIELDS = ("id", "title", "symptom", "severity", "basis", "window", "summary")


def render_json_summary(report: dict, max_rows: int) -> dict:
    """Return a compact machine-readable summary of the report."""
    bl = report["bottom_line"]
    budget = report.get("budget") or {}
    findings = sorted(
        {f["id"]: f for f in report["battery"] + report["slowness"]}.values(),
        key=lambda f: (SEVERITY_RANK.get(f["severity"], 9), f["id"]),
    )
    return {
        "schema": 1,
        "device": report["device"],
        "bottom_line": {
            key: value["summary"].splitlines() if value else []
            for key, value in bl.items()
        },
        "budget": budget.get("metrics", {}),
        "findings": [
            {
                **{k: f.get(k) for k in SUMMARY_FIELDS},
                "recommendation": f.get("recommendation", ""),
                "related": [m["id"] for m in report["related"].get(f["id"], [])],
            }
            for f in findings[:max_rows]
        ],
        "findings_total": len(findings),
        "actions": [
            {k: a[k] for k in ("text", "severity", "basis", "finding_ids")}
            for a in report["actions"][:max_rows]
        ],
        "followups": [f["text"] for f in report["followups"][:max_rows]],
        "coverage": {
            k: report["coverage"][k]
            for k in ("analyzers_ok", "skipped", "failed", "windows", "caveats")
        },
    }


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "workdir", nargs="?", type=Path, help="directory from collect.py"
    )
    parser.add_argument("--analysis", type=Path, help="read this analysis.json instead")
    parser.add_argument("--output", type=Path, help="write the report here")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="run analyze.py again even if analysis.json exists",
    )
    parser.add_argument(
        "--redact",
        action="store_true",
        help="replace addresses, network names, serials, e-mails and phone numbers",
    )
    parser.add_argument(
        "--redact-salt",
        default="",
        help="mix this text into the placeholder hashes (default: none)",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "json-summary"),
        default="markdown",
        help="output format (default: markdown)",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=DEFAULT_MAX_ROWS,
        help=(
            "entries per list of findings, actions, follow-ups and facts, and "
            f"metrics per analyzer in the appendix (default: {DEFAULT_MAX_ROWS})"
        ),
    )
    parser.add_argument(
        "--detail",
        type=int,
        default=DEFAULT_DETAIL,
        help=(
            "findings per list shown in full; the rest get one line each "
            f"(default: {DEFAULT_DETAIL})"
        ),
    )
    parser.add_argument(
        "--appendix",
        action="store_true",
        help="add the key metrics of every analyzer (Markdown only)",
    )
    args = parser.parse_args(argv)
    if args.workdir is None and args.analysis is None:
        parser.error("give WORKDIR or --analysis FILE")
    if args.max_rows < 1:
        parser.error("--max-rows must be at least 1")
    if args.detail < 0:
        parser.error("--detail must not be negative")
    return args


def main(argv: list[str] | None = None) -> int:
    """Load or create the analysis, render the report and write it."""
    args = parse_args(argv)
    doc = load_analysis(args.workdir, args.analysis, args.refresh)
    report = build(doc)
    redactor = Redactor(args.redact_salt) if args.redact else None
    if redactor:
        # Learn names from the string values of the whole analysis, not from
        # its JSON text, whose escaped quotes hide 'SSID: "name"' contexts.
        redactor.learn_obj(doc)
        redacted = redactor.redact_obj(report)
        report = redacted if isinstance(redacted, dict) else report
    if args.format == "markdown":
        markdown = render_markdown(
            report,
            args.max_rows,
            detail=args.detail,
            appendix=args.appendix,
        )
        text = escape_prose(markdown)
        suffix = ".md"
    else:
        summary = render_json_summary(report, args.max_rows)
        text = json.dumps(summary, indent=1, ensure_ascii=False) + "\n"
        suffix = ".json"
    base = args.workdir or args.analysis.parent
    out = args.output or base / f"report{suffix}"
    out.write_text(text, encoding="utf-8")
    print(f"report: {out}")
    if redactor and redactor.counts:
        counts = ", ".join(f"{n} {kind}" for kind, n in sorted(redactor.counts.items()))
        print(f"redacted: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
