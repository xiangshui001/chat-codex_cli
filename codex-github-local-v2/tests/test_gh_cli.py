from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_github_local_v2.gh_cli import GhCliControlSource


class GhCliAdapterTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def runner(argv):
            self.calls.append(argv)
            if argv[1:3] == ["issue", "list"]:
                return json.dumps(
                    [
                        {
                            "number": 43,
                            "title": "[codex-control] pause",
                            "state": "OPEN",
                            "author": {"login": "owner"},
                        },
                        {
                            "number": 44,
                            "title": "[codex] ordinary task",
                            "state": "OPEN",
                            "author": {"login": "owner"},
                        },
                    ]
                )
            if "comments?per_page=100" in argv[-1]:
                return json.dumps(
                    [
                        {
                            "id": 100,
                            "user": {"login": "owner"},
                            "created_at": "2026-10-02T00:00:00Z",
                            "updated_at": "2026-10-02T00:00:00Z",
                            "body": "/codex-local control\\n~~~json\\n{}\\n~~~",
                        }
                    ]
                )
            if "--method" in argv:
                return json.dumps({"id": 101})
            raise AssertionError(argv)

        self.source = GhCliControlSource(
            "owner/repo",
            gh_command=("gh",),
            runner=runner,
        )

    def test_filters_only_control_issues(self):
        issues = self.source.list_open_control_issues()
        self.assertEqual([issue.number for issue in issues], [43])
        self.assertEqual(issues[0].state, "open")

    def test_maps_comments(self):
        comments = self.source.list_comments(43)
        self.assertEqual(comments[0].author, "owner")
        self.assertEqual(comments[0].comment_id, 100)

    def test_posts_receipt_through_issue_comments_api(self):
        self.source.post_comment(43, "applied")
        call = self.calls[-1]
        self.assertIn("--method", call)
        self.assertIn("POST", call)
        self.assertTrue(any(value == "body=applied" for value in call))

    def test_comments_beyond_first_page_are_available_for_receipt_recovery(self):
        first = {"id": 1, "user": {"login": "owner"}, "created_at": "now",
                 "updated_at": "now", "body": "discussion"}
        pages = []

        def runner(argv):
            pages.append(argv[-1])
            if argv[-1].endswith("page=1"):
                return json.dumps([first] * 100)
            if argv[-1].endswith("page=2"):
                return json.dumps([{**first, "id": 101, "body": "receipt"}])
            raise AssertionError(argv)

        source = GhCliControlSource("owner/repo", runner=runner)
        self.assertEqual(source.list_comments(43)[-1].body, "receipt")
        self.assertEqual(len(pages), 2)


if __name__ == "__main__":
    unittest.main()
