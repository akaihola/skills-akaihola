"""Tests for scripts/report.py: Markdown and JSON reports from analysis.json.

The analysis documents are built from invented results; the budget analyzers
run on them so the report sees the same structure analyze.py writes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from textwrap import dedent

import pytest
import report
from androiddiag import budget
from androiddiag.model import SEVERITY_RANK, Evidence, Finding, Result, Windows
from conftest import SCRIPTS

WINDOWS = Windows(
    dump_time=datetime(2026, 1, 15, 12, 0),
    boot_time=datetime(2026, 1, 15, 6, 0, 0, 250000),
    since_charge_start=datetime(2026, 1, 15, 8, 0),
    on_battery_at_capture=False,
    on_battery_s=4 * 3600.0,
    screen_off_on_battery_s=3 * 3600.0,
    plugged_at=datetime(2026, 1, 15, 11, 58, 0, 500000),
)
SHARED_ADVICE = "Restrict the background app in Settings > Apps."


def finding(fid, severity, basis="measured", symptom="battery", **extra):
    return Finding(
        id=fid,
        title=extra.pop("title", f"Title {fid}"),
        symptom=symptom,
        severity=severity,
        basis=basis,
        window=extra.pop("window", "on_battery"),
        summary=extra.pop("summary", f"Summary of {fid}. More detail."),
        evidence=extra.pop("evidence", [Evidence("live/x.txt:3", "line three")]),
        recommendation=extra.pop("recommendation", f"Advice for {fid}."),
        followups=extra.pop("followups", [f"Follow up {fid}."]),
        related=extra.pop("related", []),
    )


def make_results():
    return {
        "windows": Result("windows", window="snapshot", notes=["Charging at capture."]),
        "discharge_accounting": Result(
            "discharge_accounting",
            window="on_battery",
            metrics={
                "on_battery_s": 14400.0,
                "screen_off_s": 10800.0,
                "screen_on_s": 3600.0,
                "discharge_mah": 300.0,
                "screen_on_mah": 120.0,
                "screen_off_mah": 180.0,
                "gauge_step_mah": 25.0,
            },
            findings=[
                finding(
                    "discharge_accounting.standby_drain",
                    "high",
                    recommendation=SHARED_ADVICE,
                ),
            ],
        ),
        "standby_wake": Result(
            "standby_wake",
            window="screen_off_on_battery",
            metrics={"awake_share_pct": 55.0, "resumes_per_h": 900.0},
            findings=[
                finding(
                    "standby_wake.awake_share",
                    "medium",
                    window="screen_off_on_battery",
                    summary=(
                        "A peer at 192.0.2.44 (02:00:00:00:00:44) woke the phone, "
                        "reported by owner@example.com. More."
                    ),
                    evidence=[Evidence("bugreport:KERNEL LOG:9", "src 192.0.2.44")],
                ),
            ],
        ),
        "wake_periodicity": Result(
            "wake_periodicity",
            findings=[
                finding(
                    "wake_periodicity.periodic_sender",
                    "medium",
                    basis="inferred",
                    recommendation=SHARED_ADVICE,
                ),
            ],
        ),
        "vmstat_reclaim_io": Result(
            "vmstat_reclaim_io",
            window="since_boot",
            metrics={f"metric_{i}": i for i in range(30)},
            findings=[
                finding(
                    "vmstat_reclaim_io.page_cache_thrashing",
                    "medium",
                    symptom="both",
                    window="since_boot",
                ),
            ],
        ),
        "exit_info_audit": Result(
            "exit_info_audit",
            window="since_boot",
            findings=[
                finding("exit_info_audit.low_memory_kills", "high", symptom="slowness"),
                finding("exit_info_audit.note", "info", symptom="info"),
            ],
        ),
        "frame_jank": Result("frame_jank", status="skipped", reason="missing inputs"),
    }


def make_doc(context_factory, results=None):
    ctx = context_factory(windows=WINDOWS)
    ctx.results.update(make_results() if results is None else results)
    for func in (budget.drain_budget, budget.bottom_line):
        ctx.results[func.__name__] = func(ctx)
    findings = sorted(
        (f for r in ctx.results.values() for f in r.findings),
        key=lambda f: (SEVERITY_RANK[f.severity], f.id),
    )
    return {
        "schema": 1,
        "workdir": "example-workdir",
        "device": {
            "build": "TEST.1.0",
            "android_sdk_version": "35",
            "dumpstate_time": "2026-01-15 12:00:00",
        },
        "windows": ctx.windows.to_dict(),
        "sources": ctx.sources.available(),
        "results": {name: r.to_dict() for name, r in ctx.results.items()},
        "findings": [
            {**f.__dict__, "evidence": [e.__dict__ for e in f.evidence]}
            for f in findings
        ],
        "errors": {},
    }


@pytest.fixture
def analysis(context_factory, tmp_path):
    path = tmp_path / "analysis.json"
    path.write_text(json.dumps(make_doc(context_factory), default=str))
    return path


def render(analysis, *extra):
    out = analysis.parent / ("out.json" if "json-summary" in extra else "out.md")
    assert report.main(["--analysis", str(analysis), "--output", str(out), *extra]) == 0
    return out.read_text()


def write_doc(tmp_path, doc):
    path = tmp_path / "analysis.json"
    path.write_text(json.dumps(doc, default=str))
    return path


def test_sections_in_reading_order(analysis):
    text = render(analysis)
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert headings == [
        "## Bottom line",
        "## Battery drain",
        "## Slowness",
        "## Other facts",
        "## Windows and data coverage",
        "## Action list",
        "## Follow-ups",
    ]
    assert text.rstrip().endswith("adds their key metrics to this report.")
    with_appendix = render(analysis, "--appendix")
    assert "\n## Appendix: key metrics per analyzer\n" in with_appendix
    assert "### vmstat_reclaim_io (since boot)" in with_appendix
    assert text.startswith("# Phone battery and performance report\n")
    assert "Device: build TEST.1.0, Android SDK 35, captured 2026-01-15 12:00:00." in (
        text
    )


def test_bottom_line_is_plain_and_labelled(analysis):
    text = render(analysis)
    top = text.split("\n## Battery drain\n")[0]
    assert "general knowledge, not measured on this phone" in top
    assert "1. Title discharge_accounting.standby_drain" in top
    assert "[on battery since the last full charge; measured]" in top
    assert "Analyzer frame_jank skipped: missing inputs." in top
    assert "**How to read this report.**" in top


def test_budget_tables_and_non_additive_note(analysis):
    text = render(analysis)
    assert "### Where the charge went" in text
    assert "| screen off | 3 | 180 | 60 | 60 | measured |" in text
    assert "must not be added up" in text


def test_ranked_findings_with_labels_and_evidence(analysis):
    text = render(analysis)
    battery = text.split("\n## Battery drain\n")[1].split("\n## Slowness\n")[0]
    first = battery.index("Title discharge_accounting.standby_drain")
    assert first < battery.index("Title standby_wake.awake_share")
    assert (
        "*Severity high; basis measured; window on battery since the last full "
        "charge.* `discharge_accounting.standby_drain`"
    ) in battery
    assert "- Evidence: `live/x.txt:3` `line three`" in battery
    assert f"**What to do:** {SHARED_ADVICE}" in battery


def test_both_symptom_is_shown_once(analysis):
    text = render(analysis)
    slowness = text.split("\n## Slowness\n")[1].split("\n## Other facts\n")[0]
    assert "Title vmstat_reclaim_io.page_cache_thrashing" in slowness
    assert "See battery finding 3 above." in slowness
    assert "Summary of vmstat_reclaim_io" not in slowness


def test_windows_section(analysis):
    text = render(analysis)
    section = text.split("\n## Windows and data coverage\n")[1].split(
        "\n## Action list\n"
    )[0]
    assert "| Last boot | 2026-01-15 06:00:00 |" in section
    assert "| Time on battery since then | 4h00m |" in section
    assert "| Plugged in at | 2026-01-15 11:58:00 |" in section
    assert "| On battery at capture | no |" in section
    assert "- **since boot** (`since_boot`): since the last boot" in section
    assert "- `frame_jank`: missing inputs" in section
    # The caveats are listed once, under 'What could not be determined'.
    assert "Capture caveats" not in section
    top = text.split("\n## Battery drain\n")[0]
    assert "external power at capture" in top


def test_action_list_is_deduplicated_and_ordered(analysis):
    text = render(analysis)
    actions = text.split("\n## Action list\n")[1].split("\n## Follow-ups\n")[0]
    items = [line for line in actions.splitlines() if line[:1].isdigit()]
    shared = [line for line in items if SHARED_ADVICE in line]
    assert len(shared) == 1
    assert shared[0].startswith("1. ")
    # The advice of battery findings 1 and 4, by their numbers in the list.
    assert shared[0].endswith("*(high, measured; for battery 1, 4)*")
    assert not any("Advice for exit_info_audit.note" in line for line in items)


def test_redact_hides_addresses(analysis):
    plain = render(analysis)
    assert "192.0.2.44" in plain
    redacted = render(analysis, "--redact")
    for raw in ("192.0.2.44", "02:00:00:00:00:44", "owner@example.com"):
        assert raw not in redacted
    assert "<ip:" in redacted
    assert "<mac:" in redacted
    assert "<email:" in redacted


def test_json_summary(analysis):
    data = json.loads(render(analysis, "--format", "json-summary", "--redact"))
    assert set(data) >= {"bottom_line", "budget", "findings", "actions", "coverage"}
    assert data["bottom_line"]["battery"][1].startswith("1. Title discharge")
    assert data["budget"]["screen_off_mah_per_h"] == pytest.approx(60.0)
    ids = [f["id"] for f in data["findings"]]
    assert ids[0] == "discharge_accounting.standby_drain"
    assert "exit_info_audit.note" not in ids
    assert "192.0.2.44" not in json.dumps(data)
    assert data["coverage"]["skipped"] == {"frame_jank": "missing inputs"}


def test_max_rows_caps_lists(analysis):
    text = render(analysis, "--max-rows", "1", "--appendix")
    assert "lower-ranked findings are in analysis.json" in text
    assert "more metrics are in analysis.json" in text
    assert "more actions are in analysis.json" in text


def test_missing_budget_results_are_reported(context_factory, tmp_path):
    doc = make_doc(context_factory)
    for name in ("bottom_line", "drain_budget"):
        del doc["results"][name]
    doc["findings"] = [
        f for f in doc["findings"] if not f["id"].startswith(report.OWN_PREFIXES)
    ]
    path = tmp_path / "analysis.json"
    path.write_text(json.dumps(doc, default=str))
    text = render(path)
    assert "Not available: the bottom_line analyzer did not run." in text
    assert "No drain budget: the drain_budget analyzer did not run." in text


def test_usage_errors(capsys):
    with pytest.raises(SystemExit) as exc:
        report.main([])
    assert exc.value.code == 2
    assert "give WORKDIR or --analysis FILE" in capsys.readouterr().err


def test_runs_analyze_when_analysis_is_missing(workdir_factory):
    charged = dedent(
        """\
        Statistics since last charge:
          System starts: 2, currently on battery: false
          Start clock time: 2026-01-15-08-00-00
          Time on battery: 4h 0m 0s 0ms (99,1%) realtime, 2h 0m 0s 0ms (50,0%) uptime
          Time on battery screen off: 3h 0m 0s 0ms (75,0%) realtime
          Discharge: 300 mAh
          Screen off discharge: 180 mAh
          Screen on discharge: 120 mAh
        """,
    )
    wd = workdir_factory(live={"batterystats_charged": charged})
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "report.py"), str(wd)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert (wd / "analysis.json").exists()
    assert f"report: {wd / 'report.md'}" in proc.stdout
    text = (wd / "report.md").read_text()
    assert "| Time on battery since then | 4h00m |" in text
    assert "| of which screen off | 3h00m |" in text


def test_angle_brackets_are_escaped_outside_code(analysis):
    text = render(analysis, "--redact")
    assert "`bugreport:KERNEL LOG:9` `src <ip:" in text  # code span stays literal
    assert "A peer at \\<ip:" in text  # prose is escaped for Markdown
    assert report.escape_prose("Settings > Apps > <app> `a <b>`\n") == (
        "Settings > Apps > \\<app> `a <b>`\n"
    )


def related_results():
    results = make_results()
    results["wakelocks"] = Result(
        "wakelocks",
        window="since_boot",
        findings=[
            finding(
                "wakelocks.lockout_since_boot",
                "medium",
                window="since_boot",
                summary="A lock was held 3h since boot. More.",
                recommendation="Advice only the duplicate gives.",
            ),
        ],
    )
    results["discharge_accounting"].findings[0].related = [
        "wakelocks.lockout_since_boot",
        "gone.not_emitted",
    ]
    return results


def test_related_findings_are_listed_under_their_owner(context_factory, tmp_path):
    path = write_doc(tmp_path, make_doc(context_factory, related_results()))
    text = render(path)
    battery = text.split("\n### Battery findings")[1].split("\n## Slowness\n")[0]
    owner = battery.split("#### 1. ")[1].split("#### 2. ")[0]
    assert owner.startswith("Title discharge_accounting.standby_drain")
    assert (
        "- Also reported: **Title wakelocks.lockout_since_boot**: A lock was held "
        "3h since boot. *(medium, measured, since boot)* "
        "`wakelocks.lockout_since_boot`"
    ) in owner
    assert "gone.not_emitted" not in text
    numbered = [line for line in battery.splitlines() if line.startswith("#### ")]
    assert not any("wakelocks.lockout_since_boot" in line for line in numbered)
    assert "Advice only the duplicate gives." not in text
    data = json.loads(render(path, "--format", "json-summary"))
    ids = [f["id"] for f in data["findings"]]
    assert "wakelocks.lockout_since_boot" not in ids
    owner_entry = data["findings"][ids.index("discharge_accounting.standby_drain")]
    assert owner_entry["related"] == ["wakelocks.lockout_since_boot"]


def test_a_weaker_finding_that_points_at_a_stronger_one_goes_under_it(
    context_factory,
    tmp_path,
):
    results = make_results()
    results["wake_periodicity"].findings[0].related = ["standby_wake.awake_share"]
    path = write_doc(tmp_path, make_doc(context_factory, results))
    battery = render(path).split("\n### Battery findings")[1]
    owner = battery.split("Title standby_wake.awake_share")[1].split("#### ")[0]
    assert "- Also reported: **Title wake_periodicity.periodic_sender**" in owner


def test_detail_shows_the_rest_in_one_line_each(analysis):
    text = render(analysis, "--detail", "1")
    battery = text.split("\n### Battery findings")[1].split("\n## Slowness\n")[0]
    assert battery.count("\n#### ") == 1
    assert (
        "\n2. **Title standby_wake.awake_share**: A peer at 192.0.2.44 "
        "(02:00:00:00:00:44) woke the phone, reported by owner@example.com. "
        "*(medium, measured, screen off on battery)* `standby_wake.awake_share`"
    ) in battery
    assert render(analysis, "--detail", "0").count("**What to do:**") == 0


def test_redact_learns_names_from_the_whole_analysis(context_factory, tmp_path):
    """Network names quoted only in unrendered parts are still learned (F5)."""
    doc = make_doc(context_factory)
    doc["results"]["wifi_roaming"] = {
        "status": "ok",
        "tables": {"aps": [{"line": 'SSID: "Example Home" rssi=-61'}]},
    }
    doc["findings"][0]["summary"] = "The phone roamed away from Example Home 9 times."
    path = write_doc(tmp_path, doc)
    assert "Example Home" in render(path)
    redacted = render(path, "--redact")
    assert "Example Home" not in redacted
    assert "roamed away from \\<ssid:" in redacted
