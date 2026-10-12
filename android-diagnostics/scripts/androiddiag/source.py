"""Read collected data: a workdir of live dumps and/or an Android bugreport zip.

Analyzers never open files themselves. They ask :class:`Sources` for a logical
key from :data:`androiddiag.catalog.SOURCES` and receive a :class:`Text` that
remembers where it came from, so findings can cite ``origin:line``.

A bugreport's main text is ~100 MB with ~1.2 million lines and contains binary
bytes, so it is decoded once with ``errors="replace"`` and indexed by header.

A broken input (a truncated zip, a zip without a dumpstate text, a cut-off
``manifest.json``) never stops the analysis: the input is left out and the
reason is listed in ``Workdir.problems``.
"""

from __future__ import annotations

import fnmatch
import json
import re
import zipfile
import zlib
from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING, Any, TypeVar

from .catalog import SOURCES, Live, Member, Section, Service
from .model import Evidence

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

T = TypeVar("T")

# Evidence excerpts are cut to this many characters.
EXCERPT_CHARS = 200

_TITLED_RE = re.compile(r"^------ (?P<title>.+?) ------$")
_DURATION_TITLE_RE = re.compile(r"^[\d.]+s was the duration of ")
_SERVICE_RE = re.compile(
    r"^DUMP OF SERVICE (?:(?P<prio>CRITICAL|HIGH|NORMAL) )?(?P<name>\S+):$",
)
_SERVICE_END_RE = re.compile(r"^--------- [\d.]+s was the duration of dumpsys ")


@dataclass
class Text:
    """A block of dump text with its origin, for evidence citations."""

    origin: str
    text: str
    first_line: int = 1

    @cached_property
    def lines(self) -> list[str]:
        """The text split into lines."""
        return self.text.splitlines()

    def ref(self, index: int) -> str:
        """Return ``origin:line`` for the zero-based line ``index`` of this text."""
        return f"{self.origin}:{self.first_line + index}"

    def find(self, pattern: str | re.Pattern[str]) -> list[tuple[int, re.Match[str]]]:
        """Return ``(index, match)`` for every line matching ``pattern``."""
        regex = re.compile(pattern) if isinstance(pattern, str) else pattern
        return [
            (i, m) for i, line in enumerate(self.lines) if (m := regex.search(line))
        ]

    def evidence(self, index: int, excerpt: str | None = None) -> Evidence:
        """Cite line ``index``; the excerpt (default: the line) is shortened.

        Whitespace runs collapse to one space and an excerpt longer than
        ``EXCERPT_CHARS`` ends in ``...``.
        """
        raw = self.lines[index] if excerpt is None else excerpt
        short = " ".join(raw.split())
        if len(short) > EXCERPT_CHARS:
            short = short[: EXCERPT_CHARS - 3] + "..."
        return Evidence(self.ref(index), short)


@dataclass
class _Block:
    kind: str  # "section" or "service"
    name: str
    title: str
    start: int  # index of the first body line
    end: int  # index after the last body line


# Errors that opening or reading a damaged, encrypted or exotic zip can raise.
ZIP_ERRORS = (
    zipfile.BadZipFile,
    zlib.error,
    EOFError,
    OSError,
    ValueError,
    NotImplementedError,  # unsupported compression method
    RuntimeError,  # encrypted member
)


# Main text names when main_entry.txt is missing: bugreport-*.txt, or
# dumpstate-*.txt on some Samsung builds (not dumpstate_log.txt).
_MAIN_MEMBER_RE = re.compile(r"^(?:bugreport|dumpstate)(?:-[^/]*)?\.txt$")


def main_member(names: list[str]) -> list[str]:
    """Return the members that may hold the dumpstate main text."""
    return [n for n in names if _MAIN_MEMBER_RE.match(n.rsplit("/", 1)[-1])]


class Bugreport:
    """Random access to the sections, service dumps and files of a bugreport zip."""

    def __init__(self, path: Path) -> None:
        """Open ``path`` lazily; nothing is read until a section is requested.

        Raises ``zipfile.BadZipFile`` (or ``OSError``) when ``path`` is not a
        readable zip.
        """
        self.path = path
        self._zip = zipfile.ZipFile(path)
        self.problems: list[str] = []

    @cached_property
    def main_name(self) -> str:
        """The zip member holding the main dumpstate text.

        Raises ``ValueError`` when the zip has no such member.
        """
        names = self._zip.namelist()
        if "main_entry.txt" in names:
            entry = self._zip.read("main_entry.txt").decode(errors="replace").strip()
            if entry in names:
                return entry
        candidates = main_member(names)
        if not candidates:
            msg = (
                f"{self.path.name}: no main_entry.txt, bugreport-*.txt or "
                "dumpstate-*.txt member"
            )
            raise ValueError(msg)
        return max(candidates, key=lambda n: self._zip.getinfo(n).file_size)

    @cached_property
    def lines(self) -> list[str]:
        """The main text as lines (decoded once, binary bytes replaced).

        A damaged member yields no lines and a note in ``problems``.
        """
        try:
            data = self._zip.read(self.main_name)
        except ZIP_ERRORS as exc:
            self.problems.append(
                f"{self.path.name}: cannot read {self.main_name}: {exc}",
            )
            return []
        return data.decode(errors="replace").splitlines()

    @cached_property
    def _blocks(self) -> list[_Block]:
        blocks: list[_Block] = []
        open_section: _Block | None = None
        open_service: _Block | None = None
        for i, line in enumerate(self.lines):
            if not line.startswith(("------ ", "DUMP OF SERVICE ", "--------- ")):
                continue
            if m := _TITLED_RE.match(line):
                if open_service:
                    open_service.end = i
                    open_service = None
                if open_section:
                    open_section.end = i
                    open_section = None
                title = m["title"]
                if _DURATION_TITLE_RE.match(title):
                    continue
                name = title.split(" (", 1)[0]
                open_section = _Block("section", name, title, i + 1, len(self.lines))
                blocks.append(open_section)
            elif m := _SERVICE_RE.match(line):
                if open_service:
                    open_service.end = i
                open_service = _Block(
                    "service",
                    m["name"],
                    line,
                    i + 1,
                    len(self.lines),
                )
                blocks.append(open_service)
            elif open_service and _SERVICE_END_RE.match(line):
                open_service.end = i
                open_service = None
        return blocks

    def _text(self, block: _Block, label: str) -> Text:
        return Text(
            origin=f"bugreport:{label}",
            text="\n".join(self.lines[block.start : block.end]),
            first_line=block.start + 1,
        )

    def sections(self, title: str) -> list[Text]:
        """Return every ``------ TITLE (...) ------`` section named ``title``."""
        return [
            self._text(b, b.name)
            for b in self._blocks
            if b.kind == "section" and b.name == title
        ]

    def section(self, title: str) -> Text | None:
        """Return the largest section named ``title`` (bugreports repeat some)."""
        found = self.sections(title)
        return max(found, key=lambda t: len(t.text)) if found else None

    def services(self, name: str) -> list[Text]:
        """Return every ``DUMP OF SERVICE`` block for service ``name``."""
        return [
            self._text(b, f"dumpsys {name}")
            for b in self._blocks
            if b.kind == "service" and b.name == name
        ]

    def service(self, name: str) -> Text | None:
        """Return the largest dump of service ``name`` (priorities may split it)."""
        found = [t for t in self.services(name) if t.text.strip()]
        return max(found, key=lambda t: len(t.text)) if found else None

    def member_names(self, pattern: str = "*") -> list[str]:
        """Return zip member names matching the glob ``pattern``."""
        return sorted(n for n in self._zip.namelist() if fnmatch.fnmatch(n, pattern))

    def member(self, name: str) -> Text | None:
        """Return a zip member as text, or None if it is absent or unreadable."""
        try:
            data = self._zip.read(name)
        except KeyError:
            return None
        except ZIP_ERRORS as exc:
            self.problems.append(f"{self.path.name}: cannot read {name}: {exc}")
            return None
        return Text(origin=f"bugreport:{name}", text=data.decode(errors="replace"))

    @cached_property
    def header(self) -> dict[str, str]:
        """The dumpstate header fields (time, build, fingerprint, SDK...)."""
        fields: dict[str, str] = {}
        for line in self.lines[:40]:
            if m := re.match(r"^== dumpstate: (.+)$", line):
                fields["dumpstate_time"] = m[1].strip()
            elif m := re.match(r"^([A-Za-z][A-Za-z ]+): (.+)$", line):
                fields[m[1].strip().lower().replace(" ", "_")] = m[2].strip().strip("'")
        return fields


def is_bugreport_zip(path: Path) -> bool:
    """Return whether ``path`` is a zip with a dumpstate main text."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
    except ZIP_ERRORS:
        return False
    return "main_entry.txt" in names or bool(main_member(names))


@dataclass
class Workdir:
    """A directory written by ``collect.py``: ``live/*.txt``, a bugreport zip.

    The bugreport is ``bugreport*.zip`` or any other ``*.zip`` that holds a
    dumpstate text. ``problems`` lists inputs that could not be used.
    """

    root: Path
    _bugreport: Bugreport | None = field(default=None, init=False, repr=False)
    _opened: bool = field(default=False, init=False, repr=False)
    _problems: list[str] = field(default_factory=list, init=False, repr=False)

    @property
    def live_dir(self) -> Path:
        """The directory holding live dumps."""
        return self.root / "live"

    @property
    def problems(self) -> list[str]:
        """Inputs that were left out, with the reason."""
        found = list(self._problems)
        if self._bugreport is not None:
            found += self._bugreport.problems
        return found

    @cached_property
    def manifest(self) -> dict[str, Any]:
        """The ``manifest.json`` written by ``collect.py``, or an empty dict."""
        path = self.root / "manifest.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._problems.append(f"manifest.json ignored: {exc}")
            return {}
        if not isinstance(data, dict):
            self._problems.append("manifest.json ignored: not a JSON object")
            return {}
        return data

    @cached_property
    def bugreport_path(self) -> Path | None:
        """The bugreport zip inside the workdir, if any.

        ``bugreport*.zip`` is taken by name (a damaged one is reported when
        opened); other zips only when they hold a dumpstate text.
        """
        named = sorted(self.root.glob("bugreport*.zip"))
        if named:
            return named[0]
        others = sorted(p for p in self.root.glob("*.zip") if p.is_file())
        return next((p for p in others if is_bugreport_zip(p)), None)

    @property
    def bugreport(self) -> Bugreport | None:
        """The opened bugreport, or None if there is none or it is unreadable."""
        if not self._opened:
            self._opened = True
            self._bugreport = self._open_bugreport()
        return self._bugreport

    def _open_bugreport(self) -> Bugreport | None:
        path = self.bugreport_path
        if path is None:
            return None
        try:
            bugreport = Bugreport(path)
            _ = bugreport.main_name
        except ZIP_ERRORS as exc:
            self._problems.append(f"bugreport {path.name} ignored: {exc}")
            return None
        return bugreport

    def live(self, key: str) -> Text | None:
        """Return ``live/<key>.txt``, or None if it is missing or empty."""
        path = self.live_dir / f"{key}.txt"
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8", errors="replace")
        return Text(origin=f"live/{key}.txt", text=text) if text.strip() else None


class Sources:
    """Resolve logical input keys to texts, following ``catalog.SOURCES`` order."""

    def __init__(self, workdir: Workdir) -> None:
        """Wrap ``workdir``; lookups are cached per key."""
        self.workdir = workdir
        self._cache: dict[str, Text | None] = {}
        self._memo: dict[str, Any] = {}

    def memo(self, key: str, build: Callable[[], T]) -> T:
        """Return ``build()``, computed once per run and cached under ``key``.

        Use it for parse-once loaders shared by several analyzers; pick a key
        that names the parsed view, such as ``"since_charge"``.
        """
        if key not in self._memo:
            self._memo[key] = build()
        return self._memo[key]

    def get(self, key: str) -> Text | None:
        """Return the first available text for ``key``, or None."""
        if key not in self._cache:
            self._cache[key] = self._resolve(key)
        return self._cache[key]

    def has(self, key: str) -> bool:
        """Return whether ``key`` is available."""
        return self.get(key) is not None

    def members(self, key: str) -> list[Text]:
        """Return every bugreport file matched by a ``Member`` locator of ``key``."""
        br = self.workdir.bugreport
        if br is None:
            return []
        names = [
            name
            for locator in SOURCES.get(key, ())
            if isinstance(locator, Member)
            for name in br.member_names(locator.pattern)
        ]
        return [text for name in names if (text := br.member(name))]

    def _resolve(self, key: str) -> Text | None:
        if key not in SOURCES:
            msg = f"unknown source key {key!r}; add it to catalog.SOURCES"
            raise KeyError(msg)
        br = self.workdir.bugreport
        for locator in SOURCES[key]:
            text: Text | None = None
            if isinstance(locator, Live):
                text = self.workdir.live(locator.key)
            elif br is None:
                continue
            elif isinstance(locator, Section):
                text = br.section(locator.title)
            elif isinstance(locator, Service):
                text = br.service(locator.name)
            elif isinstance(locator, Member):
                found = self.members(key)
                text = found[0] if found else None
            if text is not None and text.text.strip():
                return text
        return None

    def available(self) -> dict[str, str]:
        """Return ``{key: origin}`` for every key that resolves."""
        return {k: t.origin for k in SOURCES if (t := self.get(k))}
