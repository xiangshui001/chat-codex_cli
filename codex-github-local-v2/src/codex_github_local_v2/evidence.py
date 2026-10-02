from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any

_TASK_ID = re.compile(r"^GH-[1-9][0-9]*$")


class EvidenceError(ValueError):
    pass


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    return value


class EvidenceStore:
    """Local-only evidence bundle with atomic JSON writes and append-only events."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def job_dir(self, task_id: str) -> Path:
        if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
            raise EvidenceError("task_id must match GH-N")
        path = self.root / "jobs" / task_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _atomic_bytes(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

    def write_json(self, task_id: str, name: str, value: Any) -> Path:
        if "/" in name or "\\" in name or not name.endswith(".json"):
            raise EvidenceError("evidence JSON name must be a simple .json filename")
        path = self.job_dir(task_id) / name
        payload = json.dumps(_jsonable(value), ensure_ascii=False, indent=2, sort_keys=True)
        self._atomic_bytes(path, (payload + "\n").encode("utf-8"))
        return path

    def write_text(self, task_id: str, name: str, text: str) -> Path:
        if "/" in name or "\\" in name or not name:
            raise EvidenceError("evidence text name must be a simple filename")
        if not isinstance(text, str):
            raise EvidenceError("text must be a string")
        path = self.job_dir(task_id) / name
        self._atomic_bytes(path, text.encode("utf-8"))
        return path

    def append_event(self, task_id: str, event: str, detail: dict[str, Any] | None = None) -> Path:
        if not isinstance(event, str) or not event:
            raise EvidenceError("event must be non-empty")
        path = self.job_dir(task_id) / "events.jsonl"
        row = {
            "at": time.time(),
            "event": event,
            "detail": detail or {},
        }
        line = json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        return path
