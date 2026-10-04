"""Explicit, offline schema 1 -> 2 migration with operator reconciliation.

Schema 1 cannot tell whether a receipt was delivered or reconstruct its settings.
Every old row therefore requires evidence. No watcher invokes this function.
"""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable

from .control import (
    ControlLedger, LedgerError, RuntimeSettingsError, _atomic_json,
    _settings_from_dict, status_receipt,
)
from .github_protocol import CommentView
from .locking import single_instance_lock


@dataclass(frozen=True)
class MigrationResult:
    status: str
    records: int
    backup: Path | None = None


def _convert(control_id: str, old: Any, evidence: Any, users: tuple[str, ...]):
    fields = {"fingerprint", "outcome", "message", "revision", "recorded_at"}
    if not isinstance(old, dict) or set(old) != fields:
        raise LedgerError(f"invalid schema 1 record: {control_id}")
    fingerprint = old["fingerprint"]
    if (not isinstance(fingerprint, str) or len(fingerprint) != 64
            or any(c not in "0123456789abcdef" for c in fingerprint)):
        raise LedgerError(f"invalid fingerprint: {control_id}")
    if (not control_id.startswith("GH-") or not control_id[3:].isdigit()
            or int(control_id[3:]) < 1):
        raise LedgerError("invalid legacy control ID")
    if (old["outcome"] not in ("applied", "model_unavailable")
            or not isinstance(old["message"], str)
            or type(old["revision"]) is not int or old["revision"] < 0
            or type(old["recorded_at"]) not in (float, int)
            or not math.isfinite(old["recorded_at"])):
        raise LedgerError(f"invalid legacy result: {control_id}")
    if not isinstance(evidence, dict) or set(evidence) != {"settings", "receipt_comment"}:
        raise LedgerError(f"settings and receipt_comment reconciliation required: {control_id}")
    snapshot = evidence["settings"]
    if (not isinstance(snapshot, dict)
            or set(snapshot) != {"paused", "executor", "reviewer", "revision", "last_control_id"}
            or any(not isinstance(snapshot[role], dict) or set(snapshot[role]) != {"model", "effort"}
                   for role in ("executor", "reviewer"))):
        raise LedgerError(f"complete historical settings required: {control_id}")
    try:
        settings = _settings_from_dict(snapshot)
    except RuntimeSettingsError as exc:
        raise LedgerError(f"invalid historical settings: {control_id}") from exc
    if settings.revision != old["revision"]:
        raise LedgerError(f"historical revision mismatch: {control_id}")
    if old["outcome"] == "applied" and settings.last_control_id != control_id:
        raise LedgerError(f"historical applied identity mismatch: {control_id}")
    legacy_body = status_receipt(settings, outcome=old["outcome"], message=old["message"])
    delivered_at = None
    proof = evidence["receipt_comment"]
    if proof is not None:
        try:
            comment = CommentView(**proof)
            if (type(comment.comment_id) is not int or comment.comment_id < 1
                    or comment.author not in users
                    or comment.created_at != comment.updated_at or comment.body != legacy_body):
                raise ValueError("receipt does not match historical result or authorized author")
            timestamp = datetime.fromisoformat(comment.created_at.replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("receipt timestamp needs timezone")
            delivered_at = timestamp.timestamp()
        except (TypeError, ValueError, AttributeError) as exc:
            raise LedgerError(f"invalid receipt evidence: {control_id}") from exc
    row = {
        **old, "issue_number": int(control_id[3:]),
        "receipt": f"<!-- codex-local-control {control_id} {fingerprint} -->\n" + legacy_body,
        "delivered_at": delivered_at,
    }
    if not ControlLedger._valid_row(control_id, row):
        raise LedgerError(f"migration produced an invalid record: {control_id}")
    return row


def migrate_control_ledger(
    path: str | Path, reconciliation: dict[str, Any], *, authorized_users: Iterable[str],
) -> MigrationResult:
    """Back up exact bytes, validate all rows, then atomically replace in place.

    receipt_comment=null explicitly declares delivery unconfirmed; the operator
    supplies the historical settings. A matching authorized immutable comment
    proves delivery. Re-running on valid schema 2 is a read-only no-op.
    """
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise LedgerError("migration requires a regular existing ledger")
    with single_instance_lock(path.parent / "control.lock"):
        original = path.read_bytes()
        try:
            data = json.loads(original)
        except (ValueError, UnicodeDecodeError) as exc:
            raise LedgerError("ledger is not valid JSON") from exc
        if not isinstance(data, dict) or set(data) != {"version", "records"}:
            raise LedgerError("invalid ledger envelope")
        if type(data["version"]) is not int:
            raise LedgerError("invalid schema version")
        if data["version"] == 2:
            rows = ControlLedger(path)._load()["records"]
            return MigrationResult("already_migrated", len(rows))
        if data["version"] != 1 or not isinstance(data["records"], dict):
            raise LedgerError("unsupported ledger schema")
        if not isinstance(reconciliation, dict) or set(reconciliation) != set(data["records"]):
            raise LedgerError("reconciliation must cover exactly all legacy control IDs")
        users = tuple(authorized_users)
        converted = {key: _convert(key, row, reconciliation[key], users)
                     for key, row in data["records"].items()}
        backup = path.with_name(path.name + ".schema1." + hashlib.sha256(original).hexdigest() + ".bak")
        if backup.exists():
            if backup.is_symlink() or backup.read_bytes() != original:
                raise LedgerError("existing backup differs; refusing to overwrite")
        else:
            fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(original)
                handle.flush()
                os.fsync(handle.fileno())
        # The advisory lock coordinates with v2 watchers; also detect an external edit.
        if path.read_bytes() != original:
            raise LedgerError("ledger changed during migration; old data preserved")
        _atomic_json(path, {"version": 2, "records": converted})
        return MigrationResult("migrated", len(converted), backup)
