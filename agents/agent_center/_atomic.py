"""
Atomic JSON write + cross-platform file lock helpers.
=====================================================
Used by every state-file consumer (StructuredMemory, ChangeMemory, IssueQueue)
so concurrent dashboard requests cannot corrupt JSON mid-write.

Design:
  - file_lock(path)      → context manager. Holds an OS-level exclusive lock
                           on a sibling .lock file. Works on POSIX (fcntl)
                           and Windows (msvcrt).
  - atomic_write_json    → writes to a temp file in the same directory, fsyncs,
                           then os.replace() (atomic on POSIX; atomic-on-same-
                           volume on Windows since Python 3.3).
  - read_json            → safe read; returns {} on missing/corrupt file.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

# ── Cross-platform lock primitives ────────────────────────────────────────────
if os.name == "nt":
    import msvcrt

    def _lock(fh) -> None:
        # Lock at most 1 byte at offset 0; LK_LOCK blocks until acquired.
        # We retry a few times because msvcrt may raise OSError on contention.
        for _ in range(60):
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
                return
            except OSError:
                import time as _t
                _t.sleep(0.1)
        raise TimeoutError("Could not acquire Windows file lock after 6s")

    def _unlock(fh) -> None:
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def _lock(fh) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)

    def _unlock(fh) -> None:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass


# ── Public API ────────────────────────────────────────────────────────────────

@contextlib.contextmanager
def file_lock(path: str | os.PathLike):
    """
    Acquire an exclusive lock on a sibling ``<path>.lock`` file.

    The actual data file is never opened by this lock; this means readers and
    writers can coordinate without trampling each other's open handles.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")

    # Open in r+/create so we can both lock and reopen safely on Windows.
    fh = open(lock_path, "a+")
    try:
        # Need at least one byte for msvcrt.locking to operate on.
        if fh.tell() == 0:
            fh.write(" ")
            fh.flush()
        fh.seek(0)
        _lock(fh)
        try:
            yield
        finally:
            _unlock(fh)
    finally:
        fh.close()


def atomic_write_json(path: str | os.PathLike, data: Any) -> None:
    """
    Write ``data`` as pretty JSON to ``path`` atomically.

    Strategy: serialise to a NamedTemporaryFile in the same directory (so
    os.replace stays on the same filesystem), fsync, then os.replace().
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    try:
        json.dump(data, tmp, indent=2, ensure_ascii=False, default=str)
        tmp.flush()
        try:
            os.fsync(tmp.fileno())
        except OSError:
            # Some filesystems (e.g. tmpfs in CI) don't support fsync.
            pass
        tmp.close()
        os.replace(tmp.name, path)
    except Exception:
        try:
            os.unlink(tmp.name)
        except FileNotFoundError:
            pass
        raise


def read_json(path: str | os.PathLike, default: Any = None) -> Any:
    """Read a JSON file. Return ``default`` if missing or unreadable."""
    if default is None:
        default = {}
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
