"""Tests for scripts/perfetto_sql.py with a fake trace_processor_shell.

Nothing is downloaded: every run passes --tp-bin pointing at a small Python
script that records its arguments and prints canned trace-processor output.
"""

from __future__ import annotations

import json
import sys
import zipfile
from textwrap import dedent

import perfetto_sql
import pytest

FAKE_TP = dedent(
    """\
    #!PYTHON
    import json, os, sys
    from pathlib import Path

    args = sys.argv[1:]
    sql = Path(args[2]).read_text()
    with open(os.environ["FAKE_TP_LOG"], "a") as log:
        log.write(json.dumps({"args": args, "sql": sql}) + "\\n")
    if os.environ.get("FAKE_TP_FAIL"):
        print("Traceback: syntax error near 'nothing'", file=sys.stderr)
        sys.exit(1)
    print()
    if "screen_off_awake_pct" in sql:
        print('"on_battery_s","screen_off_awake_pct","screen_off_resumes"')
        print("14400.000000,55.500000,2700")
    else:
        print('"name","value"')
        print('"a,b","[NULL]"')
        print('"say "hi"",2.5')
    """,
)


@pytest.fixture
def fake_tp(tmp_path, monkeypatch):
    path = tmp_path / "trace_processor_shell"
    path.write_text(FAKE_TP.replace("PYTHON", sys.executable))
    path.chmod(0o755)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("FAKE_TP_LOG", str(log))
    monkeypatch.delenv("FAKE_TP_FAIL", raising=False)
    return path, log


@pytest.fixture
def trace(tmp_path):
    workdir = tmp_path / "wd"
    workdir.mkdir()
    zip_path = workdir / "bugreport-test.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("main_entry.txt", "bugreport-test.txt")
    return workdir, zip_path


def calls(log):
    return [json.loads(line) for line in log.read_text().splitlines()]


@pytest.mark.parametrize(
    ("text", "minutes"),
    [(None, 0), ("+0300", 180), ("-05:30", -330), ("+0000", 0)],
)
def test_parse_utc_offset(text, minutes):
    assert perfetto_sql.parse_utc_offset(text) == minutes


def test_parse_utc_offset_rejects_garbage():
    with pytest.raises(ValueError, match="UTC offset"):
        perfetto_sql.parse_utc_offset("3 hours")


def test_build_query_shifts_times_and_includes_tables():
    sql = perfetto_sql.build_query("screen", 180)
    assert "'+180 minutes'" in sql
    assert "$" not in sql
    standby = perfetto_sql.build_query("standby")
    assert standby.startswith("INCLUDE PERFETTO MODULE android.battery_stats;")
    assert "CREATE PERFETTO TABLE diag_off_unplugged" in standby
    assert standby.rstrip().endswith("AS screen_off_resumes_per_h;")
    assert "'-330 minutes'" in perfetto_sql.build_query("battery", -330)


def test_build_query_unknown_name():
    with pytest.raises(KeyError, match="unknown query"):
        perfetto_sql.build_query("wakeups")


def test_every_query_ends_with_one_select():
    for name in perfetto_sql.QUERIES:
        statements = [
            s.strip() for s in perfetto_sql.build_query(name).split(";") if s.strip()
        ]
        assert statements[-1].startswith("SELECT"), name
        assert not any(s.startswith("SELECT") for s in statements[:-1]), name


def test_parse_output_types_nulls_and_quirks():
    text = dedent(
        """\

        "name","count","share","empty"
        "a,b",3,1.500000,"[NULL]"
        "say "hi"",-2,0.000000,[NULL]
        """,
    )
    assert perfetto_sql.parse_output(text) == [
        {"name": "a,b", "count": 3, "share": 1.5, "empty": None},
        {"name": 'say "hi"', "count": -2, "share": 0.0, "empty": None},
    ]


def test_parse_output_empty():
    assert perfetto_sql.parse_output("\n") == []


def test_run_canned_queries_as_json(fake_tp, trace, capsys):
    tp, log = fake_tp
    workdir, zip_path = trace
    argv = [str(workdir), "--tp-bin", str(tp), "--query", "standby", "--format", "json"]
    assert perfetto_sql.main(argv) == 0
    data = json.loads(capsys.readouterr().out)
    assert data == {
        "standby": [
            {
                "on_battery_s": 14400.0,
                "screen_off_awake_pct": 55.5,
                "screen_off_resumes": 2700,
            },
        ],
    }
    (call,) = calls(log)
    assert call["args"][0:2] == ["query", "-f"]
    assert call["args"][3] == str(zip_path)
    assert "screen_off_awake_pct" in call["sql"]


def test_all_queries_by_default_as_csv(fake_tp, trace, capsys):
    tp, log = fake_tp
    assert perfetto_sql.main([str(trace[1]), "--tp-bin", str(tp)]) == 0
    out = capsys.readouterr().out
    assert [line for line in out.splitlines() if line.startswith("# ")] == [
        f"# {name}" for name in perfetto_sql.QUERIES
    ]
    assert 'name,value\n"a,b",\n"say ""hi""",2.5\n' in out
    assert len(calls(log)) == len(perfetto_sql.QUERIES)


def test_sql_file(fake_tp, trace, tmp_path, capsys):
    tp, log = fake_tp
    sql = tmp_path / "mine.sql"
    sql.write_text("SELECT 1 AS one;\n")
    assert (
        perfetto_sql.main([str(trace[1]), "--tp-bin", str(tp), "--sql", str(sql)]) == 0
    )
    assert capsys.readouterr().out.startswith("# mine\n")
    assert calls(log)[0]["sql"] == "SELECT 1 AS one;\n"


def test_query_failure_is_reported(fake_tp, trace, monkeypatch, capsys):
    tp, _ = fake_tp
    monkeypatch.setenv("FAKE_TP_FAIL", "1")
    assert (
        perfetto_sql.main([str(trace[1]), "--tp-bin", str(tp), "--query", "screen"])
        == 1
    )
    err = capsys.readouterr().err
    assert "screen: trace processor exit code 1" in err
    assert "syntax error near 'nothing'" in err


def test_unstartable_binary(trace, tmp_path, capsys):
    broken = tmp_path / "not_executable"
    broken.write_text("not a program")
    assert perfetto_sql.main([str(trace[1]), "--tp-bin", str(broken)]) == 1
    assert "cannot start" in capsys.readouterr().err


def test_missing_trace(fake_tp, tmp_path, capsys):
    tp, _ = fake_tp
    empty = tmp_path / "empty"
    empty.mkdir()
    assert perfetto_sql.main([str(empty), "--tp-bin", str(tp)]) == 2
    assert "no bugreport*.zip" in capsys.readouterr().err


def test_list_and_print_sql_need_no_trace(capsys):
    assert perfetto_sql.main(["--list"]) == 0
    listed = capsys.readouterr().out
    assert all(name in listed for name in perfetto_sql.QUERIES)
    assert (
        perfetto_sql.main(
            ["--print-sql", "--query", "battery", "--utc-offset", "+0200"]
        )
        == 0
    )
    assert "'+120 minutes'" in capsys.readouterr().out


def test_help_explains_the_gaps(capsys):
    with pytest.raises(SystemExit):
        perfetto_sql.main(["--help"])
    text = capsys.readouterr().out
    assert '"wr"' in text
    assert "ui.perfetto.dev" in text
    assert "--tp-bin" in text
