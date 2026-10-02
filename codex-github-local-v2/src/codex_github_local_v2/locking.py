from __future__ import annotations

from contextlib import contextmanager
import fcntl
from pathlib import Path
from typing import Iterator


class AlreadyRunning(RuntimeError):
    pass


@contextmanager
def single_instance_lock(path: str | Path) -> Iterator[None]:
    """POSIX advisory lock held for the whole watcher lifetime."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AlreadyRunning("another v2 control watcher already holds the lock") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
