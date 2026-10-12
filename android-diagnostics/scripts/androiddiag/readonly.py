"""Keep every command sent to the phone read-only, and run it through adb.

Two layers guard ``adb shell``:

1. :func:`check_shell` rejects a command that contains a fragment of
   :data:`androiddiag.catalog.FORBIDDEN_FRAGMENTS` (``--checkin``,
   ``settings put``, ``logcat -c``...). Every command passes through it,
   including the static ``LIVE_COMMANDS``, which use loops and pipes and are
   otherwise trusted.
2. :func:`check_adhoc` also requires a command typed by a person or an agent
   (``adb_ro.py``) to match an allow-list of read-only programs and argument
   shapes, and rejects shell syntax outright. Without ``;``, ``|``,
   redirections, substitutions, quotes, braces, ``~`` or ``#``, the phone's
   shell runs the words checked here. It only expands globs in paths, which
   are checked against every name they could match, and in the logcat filter
   ``*:LEVEL``, which matches no file in ``/``, where ``adb shell`` starts.

Device selection and the command runner live here too, so that the checks sit
on the only path from the scripts to ``adb shell``.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] - adb is the point
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .catalog import FORBIDDEN_FRAGMENTS

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

# ---------------------------------------------------------------- layer 1

# Quotes and backslashes are dropped and command separators become spaces
# before matching, so ``settings 'put'`` and ``cat x;rm -rf /`` still hit the
# deny-list.
_QUOTES_RE = re.compile(r"[\"'\\]")
_SEPARATORS_RE = re.compile(r"[;&|()`<>{}\s]+")


def check_shell(command: str) -> None:
    """Raise ValueError if ``command`` contains a state-changing fragment."""
    flat = _SEPARATORS_RE.sub(" ", _QUOTES_RE.sub("", command))
    padded = f" {flat.strip()} "
    for fragment in FORBIDDEN_FRAGMENTS:
        if fragment in padded:
            msg = (
                f"{fragment.strip()!r} is on the deny-list of commands that change "
                "the phone's state"
            )
            raise ValueError(msg)


# ---------------------------------------------------------------- layer 2

# Shell syntax that could chain, redirect, substitute or quote, or make the
# phone's words differ from the checked ones: quotes, brace expansion (mksh,
# Android's sh, turns "{.,/sdcard/x}" into two words), "~" (the home
# directory) and "#" (a comment that drops the rest of the line).
_SHELL_SYNTAX = frozenset(";&|<>`$()\\'\"{}~#")
# A plain word: no globs, no shell syntax, not starting with "+".
_WORD_RE = re.compile(r"^[A-Za-z0-9_.,:=@%/-][A-Za-z0-9_.,:=@%+/-]*$")
_GLOB_CHARS = frozenset("*?[]")

# Directories whose files cat, head, tail, grep, ls and wc may read; the list
# keeps ad-hoc reads away from personal files.
READ_PREFIXES = ("/proc", "/sys", "/vendor/etc", "/system/etc", "/product/etc")
_PATH_RE = re.compile(r"^/[A-Za-z0-9_.,:=@%+/*?\[\]-]*$")
# Per-process entries that lead out of /proc: the root and working-directory
# links, open file descriptors and process memory.
_PROC_ESCAPES = ("root", "cwd", "fd", "map_files", "mem")
# Most reads change nothing, but these files hand out each byte once and block
# while empty: reading takes kernel messages from logd (/proc/kmsg, readable
# when adb runs as root) and trace events from a running Perfetto or atrace
# session. Reading a tracefs "trace" file pauses that recording meanwhile.
_CONSUMING_FILES = ("kmsg", "trace_pipe", "trace_pipe_raw", "trace")


def _words(text: str) -> frozenset[str]:
    """Return the whitespace-separated words of ``text`` (keeps lists short)."""
    return frozenset(text.split())


def _fail(message: str) -> None:
    raise ValueError(message)


def _plain(word: str, what: str) -> None:
    if not _WORD_RE.match(word):
        _fail(
            f"{what} {word!r} may only contain letters, digits and _.,:=@%+/- "
            "(no globs)",
        )


def _check_path(word: str, *, reads: bool = True) -> None:
    """Check a path argument; ``reads`` is false for ls, which reads no file."""
    if not _PATH_RE.match(word) or ".." in word:
        _fail(f"path {word!r} must be absolute, without '..' or braces")
    if not any(word == p or word.startswith(f"{p}/") for p in READ_PREFIXES):
        _fail(f"path {word!r} is outside {', '.join(READ_PREFIXES)}")
    parts = word.split("/")
    if parts[1] == "proc":
        for part in parts[3:]:
            if any(fnmatch.fnmatchcase(name, part) for name in _PROC_ESCAPES):
                _fail(f"path {word!r} could leave /proc through {part!r}")
    if reads and any(fnmatch.fnmatchcase(n, parts[-1]) for n in _CONSUMING_FILES):
        _fail(
            f"path {word!r} could name {', '.join(_CONSUMING_FILES)}; reading "
            "those takes data from the kernel log reader or a running trace",
        )


# ``dumpsys SERVICE ARGS`` hands ARGS to the service's dump(), and many
# services act on them instead of printing: they delete or fake statistics
# (``batterystats --reset`` or ``--history-create-events``, ``procstats
# --clear``, ``wifi wifiMetricsProto``, ``location --gnssmetrics``), change
# the phone (``deviceidle motion`` leaves Doze, ``netpolicy --unsnooze``,
# ``sensorservice data_injection``, ``storaged --time_window``) or pass them
# on: ``dumpsys activity WORD`` runs ``am WORD`` when WORD names no sub-dump,
# and ``activity service NAME ARGS`` hands ARGS to an app's own dump(). So any
# service may be dumped without arguments, but arguments are allowed only in
# the forms below, each read in the service's dump() in AOSP
# android15-release. Each pattern matches the arguments, each after a space.
_PKG = r"[A-Za-z]\w*(?:\.\w+)+"
_APP_PROCESS = rf"\d+|{_PKG}(?::[\w.]+)?"  # a PID or an app's process name


def _many(*words: str) -> str:
    """Return a pattern for any number of words, each matching one of WORDS."""
    return rf"(?: (?:{'|'.join(words)}))*"


def _optional(*words: str) -> str:
    """Return a pattern for at most one word matching one of WORDS."""
    return rf"(?: (?:{'|'.join(words)}))?"


def _form(accepts: str, pattern: str) -> tuple[str, re.Pattern[str]]:
    """Pair the description shown on rejection with the compiled pattern."""
    return accepts, re.compile(pattern, re.ASCII)


_DUMPSYS_FORMS: dict[str, tuple[str, re.Pattern[str]]] = {
    # Not --history-start (saves the stats), --history-create-events (adds
    # fake wakelocks), --read-daily, --new-daily, --usage (samples power
    # stats), --checkin (deletes the previous period).
    "batterystats": _form(
        "--charged, -c, -a, --history, --daily, --cpu, --wakeups, --settings, "
        "--power-profile, PACKAGE",
        _many(
            "--charged",
            "-c",
            "-a",
            "--history",
            "--daily",
            "--cpu",
            "--wakeups",
            "--settings",
            "--power-profile",
            _PKG,
        ),
    ),
    # Not --read, --pretend-screen-on|off, --commit, --clear, --start-testing.
    # -a deletes a committed file only when the file cannot be parsed.
    "procstats": _form(
        "--hours N, --last N, --max N, --current, --active, --details, "
        "--full-details, -a, -c, PACKAGE",
        _many(
            r"--(?:hours|last|max) \d+",
            "--current",
            "--active",
            "--details",
            "--full-details",
            "-a",
            "-c",
            _PKG,
        ),
    ),
    # Nothing may follow service or provider NAME: the app's own dump() reads
    # it (Bluetooth's --proto-bin, telephony's --metricsproto clear metrics).
    # NAME may not be "all" or "all-..." (DumpUtils.filterRecord keywords),
    # which run the dump() of every matching app's services at once.
    "activity": _form(
        "one of services|processes|exit-info|start-info|intents [PACKAGE], "
        "broadcasts [history|PACKAGE], settings, lmk, oom, lru, recents, "
        "users, service NAME, provider NAME (nothing after NAME, NAME not all*)",
        r" (?:(?:services|processes|exit-info|start-info|intents)"
        rf"{_optional(_PKG)}|broadcasts{_optional('history', _PKG)}"
        r"|settings|lmk|oom|lru|recents|users"
        r"|(?:service|provider) (?!all(?:-|$))[A-Za-z][\w.-]*(?:/[\w.]+)?)",
    ),
    "package": _form("PACKAGE or dexopt", rf" (?:{_PKG}|dexopt)"),
    # Not --unreachable, which stops the process to scan its heap.
    "meminfo": _form(
        "-a, -d, -s, -S, -c, --oom, --package, --local, then a PID or process name",
        _many("-a", "-d", "-s", "-S", "-c", "--oom", "--package", "--local")
        + _optional(r"\d+", r"[A-Za-z][\w.]*(?::[\w.]+)?"),
    ),
    # Not reset; framestats only prints the recent frames.
    "gfxinfo": _form(
        "PACKAGE or PID, then optionally framestats",
        rf" (?:{_APP_PROCESS})(?: framestats)?",
    ),
    # Not poll or --poll, which force a persisting poll.
    "netstats": _form(
        "detail, full, --full, --uid, --tag",
        _many("detail", "full", "--full", "--uid", "--tag"),
    ),
    "dropbox": _form(
        "--print, -p, --file, -f, TAG or DATE",
        _many("--print", "-p", "--file", "-f", r"[A-Za-z0-9][\w.:-]*"),
    ),
    # Not --time_window (changes the I/O sampling interval) or --force.
    "storaged": _form(
        "--hours N, --debug",
        _many(r"--hours \d+(?:\.\d+)?", "--debug"),
    ),
    # Not flush.
    "usagestats": _form("PACKAGE", _many(_PKG)),
    "jobscheduler": _form("PACKAGE", _optional(_PKG)),
}


def _dumpsys(args: list[str]) -> None:
    match args:
        case ["-l"]:
            return
        case []:
            _fail("dumpsys needs a service name; use a bugreport for everything")
        case [service, *_] if service.startswith("-"):
            _fail("put the service first: dumpsys <service> [arguments]")
        case [service]:
            _plain(service, "service name")
        case [service, *rest] if service in _DUMPSYS_FORMS:
            accepts, pattern = _DUMPSYS_FORMS[service]
            if not pattern.fullmatch("".join(f" {arg}" for arg in rest)):
                _fail(
                    f"dumpsys {service} {' '.join(rest)}: not an allowed form; "
                    f"dumpsys {service} accepts only {accepts}",
                )
        case [service, *_]:
            _fail(
                f"dumpsys {service} takes no arguments here, because services act "
                "on some of them ('dumpsys deviceidle motion' ends Doze). Run "
                f"'dumpsys {service}' alone. Only {', '.join(sorted(_DUMPSYS_FORMS))} "
                "accept vetted arguments",
            )


def _getprop(args: list[str]) -> None:
    match args:
        case []:
            return
        case [name] if not name.startswith("-"):
            _plain(name, "property name")
        case _:
            _fail("getprop takes at most one property name and no options")


def _file_reader(
    program: str,
    options: str,
    value_options: frozenset[str] = frozenset(),
    *,
    reads: bool = True,
) -> Callable[[list[str]], None]:
    """Return a validator for ``program [options] PATH...``."""
    option_re = re.compile(options)

    def check(args: list[str]) -> None:
        paths = 0
        expect_value = False
        for arg in args:
            if expect_value:
                _plain(arg, f"{program} option value")
                expect_value = False
            elif arg.startswith("-"):
                if not option_re.match(arg):
                    _fail(f"{program} option {arg!r} is not allowed")
                expect_value = arg in value_options
            else:
                _check_path(arg, reads=reads)
                paths += 1
        if expect_value:
            _fail(f"{program} option {args[-1]!r} needs a value")
        if not paths:
            _fail(f"{program} needs a path under {', '.join(READ_PREFIXES)}")

    return check


# No -f/-F: tail would follow the file forever.
_HEAD_TAIL_OPTIONS = r"^-(?:[nc]\d*|\d+|q|v)$"
_HEAD_TAIL_VALUES = frozenset({"-n", "-c"})
# toybox grep options that only change what is matched or printed, and those
# whose value is the next word. Not -r or -R: recursion reaches the consuming
# files above, and -R follows /proc/self/root out of READ_PREFIXES. Not -f (a
# pattern file) or -S/-M (exclude and include globs, which take a value).
_GREP_FLAGS = "EFHILZabchilnoqsvwxz"
_GREP_VALUE_FLAGS = "emABC"
_GREP_OPTION_RE = re.compile(f"^-[{_GREP_FLAGS}{_GREP_VALUE_FLAGS}]+$")


def _grep_pattern(pattern: str) -> None:
    if _GLOB_CHARS & set(pattern):
        _fail(
            f"grep pattern {pattern!r}: the phone's shell would expand * ? [ ] "
            "into file names",
        )


def _grep_option(arg: str) -> str:
    """Check one grep option word; return the option whose value comes next."""
    if not _GREP_OPTION_RE.match(arg):
        _fail(
            f"grep option {arg!r} is not allowed; use -{_GREP_FLAGS} and "
            f"-{'/-'.join(_GREP_VALUE_FLAGS)} VALUE (no recursion, no -f)",
        )
    # getopt takes the rest of the word as the value: "-er" is -e "r".
    if any(letter in _GREP_VALUE_FLAGS for letter in arg[1:-1]):
        _fail(f"grep option {arg!r}: put -e, -m, -A, -B or -C last in a group")
    return arg[-1] if arg[-1] in _GREP_VALUE_FLAGS else ""


def _grep(args: list[str]) -> None:
    # toybox and GNU grep move options before the other words, and once any
    # -e is given every other word is a file: "grep notes.txt -e . /proc/x"
    # reads notes.txt. So look for -e (or a group ending in e) first.
    e_given = any(
        (_GREP_OPTION_RE.match(arg) and arg.endswith("e")) or arg.startswith("--regexp")
        for arg in args
    )
    pattern_seen = False
    paths = 0
    expect = ""
    for arg in args:
        if expect == "e":
            _grep_pattern(arg)
            pattern_seen, expect = True, ""
        elif expect:
            _plain(arg, f"grep -{expect} value")
            expect = ""
        elif arg.startswith("-") and len(arg) > 1:
            expect = _grep_option(arg)
        elif not pattern_seen and not e_given:
            _grep_pattern(arg)
            pattern_seen = True
        else:
            _check_path(arg)
            paths += 1
    if expect or not pattern_seen or not paths:
        _fail(f"grep needs a pattern and a path under {', '.join(READ_PREFIXES)}")


def _ps(args: list[str]) -> None:
    for arg in args:
        _plain(arg, "ps argument")


def _top(args: list[str]) -> None:
    for arg in args:
        _plain(arg, "top argument")
    if "-b" not in args:
        _fail("top needs -b (batch mode)")
    if not any(a == "-n" or re.match(r"^-n\d+$", a) for a in args):
        _fail("top needs -n COUNT; without it it never exits")


def _options_only(program: str, letters: str) -> Callable[[list[str]], None]:
    option_re = re.compile(rf"^-[{letters}]+$")

    def check(args: list[str]) -> None:
        for arg in args:
            if not option_re.match(arg):
                _fail(f"{program} accepts only the options -[{letters}]")

    return check


_DATE_FORMAT_RE = re.compile(r"^\+[A-Za-z0-9%:._,/-]+$")


def _date(args: list[str]) -> None:
    for arg in args:
        if arg not in {"-u", "-R", "-I", "--utc"} and not _DATE_FORMAT_RE.match(arg):
            _fail("date accepts only -u, -R, -I and +FORMAT; others set the clock")


def _df(args: list[str]) -> None:
    for arg in args:
        if re.match(r"^-[A-Za-z]+$", arg):
            continue
        if not re.match(r"^/[\w./-]*$", arg) or ".." in arg:
            _fail(f"df argument {arg!r} must be an option or an absolute path")


_SETTINGS_NAMESPACES = frozenset({"global", "secure", "system"})


def _settings(args: list[str]) -> None:
    match args:
        case ["get", namespace, name] if namespace in _SETTINGS_NAMESPACES:
            _plain(name, "setting name")
        case ["list", namespace] if namespace in _SETTINGS_NAMESPACES:
            return
        case _:
            _fail("settings: only 'get NAMESPACE NAME' and 'list NAMESPACE'")


def _device_config(args: list[str]) -> None:
    match args:
        case ["get", namespace, key]:
            _plain(namespace, "namespace")
            _plain(key, "key")
        case ["list"]:
            return
        case ["list", namespace]:
            _plain(namespace, "namespace")
        case _:
            _fail("device_config: only 'get NAMESPACE KEY' and 'list [NAMESPACE]'")


_PM_LISTS = _words(
    "packages features libraries users permissions permission-groups instrumentation",
)


def _pm_list(args: list[str]) -> None:
    if not args or args[0] not in _PM_LISTS:
        _fail(f"pm list: only {', '.join(sorted(_PM_LISTS))}")
    for arg in args[1:]:
        _plain(arg, "pm list argument")


def _pm(args: list[str]) -> None:
    match args:
        case ["list", *rest]:
            _pm_list(rest)
        case ["path", package]:
            _plain(package, "package name")
        case _:
            _fail("pm: only 'list ...' and 'path PACKAGE'")


_DEVICEIDLE_GET = _words("light deep force screen charging network")


def _cmd(args: list[str]) -> None:
    match args:
        case ["package", "list", *rest]:
            _pm_list(rest)
        case ["package", "resolve-activity", *rest] | ["appops", "get", *rest] if rest:
            for arg in rest:
                _plain(arg, "cmd argument")
        case ["deviceidle", "whitelist"]:
            return
        case ["deviceidle", "whitelist", *_]:
            _fail("cmd deviceidle whitelist takes no arguments; +PKG/-PKG edit it")
        case ["deviceidle", "get", what] if what in _DEVICEIDLE_GET:
            return
        case _:
            _fail(
                "cmd: only 'package list|resolve-activity', 'appops get PKG', "
                "'deviceidle whitelist' and 'deviceidle get "
                f"{'|'.join(sorted(_DEVICEIDLE_GET))}'",
            )


# logcat options that change buffers or write files, with the reason.
_LOGCAT_BAD = {
    "-c": "clears the log buffers",
    "--clear": "clears the log buffers",
    "-G": "changes the log buffer size",
    "--buffer-size": "changes the log buffer size",
    "-P": "changes the prune list",
    "-p": "is a prune-list option",
    "--prune": "changes the prune list",
    "-f": "writes a file on the phone",
    "--file": "writes a file on the phone",
    "-r": "rotates log files on the phone",
    "--rotate-kbytes": "rotates log files on the phone",
    "-n": "rotates log files on the phone",
    "--rotate-count": "rotates log files on the phone",
}
_LOGCAT_FLAGS = _words("-d -s -D -B -L")
_LOGCAT_VALUE_OPTIONS = _words("-b -v -t -T -e -m")
_LOGCAT_LONG = _words("--pid --uid --buffer --format --max-count")
# A bare "*" would expand to the file names in "/"; "*:S" matches none.
_FILTERSPEC_RE = re.compile(r"^(?:[A-Za-z0-9_.-]+(?::[VDIWEFS])?|\*:[VDIWEFS])$")


def _logcat_option(arg: str) -> str:
    """Check one logcat word; return the option whose value comes next, if any."""
    name = arg.split("=", 1)[0]
    if name in _LOGCAT_BAD:
        _fail(f"logcat {name} {_LOGCAT_BAD[name]}")
    if arg in _LOGCAT_VALUE_OPTIONS:
        return arg
    if name in _LOGCAT_LONG and "=" in arg:
        _plain(arg.split("=", 1)[1], f"logcat {name} value")
    elif arg.startswith("-") and arg not in _LOGCAT_FLAGS:
        _fail(f"logcat option {arg!r} is not on the allow-list")
    elif not arg.startswith("-") and not _FILTERSPEC_RE.match(arg):
        _fail(f"logcat filter {arg!r} must look like TAG:LEVEL or *:LEVEL")
    return ""


def _logcat(args: list[str]) -> None:
    expect = ""
    for arg in args:
        if expect:
            _plain(arg, f"logcat {expect} value")
            expect = ""
        else:
            expect = _logcat_option(arg)
    if expect:
        _fail(f"logcat {expect} needs a value")
    if "-d" not in args:
        _fail("logcat needs -d (dump and exit); without it it streams forever")


_IP_OBJECTS = _words("addr address a link l route r neigh neighbour n rule ru")
_IP_OPTION_RE = re.compile(r"^-(?:4|6|br|brief|s|stats|d|details|o|oneline|j|json)$")
_IP_VERBS = _words(
    "add del delete change replace flush set append prepend save restore get",
)


def _ip(args: list[str]) -> None:
    rest = list(args)
    while rest and rest[0].startswith("-"):
        if not _IP_OPTION_RE.match(rest[0]):
            _fail(f"ip option {rest[0]!r} is not allowed")
        rest.pop(0)
    if not rest or rest[0] not in _IP_OBJECTS:
        _fail("ip: only addr, link, route, neigh and rule")
    rest.pop(0)
    if rest and rest[0] not in {"show", "list", "ls"}:
        _fail("ip: only 'show' or 'list'")
    for arg in rest[1:]:
        _plain(arg, "ip argument")
        if arg in _IP_VERBS:
            _fail(f"ip: {arg!r} is not allowed")


def _ss(args: list[str]) -> None:
    for arg in args:
        if arg.startswith("-"):
            # No -K (kills sockets), -D (writes a file), -E (streams events),
            # -F (reads a filter file) or -N (switches network namespace).
            if not re.match(r"^-[tuanlpmoeisrxw46H0O]+$", arg):
                _fail(f"ss option {arg!r} is not allowed (-K kills sockets)")
        else:
            _plain(arg, "ss filter word")


def _service(args: list[str]) -> None:
    match args:
        case ["list"]:
            return
        case ["check", name]:
            _plain(name, "service name")
        case _:
            _fail("service: only 'list' and 'check NAME'")


_PROGRAMS: dict[str, Callable[[list[str]], None]] = {
    "dumpsys": _dumpsys,
    "getprop": _getprop,
    "cat": _file_reader("cat", r"^-[AbeEnstTuv]+$"),
    # No -L or -H: with -R they follow /proc/self/root out of READ_PREFIXES.
    "ls": _file_reader("ls", r"^-[aAbcCdFghiklnopqrRsStuUxXZ1]+$", reads=False),
    "head": _file_reader("head", _HEAD_TAIL_OPTIONS, _HEAD_TAIL_VALUES),
    "tail": _file_reader("tail", _HEAD_TAIL_OPTIONS, _HEAD_TAIL_VALUES),
    "wc": _file_reader("wc", r"^-[lcwmL]+$"),
    "grep": _grep,
    "ps": _ps,
    "top": _top,
    "uptime": _options_only("uptime", "a-z"),
    "date": _date,
    "uname": _options_only("uname", "A-Za-z"),
    "df": _df,
    "id": _options_only("id", "A-Za-z"),
    "settings": _settings,
    "device_config": _device_config,
    "pm": _pm,
    "cmd": _cmd,
    "logcat": _logcat,
    "ip": _ip,
    "netstat": _options_only("netstat", "laentuwxrWpv"),
    "ss": _ss,
    "service": _service,
}


def check_adhoc(command: str) -> list[str]:
    """Check an ad-hoc command against both layers and return its words.

    A rejected command raises ValueError with the reason.
    """
    check_shell(command)
    for char in command:
        if char in _SHELL_SYNTAX or not (char.isprintable() or char in " \t"):
            _fail(
                f"shell syntax {char!r} is not allowed in ad-hoc commands; "
                "run one simple command at a time",
            )
    words = command.split()
    if not words:
        _fail("empty command")
    validator = _PROGRAMS.get(words[0])
    if validator is None:
        _fail(
            f"{words[0]!r} is not on the allow-list of read-only programs: "
            f"{', '.join(sorted(_PROGRAMS))}",
        )
    else:
        validator(words[1:])
    return words


# ---------------------------------------------------------------- adb access


class DeviceError(Exception):
    """No usable phone: adb missing, no device, several devices, unauthorized."""


# States printed by ``adb devices``; "no permissions" is followed by a hint.
_DEVICE_LINE_RE = re.compile(
    r"^(?P<serial>\S+)\s+(?P<state>device|offline|unauthorized|authorizing|"
    r"connecting|bootloader|recovery|rescue|sideload|host|detached|unknown|"
    r"no permissions)\b(?P<rest>.*)$",
)
_DEVICE_PROP_RE = re.compile(r"\b(usb|product|model|device|transport_id):(\S+)")
_STATE_ADVICE = {
    "unauthorized": "unlock the phone and accept the 'Allow USB debugging?' prompt",
    "authorizing": "wait a moment and retry",
    "offline": "reconnect the cable, or run 'adb kill-server' and retry",
    "no permissions": "the host user may not open the USB device (check udev rules)",
}


@dataclass(frozen=True)
class Device:
    """One line of ``adb devices -l``."""

    serial: str
    state: str
    props: dict[str, str] = field(default_factory=dict, hash=False)

    @property
    def model(self) -> str:
        """The model as adb reports it (spaces become underscores)."""
        return self.props.get("model", "")


def parse_devices(text: str) -> list[Device]:
    """Parse ``adb devices -l``, ignoring daemon messages and the header."""
    devices = []
    for line in text.splitlines():
        m = _DEVICE_LINE_RE.match(line.strip())
        if m and not line.startswith(("*", "List of devices")):
            props = dict(_DEVICE_PROP_RE.findall(m["rest"]))
            devices.append(Device(m["serial"], m["state"], props))
    return devices


def find_adb() -> str:
    """Return the path of the adb executable."""
    adb = shutil.which("adb")
    if adb is None:
        msg = "adb not found on PATH; install the Android SDK platform-tools"
        raise DeviceError(msg)
    return adb


def choose_device(devices: list[Device], serial: str | None) -> Device:
    """Pick the device to use, or raise DeviceError with advice."""
    listing = "\n".join(
        f"  {d.serial}  model:{d.model or '?'}  state:{d.state}" for d in devices
    )
    if serial:
        chosen = [d for d in devices if d.serial == serial]
        if not chosen:
            msg = f"device {serial} is not attached; attached:\n{listing or '  none'}"
            raise DeviceError(msg)
        device = chosen[0]
    elif not devices:
        msg = (
            "no device attached. Enable USB debugging (Settings > System > "
            "Developer options) and connect the phone, or pair it with wireless "
            "debugging, then check 'adb devices -l'"
        )
        raise DeviceError(msg)
    elif len(devices) > 1:
        msg = f"{len(devices)} devices attached; choose one with --serial:\n{listing}"
        raise DeviceError(msg)
    else:
        device = devices[0]
    if device.state != "device":
        advice = _STATE_ADVICE.get(device.state, "boot the phone into Android")
        msg = f"device {device.serial} is {device.state}: {advice}"
        raise DeviceError(msg)
    return device


@dataclass
class Run:
    """The outcome of one adb invocation."""

    stdout: bytes
    stderr: bytes
    exit_code: int | None  # None when adb could not run or timed out
    seconds: float
    error: str = ""  # why the run counts as failed; empty when it succeeded

    @property
    def ok(self) -> bool:
        """Whether the command ran and produced its output."""
        return not self.error

    def record(self, serial: str) -> dict[str, Any]:
        """Return the manifest fields for this run, without the serial number.

        adb names the serial in errors such as "device '...' not found".
        """
        return {
            "exit_code": self.exit_code,
            "seconds": round(self.seconds, 2),
            "bytes": len(self.stdout),
            "stderr_bytes": len(self.stderr),
            "error": self.error.replace(serial, "<serial>") if serial else self.error,
        }


def _first_line(data: bytes) -> str:
    text = data.decode(errors="replace").strip()
    return text.splitlines()[0][:200] if text else ""


def run_adb(adb: str, args: list[str], timeout: float) -> Run:
    """Run ``adb ARGS`` without stdin and capture its output."""
    start = time.monotonic()
    try:
        proc = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - argv list
            [adb, *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        error = f"timed out after {timeout:g} s; the output may be incomplete"
        stdout, stderr = exc.stdout or b"", exc.stderr or b""
        return Run(stdout, stderr, None, time.monotonic() - start, error)
    except OSError as exc:
        error = f"adb failed: {exc}"
        return Run(b"", b"", None, time.monotonic() - start, error)
    error = ""
    if proc.returncode != 0:
        detail = _first_line(proc.stderr) or _first_line(proc.stdout)
        error = f"exit code {proc.returncode}: {detail}"
    elif not proc.stdout.strip() and proc.stderr.strip():
        error = f"no output: {_first_line(proc.stderr)}"
    seconds = time.monotonic() - start
    return Run(proc.stdout, proc.stderr, proc.returncode, seconds, error)


def run_shell(
    adb: str,
    serial: str,
    command: str,
    timeout: float,
    *,
    adhoc: bool = False,
) -> Run:
    """Check ``command`` and run it with ``adb -s SERIAL shell``.

    A command that fails the read-only checks raises ValueError and never runs.
    """
    if adhoc:
        check_adhoc(command)
    else:
        check_shell(command)
    return run_adb(adb, ["-s", serial, "shell", command], timeout)


def connect(serial: str | None) -> tuple[str, Device]:
    """Find adb and the device to use; raise DeviceError with advice."""
    adb = find_adb()
    listing = run_adb(adb, ["devices", "-l"], timeout=30)
    if listing.exit_code != 0:
        msg = f"'adb devices -l' failed: {listing.error}"
        raise DeviceError(msg)
    devices = parse_devices(listing.stdout.decode(errors="replace"))
    return adb, choose_device(devices, serial)


# ---------------------------------------------------------------- workdir files


def serial_hash(serial: str) -> str:
    """Return a short, stable, non-reversible identifier for a serial number."""
    return hashlib.sha256(serial.encode()).hexdigest()[:12]


def now_iso() -> str:
    """Return the host's local time with its UTC offset."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_json(path: Path, data: object) -> None:
    """Write ``data`` as JSON, replacing ``path`` atomically."""
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", "utf-8")
    tmp.replace(path)


def append_manifest(workdir: Path, key: str, entry: dict[str, Any]) -> None:
    """Append ``entry`` to the list ``key`` of the workdir's manifest.json."""
    path = workdir / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    manifest.setdefault(key, []).append(entry)
    write_json(path, manifest)


def save_output(live_dir: Path, name: str, run: Run) -> Path:
    """Save stdout as ``<name>.txt`` and non-empty stderr as ``<name>.err``."""
    live_dir.mkdir(parents=True, exist_ok=True)
    path = live_dir / f"{name}.txt"
    path.write_bytes(run.stdout)
    if run.stderr.strip():
        (live_dir / f"{name}.err").write_bytes(run.stderr)
    return path
