"""Controller-owned acceptance examples, run against the candidate worktree.

These assertions validate only this demonstrator's explicitly scoped contract.
"""
import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location("candidate_query_parser", Path.cwd() / "src/query_parser.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
cases = [
    ("双音节动词", {"syllable_count": 2, "pos": "verb"}, ""),
    ("双音节单义动词", {"syllable_count": 2, "pos": "verb", "sense_count": 1}, ""),
    ("三音节名词", {"syllable_count": 3, "pos": "noun"}, ""),
    ("", {}, ""),
    ("表达悲伤的词", {}, "表达悲伤的词"),
    ("花儿", {}, "花儿"),
]
for text, filters, semantic_query in cases:
    actual = module.parse_query(text)
    expected = {"filters": filters, "semantic_query": semantic_query}
    if actual != expected:
        raise AssertionError(f"{text!r}: expected {expected!r}, got {actual!r}")
try:
    module.parse_query(None)
except TypeError:
    pass
else:
    raise AssertionError("None 必须触发 TypeError")
print(f"PASS: {len(cases) + 1} acceptance cases")
