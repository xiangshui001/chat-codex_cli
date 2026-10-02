from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .contract import ContractError, TaskContract


def load_contract(path: str) -> TaskContract:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return TaskContract.from_dict(data)


def cmd_validate(path: str) -> int:
    task = load_contract(path)
    print(
        json.dumps(
            {
                "ok": True,
                "version": task.version,
                "repository": task.repository,
                "task_id": task.task_id,
                "type": task.task_type,
                "read_scope": list(task.read_scope),
                "write_scope": list(task.write_scope),
                "max_rounds": task.budget.max_rounds,
                "max_minutes": task.budget.max_minutes,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_explain(path: str) -> int:
    task = load_contract(path)
    print(f"{task.task_id}: {task.title}")
    print(f"type: {task.task_type}")
    print(f"repository: {task.repository}@{task.base_sha[:12]}")
    print("read: " + ", ".join(task.read_scope))
    print("write: " + (", ".join(task.write_scope) if task.write_scope else "(none)"))
    print(
        "executor: "
        + f"{task.model_policy.executor.primary.name}/{task.model_policy.executor.primary.effort}"
    )
    print(
        "reviewer: "
        + f"{task.model_policy.reviewer.primary.name}/{task.model_policy.reviewer.primary.effort}"
    )
    print(
        f"budget: {task.budget.max_rounds} rounds, {task.budget.max_minutes} minutes, "
        + f"{task.budget.review_rounds} review rounds"
    )
    print(f"network={task.network}; production={task.production}; publication={task.publication.mode}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the v2 prototype task contract.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "explain"):
        command = sub.add_parser(name)
        command.add_argument("task_json")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            return cmd_validate(args.task_json)
        return cmd_explain(args.task_json)
    except (OSError, json.JSONDecodeError, ContractError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
