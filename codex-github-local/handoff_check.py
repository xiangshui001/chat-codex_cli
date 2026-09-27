"""Check a small handoff artifact, without network or production/data access."""
from pathlib import Path
import re
import sys


def check(task_id, root):
    if not re.fullmatch(r"GH-[1-9][0-9]*", task_id):
        raise ValueError("Invalid GitHub task ID")
    path = root / "tasks" / task_id / "handoff.md"
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Handoff is outside the worktree")
    value = path.read_text(encoding="utf-8")
    if not 100 <= len(value) <= 30000:
        raise ValueError("Handoff is missing or outside the size limit")
    required = ("任务", "基线", "修改", "检查", "未运行", "风险", "部署")
    missing = [word for word in required if word not in value]
    if missing:
        raise ValueError("Handoff sections missing: " + ", ".join(missing))
    print("PASS: handoff sections present; this check does not certify their claims.")


if __name__ == "__main__":
    try:
        check(sys.argv[1], Path.cwd())
    except (OSError, ValueError, IndexError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
