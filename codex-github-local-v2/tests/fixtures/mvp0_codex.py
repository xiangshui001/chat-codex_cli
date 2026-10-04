"""OFFLINE subprocess fixture, never evidence of real Codex/model execution."""
import json
from pathlib import Path
import subprocess
import sys
import time

if "--version" in sys.argv:
    print("offline-codex-fixture 1")
    raise SystemExit(0)

mode = sys.argv[1]
prompt = sys.stdin.read()
Path("received-prompt.txt").write_text(prompt, encoding="utf-8")
print("fixture stderr only", file=sys.stderr, flush=True)
print(json.dumps({"type": "thread.started", "thread_id": "offline"}), flush=True)
if mode == "timeout":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    Path("child.pid").write_text(str(child.pid))
    time.sleep(60)
if mode == "flood":
    print("x" * 100000, flush=True)
if mode == "invalid":
    print("not JSON")
print(json.dumps({"type": "item.completed", "item": {"type": "command_execution"}}))
if mode == "failure":
    print(json.dumps({"type": "turn.failed"}))
    raise SystemExit(7)
if mode != "item_only":
    print(json.dumps({"type": "turn.completed"}))
