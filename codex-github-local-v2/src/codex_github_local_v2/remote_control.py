from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

from .codex_adapter import CodexProbeRunner
from .control import ControlLedger, ControlProcessor, RuntimeControlService, RuntimeSettingsStore
from .gh_cli import GhCliControlSource
from .locking import AlreadyRunning, single_instance_lock


def build_processor(args) -> ControlProcessor:
    state_dir = Path(args.state_dir).expanduser()
    return ControlProcessor(
        repository=args.repository,
        authorized_users=args.authorized_user,
        source=GhCliControlSource(args.repository, gh_command=tuple(args.gh_command)),
        runtime=RuntimeControlService(
            RuntimeSettingsStore(state_dir / "runtime-settings.json"),
            CodexProbeRunner(tuple(args.codex_command), args.probe_timeout),
        ),
        ledger=ControlLedger(state_dir / "control-ledger.json"),
    )


def run_once(args) -> int:
    result = build_processor(args).tick()
    print(
        json.dumps(
            {
                "status": result.status,
                "issue_number": result.issue_number,
                "message": result.message,
            },
            ensure_ascii=False,
        )
    )
    return int(result.status in {"rejected", "model_unavailable"})


def watch(args) -> int:
    while True:
        try:
            if run_once(args):
                print("control watcher observed a rejected/failed command", file=sys.stderr)
        except KeyboardInterrupt:
            return 130
        except Exception as exc:
            print(f"control watcher error: {type(exc).__name__}: {exc}", file=sys.stderr)
        time.sleep(args.interval)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Prototype GitHub control watcher for codex-github-local v2."
    )
    p.add_argument("--repository", required=True, help="OWNER/REPO")
    p.add_argument("--authorized-user", action="append", required=True)
    p.add_argument("--state-dir", default="~/.local/state/codex-github-local-v2")
    p.add_argument("--gh-command", nargs="+", default=["gh"])
    p.add_argument("--codex-command", nargs="+", default=["codex"])
    p.add_argument("--probe-timeout", type=int, default=90)

    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("run-once")
    w = sub.add_parser("watch")
    w.add_argument("--interval", type=int, default=60)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not 10 <= args.probe_timeout <= 300:
        raise SystemExit("--probe-timeout must be between 10 and 300 seconds")
    if args.command == "watch" and args.interval < 10:
        raise SystemExit("--interval must be at least 10 seconds")

    state_dir = Path(args.state_dir).expanduser()
    try:
        with single_instance_lock(state_dir / "control.lock"):
            return run_once(args) if args.command == "run-once" else watch(args)
    except AlreadyRunning as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
