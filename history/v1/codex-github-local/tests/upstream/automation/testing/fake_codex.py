"""Offline test double. Never used by the distributed default configuration."""
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
if args == ["--version"]:
    print("offline-test-double")
elif args == ["exec", "--help"]:
    print("--json --output-schema --output-last-message --sandbox")
elif args == ["login", "status"]:
    print("Logged in using ChatGPT (offline test double)")
else:
    sys.stdin.read()
    output = Path(args[args.index("--output-last-message") + 1])
    mode = os.environ.get("COLLAB_TEST_MODE", "ok")
    attempt = int(output.stem.split("-")[-1])
    worker = output.name.startswith("worker")
    if mode == "exit_error":
        raise SystemExit(9)
    if worker:
        if mode == "protected":
            Path("AGENTS.md").write_text("unauthorized change", encoding="utf-8")
        broken = mode == "always_fail" or (mode == "repair_once" and attempt == 1)
        code = '''def parse_query(text):
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    cases = {
        "双音节动词": {"syllable_count": 2, "pos": "verb"},
        "双音节单义动词": {"syllable_count": 2, "pos": "verb", "sense_count": 1},
        "三音节名词": {"syllable_count": 3, "pos": "noun"}
    }
    return {"filters": cases.get(text, {}), "semantic_query": "" if text in cases else text}
'''
        if broken:
            code = "def parse_query(text):\n    return None\n"
        code += "\n# Offline fixture for " + output.parent.name + "\n"
        Path("src/query_parser.py").write_text(code, encoding="utf-8")
        result = {"status": "completed", "summary": "Offline fixture changed candidate.",
                  "issues": [], "evidence": ["src/query_parser.py"]}
    else:
        verdict = "revise" if mode == "review_revise" and attempt == 1 else "pass"
        result = {"verdict": verdict, "summary": "Offline review fixture.",
                  "issues": ["test fixture asks for revision"] if verdict == "revise" else [],
                  "evidence": ["fixture"]}
        if mode == "invalid_review":
            result = {"verdict": "pass"}
    output.write_text(json.dumps(result), encoding="utf-8")
    print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 0, "output_tokens": 0}}))
