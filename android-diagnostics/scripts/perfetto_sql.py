#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["perfetto>=0.58,<0.60"]
# ///
"""Cross-check a bugreport's battery history with Perfetto's trace processor.

This is optional. analyze.py does not need it: Perfetto's importer does not
read the wake-reason events ("wr") of the battery history, nor the aggregate
checkin rows (9,0,l,...) that hold the discharge totals, so the main pipeline
parses the checkin format itself. Perfetto is an independent, maintained
parser for the rest of the history and a quick way to check those numbers.

Canned queries (each runs on its own; times are UTC unless --utc-offset):
  standby      screen-off time, awake share and resumes while unplugged
  deep_idle    Doze states (off, light, deep) during screen-off time unplugged
  battery      battery level (%), charge counter (mAh) and plug type samples
  screen       screen on and off intervals

--sql FILE runs your own query; the file may hold INCLUDE and CREATE
statements, but only the last statement may be a SELECT. Results print as CSV
(one block per query, headed by "# name") or as JSON with --format json.

The trace processor binary:
  --tp-bin PATH, or $PERFETTO_TP_BIN, or trace_processor_shell on PATH, or
  else the "perfetto" Python package (declared in this script's metadata, so
  `uv run` installs it) downloads the pinned trace_processor_shell with curl
  on first use and caches it under ~/.local/share/perfetto/prebuilts/. That
  binary is linked against glibc: on NixOS it runs only with nix-ld enabled;
  otherwise pass --tp-bin with the trace_processor_shell from the "tools"
  output of nixpkgs' perfetto package (nix build 'nixpkgs#perfetto^tools').
  The command-line mode used here needs no network and no local socket.

For a visual timeline, open the bugreport zip at https://ui.perfetto.dev/;
the page parses it in the browser.

Exit codes:
  0  all queries ran
  1  a query failed (the trace processor's error is printed)
  2  usage error, or no trace processor binary could be found
"""

from __future__ import annotations

import argparse
import csv
import importlib
import json
import os
import re
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] - runs trace_processor_shell
import sys
import tempfile
from pathlib import Path
from string import Template
from textwrap import dedent
from typing import TextIO

if sys.version_info < (3, 11):  # ruff: ignore[outdated-version-block] - message for users of old Python
    sys.exit("perfetto_sql.py needs Python 3.11 or newer")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from androiddiag.common import parse_utc_offset as parse_offset

DEFAULT_TIMEOUT_S = 300
NULL = "[NULL]"
# One CSV field of trace_processor_shell output. Strings are quoted, but quotes
# inside a string are not doubled, so a quoted field ends at a quote followed
# by a comma or the end of the line. Numbers and NULL markers are unquoted.
_FIELD_RE = re.compile(r'"(?P<quoted>.*?)"(?=,|$)|(?P<bare>[^,"]*)(?=,|$)')

# Intervals while unplugged, screen off and awake, from the battery history.
_STANDBY_TABLES = dedent(
    """\
    INCLUDE PERFETTO MODULE android.battery_stats;
    INCLUDE PERFETTO MODULE intervals.intersect;
    CREATE PERFETTO TABLE diag_unplugged AS
    SELECT ROW_NUMBER() OVER () AS id, ts, dur FROM android_battery_stats_state
    WHERE track_name = 'battery_stats.plugged' AND value = 0 AND dur > 0;
    CREATE PERFETTO TABLE diag_screen_off AS
    SELECT ROW_NUMBER() OVER () AS id, ts, dur FROM android_battery_stats_state
    WHERE track_name = 'battery_stats.screen' AND value = 0 AND dur > 0;
    CREATE PERFETTO TABLE diag_awake AS
    SELECT ROW_NUMBER() OVER () AS id, ts, dur FROM android_battery_stats_state
    WHERE track_name = 'battery_stats.running' AND value = 1 AND dur > 0;
    CREATE PERFETTO TABLE diag_off_unplugged AS
    SELECT ROW_NUMBER() OVER () AS id, ts, dur
    FROM _interval_intersect!((diag_unplugged, diag_screen_off), ());
    """,
)

# Each template may use $standby_tables (the tables above) and $offset (minutes
# east of UTC, applied to printed times). Only the last statement may be a SELECT.
QUERIES: dict[str, tuple[str, str]] = {
    "standby": (
        "screen-off time, awake share and resumes while unplugged",
        dedent(
            """\
            $standby_tables
            CREATE PERFETTO TABLE diag_off_awake AS
            SELECT ts, dur
            FROM _interval_intersect!((diag_off_unplugged, diag_awake), ());
            CREATE PERFETTO TABLE diag_resumes AS
            SELECT count(*) AS n FROM diag_awake a JOIN diag_off_unplugged o
            ON a.ts >= o.ts AND a.ts < o.ts + o.dur;
            SELECT
              round((SELECT sum(dur) FROM diag_unplugged) / 1e9, 1) AS on_battery_s,
              round((SELECT sum(dur) FROM diag_off_unplugged) / 1e9, 1)
                AS screen_off_s,
              round((SELECT sum(dur) FROM diag_off_awake) / 1e9, 1)
                AS screen_off_awake_s,
              round(100.0 * (SELECT sum(dur) FROM diag_off_awake)
                / (SELECT sum(dur) FROM diag_off_unplugged), 1) AS screen_off_awake_pct,
              (SELECT n FROM diag_resumes) AS screen_off_resumes,
              round((SELECT n FROM diag_resumes)
                / ((SELECT sum(dur) FROM diag_off_unplugged) / 3.6e12), 1)
                AS screen_off_resumes_per_h;
            """,
        ),
    ),
    "deep_idle": (
        "Doze states during screen-off time unplugged",
        dedent(
            """\
            $standby_tables
            CREATE PERFETTO TABLE diag_idle AS
            SELECT ROW_NUMBER() OVER () AS id, ts, dur, value
            FROM android_battery_stats_state
            WHERE track_name = 'battery_stats.device_idle' AND dur > 0;
            SELECT
              CASE d.value WHEN 0 THEN 'off' WHEN 1 THEN 'light' WHEN 2 THEN 'deep'
                ELSE CAST(d.value AS TEXT) END AS doze,
              round(sum(i.dur) / 1e9, 1) AS screen_off_unplugged_s
            FROM _interval_intersect!((diag_off_unplugged, diag_idle), ()) i
            JOIN diag_idle d ON d.id = i.id_1
            GROUP BY d.value ORDER BY d.value;
            """,
        ),
    ),
    "battery": (
        "battery level, charge counter and plug type samples",
        dedent(
            """\
            SELECT
              datetime(c.ts / 1000000000, 'unixepoch', '$offset minutes') AS time,
              CASE t.name WHEN 'batt.capacity_pct' THEN 'level_pct'
                WHEN 'batt.charge_uah' THEN 'charge_mah'
                ELSE 'plug_type' END AS counter,
              CASE t.name WHEN 'batt.charge_uah' THEN round(c.value / 1000.0, 1)
                ELSE c.value END AS value
            FROM counter c JOIN counter_track t ON c.track_id = t.id
            WHERE t.name IN ('batt.capacity_pct', 'batt.charge_uah', 'PlugType')
            ORDER BY c.ts, t.name;
            """,
        ),
    ),
    "screen": (
        "screen on and off intervals",
        dedent(
            """\
            INCLUDE PERFETTO MODULE android.battery_stats;
            SELECT
              datetime(ts / 1000000000, 'unixepoch', '$offset minutes') AS start,
              datetime((ts + dur) / 1000000000, 'unixepoch', '$offset minutes')
                AS end_time,
              CASE value WHEN 1 THEN 'on' ELSE 'off' END AS screen,
              round(dur / 1e9, 1) AS duration_s
            FROM android_battery_stats_state
            WHERE track_name = 'battery_stats.screen' AND dur > 0
            ORDER BY ts;
            """,
        ),
    ),
}


class QueryError(Exception):
    """The trace processor could not run a query."""


def parse_utc_offset(text: str | None) -> int:
    """Return minutes east of UTC for ``+0300``, ``-05:30`` or None (0)."""
    if not text:
        return 0
    offset = parse_offset(text)
    if offset is None:
        msg = f"UTC offset must look like +0300 or -05:30, not {text!r}"
        raise ValueError(msg)
    return int(offset.total_seconds()) // 60


def build_query(name: str, offset_minutes: int = 0) -> str:
    """Return the SQL of canned query ``name`` with times shifted by the offset."""
    if name not in QUERIES:
        known = ", ".join(QUERIES)
        msg = f"unknown query {name!r}; known: {known}"
        raise KeyError(msg)
    return Template(QUERIES[name][1]).substitute(
        standby_tables=_STANDBY_TABLES.rstrip("\n"),
        offset=f"{offset_minutes:+d}",
    )


def _value(m: re.Match[str]) -> str | int | float | None:
    if m["quoted"] is not None:
        return None if m["quoted"] == NULL else m["quoted"]
    bare = m["bare"].strip()
    if bare in {"", NULL}:
        return None
    try:
        return int(bare)
    except ValueError:
        pass
    try:
        return float(bare)
    except ValueError:
        return bare


def parse_row(line: str) -> list[str | int | float | None]:
    """Split one output line into typed fields (str, int, float or None)."""
    fields = []
    pos = 0
    while True:
        m = _FIELD_RE.match(line, pos)
        if m is None:
            msg = f"cannot parse trace processor output line: {line!r}"
            raise ValueError(msg)
        fields.append(_value(m))
        pos = m.end()
        if pos >= len(line):
            return fields
        pos += 1  # the comma


def parse_output(text: str) -> list[dict[str, str | int | float | None]]:
    """Parse trace_processor_shell CSV output into one dict per row."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    columns = [str(c) for c in parse_row(lines[0])]
    return [dict(zip(columns, parse_row(line), strict=False)) for line in lines[1:]]


def find_trace(path: Path) -> Path:
    """Return the bugreport zip itself, or the one inside a workdir."""
    if path.is_dir():
        zips = sorted(path.glob("bugreport*.zip"))
        if not zips:
            msg = f"{path}: no bugreport*.zip inside"
            raise FileNotFoundError(msg)
        return zips[0]
    if not path.exists():
        msg = f"{path} does not exist"
        raise FileNotFoundError(msg)
    return path


def resolve_tp_bin(explicit: Path | None) -> Path:
    """Find trace_processor_shell; may download it via the perfetto package."""
    if explicit:
        return explicit
    if env := os.environ.get("PERFETTO_TP_BIN"):
        return Path(env)
    if found := shutil.which("trace_processor_shell"):
        return Path(found)
    try:
        manifests = importlib.import_module(
            "perfetto.prebuilts.manifests.trace_processor_shell",
        )
        prebuilts = importlib.import_module("perfetto.prebuilts.perfetto_prebuilts")
    except ImportError as exc:
        msg = (
            "no trace processor: pass --tp-bin, set PERFETTO_TP_BIN, or run this "
            "script with `uv run` so the perfetto package can fetch one"
        )
        raise FileNotFoundError(msg) from exc
    print("locating trace_processor_shell (first use downloads it)", file=sys.stderr)
    manifest = manifests.TRACE_PROCESSOR_SHELL_MANIFEST
    return Path(prebuilts.get_perfetto_prebuilt(manifest))


def run_sql(tp_bin: Path, trace: Path, sql: str, timeout_s: int) -> str:
    """Run ``sql`` on ``trace`` with the trace processor CLI; return stdout."""
    with tempfile.NamedTemporaryFile(
        "w",
        suffix=".sql",
        delete=False,
        encoding="utf-8",
    ) as handle:
        handle.write(sql)
        sql_path = Path(handle.name)
    cmd = [str(tp_bin), "query", "-f", str(sql_path), str(trace)]
    try:
        proc = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - argv list
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except OSError as exc:
        msg = (
            f"cannot start {tp_bin}: {exc}. A downloaded binary needs glibc's "
            "loader; on NixOS enable nix-ld or pass --tp-bin."
        )
        raise QueryError(msg) from exc
    except subprocess.TimeoutExpired as exc:
        msg = f"the trace processor did not finish within {timeout_s} s"
        raise QueryError(msg) from exc
    finally:
        sql_path.unlink(missing_ok=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-8:])
        msg = f"trace processor exit code {proc.returncode}:\n{tail}"
        raise QueryError(msg)
    return proc.stdout


def write_csv(name: str, rows: list[dict], out: TextIO) -> None:
    """Print one result block as CSV, headed by ``# name``."""
    out.write(f"# {name}\n")
    if not rows:
        out.write("(no rows)\n")
        return
    writer = csv.DictWriter(out, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("trace", nargs="?", type=Path, help="bugreport zip or workdir")
    parser.add_argument(
        "--query",
        action="append",
        choices=sorted(QUERIES),
        help="canned query to run (repeatable; default: all)",
    )
    parser.add_argument("--sql", type=Path, help="run the SQL in this file")
    parser.add_argument("--format", choices=("csv", "json"), default="csv")
    parser.add_argument("--tp-bin", type=Path, help="trace_processor_shell to use")
    parser.add_argument(
        "--utc-offset",
        help="shift printed times from UTC, e.g. +0300 (default: UTC)",
    )
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--list", action="store_true", help="list canned queries")
    parser.add_argument(
        "--print-sql",
        action="store_true",
        help="print the SQL instead of running it",
    )
    args = parser.parse_args(argv)
    try:
        args.offset_minutes = parse_utc_offset(args.utc_offset)
    except ValueError as exc:
        parser.error(str(exc))
    if not (args.list or args.print_sql) and args.trace is None:
        parser.error("give a bugreport zip or a workdir")
    return args


def selected(args: argparse.Namespace) -> dict[str, str]:
    """Return ``{name: sql}`` for the queries to run."""
    queries = {}
    names = args.query or ([] if args.sql else list(QUERIES))
    for name in names:
        queries[name] = build_query(name, args.offset_minutes)
    if args.sql:
        queries[args.sql.stem] = args.sql.read_text(encoding="utf-8")
    return queries


def main(argv: list[str] | None = None) -> int:
    """Run the selected queries and print their results."""
    args = parse_args(argv)
    if args.list:
        for name, (description, _) in QUERIES.items():
            print(f"{name:10} {description}")
        return 0
    queries = selected(args)
    if args.print_sql:
        for name, sql in queries.items():
            print(f"-- {name}\n{sql}")
        return 0
    try:
        trace = find_trace(args.trace)
        tp_bin = resolve_tp_bin(args.tp_bin)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 2
    results: dict[str, list[dict]] = {}
    for name, sql in queries.items():
        try:
            results[name] = parse_output(run_sql(tp_bin, trace, sql, args.timeout))
        except (QueryError, ValueError) as exc:
            print(f"{name}: {exc}", file=sys.stderr)
            return 1
    if args.format == "json":
        print(json.dumps(results, indent=1, ensure_ascii=False))
    else:
        for name, rows in results.items():
            write_csv(name, rows, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
