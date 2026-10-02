from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

from .codex_probe import CodexProbeRunner
from .control_ledger import ControlLedger
from .control_processor import ControlProcessor
from .gh_cli import GhCliControlSource
from .runtime_settings import RuntimeControlService, RuntimeSettingsStore


def build_processor(args) -> ControlProcessor:
    state_dir = Path(args.state_dir).expanduser()
    source = GhCliControlSource(
        args.repository,
        gh_command=tuple(args.gh_command),
    )
    store = RuntimeSettingsStore(state_dir / "runtime-settings.json")
    ledger = ControlLedger(state_dir / "control-ledger.json")
    probe = CodexProbeRunner(
        codex_command=tuple(args.codex_command),
        timeout_seconds=args.probe_timeout,
    )
    runtime = RuntimeControlService(store, probe)
    return ControlProcessor(
        repository=args.repository,
        authorized_users=args.authorized_user,
        source=source,
        runtime=runtime,
        ledger=ledger,
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
    return 1 if result.status in {"rejected", "model_unavailable"} else 0


def watch(args) -> int:
    while True:
        try:
            code = run_once(args)
            if code:
                print("control watcher observed a rejected/failed command", file=sys.stderr)
        except KeyboardInterrupt:
            return 130
        except Exception as exc:
            # A transient GitHub/CLI failure must not mutate runtime settings.
            print(f"control watcher error: {type(exc).__name__}: {exc}", file=sys.stderr)
        time.sleep(args.interval)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Prototype GitHub control watcher for codex-github-local v2."
    )
    p.add_argument("--repository", required=True, help="OWNER/REPO")
    p.add_argument(
        "--authorized-user",
        action="append",
        required=True,
        help="GitHub login allowed to issue control commands; repeatable",
    )
    p.add_argument(
        "--state-dir",
        default="~/.local/state/codex-github-local-v2",
    )
    p.add_argument(
        "--gh-command",
        nargs="+",
        default=["gh"],
    )
    p.add_argument(
        "--codex-command",
        nargs="+",
        default=["codex"],
    )
    p.add_argument("--probe-timeout", type=int, default=90)

    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("run-once")
    w = sub.add_parser("watch")
    w.add_argument("--interval", type=int, default=60)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.probe_timeout < 10 or args.probe_timeout > 300:
        raise SystemExit("--probe-timeout must be between 10 and 300 seconds")
    if args.command == "run-once":
        return run_once(args)
    if args.interval < 10:
        raise SystemExit("--interval must be at least 10 seconds")
    return watch(args)


if __name__ == "__main__":
    raise SystemExit(main())
