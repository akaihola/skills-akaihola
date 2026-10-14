"""Owner-only local capture storage, without changing existing permissions."""

from __future__ import annotations

import os
import stat
import tempfile
from contextlib import suppress
from pathlib import Path

DIRECTORY_MODE = 0o700


def private_directory(path: Path, *, require_private: bool = True) -> None:
    """Create private directories; reject exposed destinations and unsafe links."""
    # resolve() would hide symlinks before the checks below.
    absolute = Path(os.path.abspath(path))  # ruff: ignore[os-path-abspath]
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        with suppress(FileExistsError):
            current.mkdir(mode=DIRECTORY_MODE)
        info = current.lstat()
        if not stat.S_ISDIR(info.st_mode):
            msg = f"capture directory must be a real directory, not a link: {current}"
            raise ValueError(msg)
        if os.name != "posix":
            continue
        if info.st_uid not in {0, os.getuid()}:
            msg = f"capture path has a directory owned by another user: {current}"
            raise ValueError(msg)
        # Shared temporary roots are safe only with sticky deletion protection.
        if info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX:
            msg = f"capture path has a writable parent directory: {current}"
            raise ValueError(msg)
        if (
            require_private
            and current == absolute
            and (
                info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != DIRECTORY_MODE
            )
        ):
            msg = f"capture directory must be owned by you with mode 0700: {current}"
            raise ValueError(msg)


def check_private_file(path: Path) -> None:
    """Reject existing links, shared files and files owned by another user."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        msg = f"capture file must be a regular file with one link: {path}"
        raise ValueError(msg)
    if os.name == "posix" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
        msg = f"capture file must be owned by you with owner-only permissions: {path}"
        raise ValueError(msg)


def write_private(path: Path, data: bytes) -> None:
    """Atomically write data through an owner-only temporary file."""
    private_directory(path.parent)
    check_private_file(path)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
