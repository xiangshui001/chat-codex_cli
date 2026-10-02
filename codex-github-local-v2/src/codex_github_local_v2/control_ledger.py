from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any

from .control import ControlCommand


class LedgerError(RuntimeError):
    pass


def command_fingerprint(command: ControlCommand) -> str:
    payload = json.dumps(
        asdict(command),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class ControlLedger:
    """Persistent replay guard for remote control issues."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _load_all(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "records": {}}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if (
            not isinstance(value, dict)
            or value.get("version") != 1
            or not isinstance(value.get("records"), dict)
        ):
            raise LedgerError("invalid control ledger")
        return value

    def get(self, control_id: str) -> dict[str, Any] | None:
        return self._load_all()["records"].get(control_id)

    def record(
        self,
        command: ControlCommand,
        *,
        outcome: str,
        message: str,
        revision: int,
    ) -> dict[str, Any]:
        data = self._load_all()
        fingerprint = command_fingerprint(command)
        existing = data["records"].get(command.control_id)
        if existing:
            if existing.get("fingerprint") != fingerprint:
                raise LedgerError("control id already exists with a different command fingerprint")
            return existing

        row = {
            "fingerprint": fingerprint,
            "outcome": outcome,
            "message": message,
            "revision": revision,
            "recorded_at": time.time(),
        }
        data["records"][command.control_id] = row
        self._atomic_write(data)
        return row

    def _atomic_write(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        fd, tmp_name = tempfile.mkstemp(
            prefix=self.path.name + ".",
            suffix=".tmp",
            dir=self.path.parent,
        )
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        finally:
            tmp.unlink(missing_ok=True)
