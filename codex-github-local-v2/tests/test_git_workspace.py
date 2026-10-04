from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_github_local_v2.contract import TaskContract
from codex_github_local_v2.git_workspace import GitWorkspace, GitWorkspaceError
from codex_github_local_v2.policy import HostPolicy, PolicyEngine


def git(cwd, *args):
    return subprocess.check_output(["git", *args], cwd=cwd, text=True, encoding="utf-8").strip()


def task():
    return TaskContract.from_dict(
        {
            "version": 2,
            "repository": "owner/repo",
            "base_sha": "d" * 40,
            "task": {
                "id": "GH-8",
                "type": "documentation",
                "title": "Git fixture",
                "goal": "Write docs.",
                "read_scope": ["**"],
                "write_scope": ["docs/", "tasks/GH-8/"],
                "checks": [],
                "acceptance": ["fixture"],
                "model_policy": {
                    "executor": {
                        "primary": {"name": "runtime-default", "effort": "medium"},
                        "fallbacks": []
                    },
                    "reviewer": {
                        "primary": {"name": "runtime-default", "effort": "high"},
                        "fallbacks": []
                    }
                },
                "budget": {"max_rounds": 1, "max_minutes": 10, "review_rounds": 1},
                "network": "deny",
                "production": "deny",
                "publication": {"mode": "pr", "draft_on_incomplete_validation": True}
            }
        }
    )


class GitWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.repo = root / "repo"
        self.repo.mkdir()
        subprocess.check_call(["git", "init", "-b", "main"], cwd=self.repo, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "config", "user.name", "Fixture"], cwd=self.repo)
        subprocess.check_call(["git", "config", "user.email", "fixture@example.invalid"], cwd=self.repo)
        (self.repo / "README.md").write_text("fixture\n", encoding="utf-8")
        subprocess.check_call(["git", "add", "."], cwd=self.repo)
        subprocess.check_call(["git", "commit", "-m", "base"], cwd=self.repo, stdout=subprocess.DEVNULL)
        self.base = git(self.repo, "rev-parse", "HEAD")
        self.workspace = GitWorkspace(self.repo, root / "worktrees")
        self.policy = PolicyEngine(
            HostPolicy(read_roots=("**",), write_roots=("docs/", "tasks/")),
            task(),
        )

    def test_worktree_changes_are_guarded_and_controller_commits(self):
        self.workspace.assert_clean_base("main", self.base)
        wt = self.workspace.create("GH-8", self.base)
        (wt.path / "docs").mkdir()
        (wt.path / "docs" / "note.md").write_text("hello\n", encoding="utf-8")
        self.assertEqual(self.workspace.guard_changes(wt, self.policy), ["docs/note.md"])
        candidate = self.workspace.commit_candidate(wt, "GH-8: docs fixture")
        self.assertNotEqual(candidate, self.base)
        self.assertEqual(git(wt.path, "rev-parse", "HEAD"), candidate)
        self.assertEqual(git(self.repo, "rev-parse", "main"), self.base)

    def test_out_of_scope_change_is_rejected(self):
        wt = self.workspace.create("GH-8", self.base)
        (wt.path / "app").mkdir()
        (wt.path / "app" / "server.py").write_text("print('x')\n", encoding="utf-8")
        with self.assertRaises(GitWorkspaceError):
            self.workspace.guard_changes(wt, self.policy)


if __name__ == "__main__":
    unittest.main()
