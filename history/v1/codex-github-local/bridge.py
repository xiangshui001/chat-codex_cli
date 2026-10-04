#!/usr/bin/env python3
"""A foreground, single-host GitHub queue for the reviewed local Codex runner.

Tasks are explicit, unedited comments by configured GitHub users. No model is
called to poll. This program never merges a PR or pushes a base branch.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import quote

from engine import runner as core

BUNDLE = Path(__file__).resolve().parent
APP = Path.home() / ".local/state/codex-github-local"
MARKER = "/codex-local run"
REPO_RE = r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
SHA_RE = r"[0-9a-f]{40}"
Halt = core.Halt


def fingerprint(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def shell(argv, cwd=None, body=None):
    """No shell expansion; use the audited process-group timeout handling."""
    p = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE if body is not None else subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        out, err = core.communicate(p, 120, body.encode() if body is not None else None)
    finally:
        p.stdout.close()
        p.stderr.close()
        if p.stdin and not p.stdin.closed:
            p.stdin.close()
    if p.returncode:
        # Do not persist raw external error output: it can contain credentials.
        raise Halt(f"{Path(argv[0]).name} failed (exit {p.returncode}); check connection/authentication locally.")
    return out.decode("utf-8").strip()


class GitHub:
    def api(self, endpoint, method="GET", data=None):
        args = ["gh", "api", "--hostname", "github.com", "--method", method,
                "-H", "Accept: application/vnd.github+json", endpoint]
        if data is not None:
            args += ["--input", "-"]
        value = shell(args, body=json.dumps(data, ensure_ascii=False) if data is not None else None)
        return json.loads(value) if value else None

    def pages(self, endpoint):
        separator = "&" if "?" in endpoint else "?"
        # Bounded pagination fails closed instead of silently dropping tasks.
        result = []
        for page in range(1, 101):
            rows = self.api(f"{endpoint}{separator}per_page=100&page={page}")
            if not isinstance(rows, list):
                raise Halt("Unexpected GitHub list response")
            result.extend(rows)
            if len(rows) < 100:
                return result
        raise Halt("GitHub list exceeds 10,000 records; narrow the queue before continuing")


def parse_task(issue, comments, cfg):
    """Use only one explicit, unchanged approval comment from a trusted user."""
    users = {x.lower() for x in cfg["authorized_users"]}
    if (issue.get("state") != "open" or "pull_request" in issue
            or not issue.get("title", "").startswith("[codex] ")
            or issue.get("user", {}).get("login", "").lower() not in users):
        return None
    marked = [c for c in comments if (c.get("body") or "").splitlines()[:1] == [MARKER]]
    trusted = [c for c in marked if c.get("user", {}).get("login", "").lower() in users]
    if not trusted:
        return None
    if len(trusted) != 1:
        raise Halt("An issue must have exactly one trusted task comment; use a new issue for revisions")
    comment = trusted[0]
    if not comment.get("created_at") or comment.get("created_at") != comment.get("updated_at"):
        raise Halt("Edited task comments are not executable; create a new issue")
    body = comment["body"]
    match = re.fullmatch(r"/codex-local run\r?\n```json\r?\n(.*?)\r?\n```\s*", body, re.S)
    if not match or len(body.encode()) > 40000:
        raise Halt("Task comment must contain exactly one JSON block after /codex-local run")
    envelope = json.loads(match[1])
    if not isinstance(envelope, dict) or set(envelope) != {"version", "repository", "base_sha", "task"}:
        raise Halt("Invalid task envelope")
    if type(envelope["version"]) is not int or envelope["version"] != 1:
        raise Halt("Unsupported task protocol")
    if envelope["repository"] != cfg["repository"] or not re.fullmatch(SHA_RE, str(envelope["base_sha"])):
        raise Halt("Task repository/base SHA mismatch")
    task = envelope["task"]
    if not isinstance(task, dict) or task.get("id") != f"GH-{issue['number']}":
        raise Halt("Task ID must equal GH-<issue number>")
    return {"issue": issue["number"], "comment": comment["id"],
            "comment_sha256": fingerprint(body), "author": comment["user"]["login"],
            "source_base": envelope["base_sha"], "task": task}


class ProjectRunner(core.Runner):
    def __init__(self, config_path, cfg, live_check):
        super().__init__(cfg["root"], control=BUNDLE / "engine", runtime=cfg["runtime"],
                         config_path=config_path, branch_prefix="feature/")
        self.live_check = live_check

    def load_config(self):
        super().load_config()
        if getattr(self, "expected_config_hash", self.config_hash) != self.config_hash:
            raise Halt("Bridge configuration changed after claiming the task")

    def validate(self, task):
        super().validate(task)
        if not re.fullmatch(r"GH-[1-9][0-9]*", task["id"]):
            raise Halt("Only GitHub task IDs are supported")
        for path in task["allowed_paths"]:
            if not any(core.covered(path, root) for root in self.cfg["allowed_roots"]):
                raise Halt("Task requests a path outside local policy: " + path)
        if not set(self.cfg["required_checks"]).issubset(task["checks"]):
            raise Halt("Task omits locally required checks")
        handoff = f"tasks/{task['id']}/handoff.md"
        if not any(core.covered(handoff, p) for p in task["allowed_paths"]):
            raise Halt("Task must allow its own handoff file")
        return task

    def model(self, role, prompt, wt, outdir, attempt):
        self.live_check()
        prompt += ("\n项目交接：先读 docs/START_HERE.md、docs/STATUS.md、docs/CONTROL_PLANE.md。"
                   "本任务只授予任务列出的路径与行为；仓库中别的会话授权不会扩大权限。"
                   "需在 tasks/<任务ID>/handoff.md 写明任务、基线、修改、实际检查、未运行、风险和部署状态。"
                   "不能把自动检查通过写成人工接纳或生产部署。最终候选 SHA 由控制程序写入 PR，"
                   "不用在提交内伪造自引用 SHA。不得读取或复制凭据、真实数据或调用生产服务。")
        result = super().model(role, prompt, wt, outdir, attempt)
        self.live_check()
        return result

    def guard(self, task, wt, base):
        paths = super().guard(task, wt, base)
        for path in paths:
            parts = Path(path).parts
            if any(p in (".git", ".env", "credentials", "secrets") or p.startswith(".env.") for p in parts):
                raise Halt("Credential/configuration path cannot be published")
            target = Path(wt) / path
            if target.is_file():
                raw = target.read_bytes()
                if re.search(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}", raw):
                    raise Halt("Possible credential in a changed file; inspect locally")
        return paths


class Bridge:
    def __init__(self, config_path, api=None):
        self.path = Path(config_path).resolve()
        raw = self.path.read_bytes()
        cfg = json.loads(raw)
        if not isinstance(cfg, dict) or not re.fullmatch(REPO_RE, cfg.get("repository", "")):
            raise Halt("Invalid registered repository")
        for name in ("authorized_users", "allowed_roots", "required_checks"):
            if (not isinstance(cfg.get(name), list) or not cfg[name]
                    or not all(isinstance(x, str) and x for x in cfg[name])):
                raise Halt("Invalid local policy list: " + name)
        for name in ("root", "runtime"):
            if not isinstance(cfg.get(name), str) or not Path(cfg[name]).is_absolute():
                raise Halt("Local policy requires an absolute path: " + name)
        if cfg.get("base_branch") != "main":
            raise Halt("This release supports base branch main")
        for root in cfg["allowed_roots"]:
            if not core.valid_path(root.rstrip("/")):
                raise Halt("Invalid local allowed root")
        self.cfg = cfg
        self.api = api or GitHub()
        self.repo = cfg["repository"]
        self.endpoint = "repos/" + self.repo
        self.r = ProjectRunner(self.path, cfg, self.check_live)
        if (self.r.runtime.is_relative_to(self.r.root) or self.r.control.is_relative_to(self.r.root)
                or self.path.is_relative_to(self.r.root)):
            raise Halt("Bridge configuration, engine and runtime must be outside the business clone")
        self.r.load_config()
        if self.r.config_hash != hashlib.sha256(raw).hexdigest():
            raise Halt("Configuration changed during loading")
        self.r.expected_config_hash = self.r.config_hash
        self.state_path = self.r.runtime / "bridge.json"
        self.state = core.read_json(self.state_path) if self.state_path.exists() else {"current": None, "history": {}}

    @property
    def remote(self):
        return f"https://github.com/{self.repo}.git"

    def git(self, *args):
        return shell(["git", "-c", "core.hooksPath=/dev/null", "-c", "credential.helper=",
                      "-c", "credential.https://github.com.helper=!gh auth git-credential", *args], self.r.root)

    def save(self):
        core.write_json(self.state_path, self.state)

    def remote_head(self):
        result = self.api.api(self.endpoint + "/git/ref/heads/" + quote(self.cfg["base_branch"], safe=""))
        sha = result["object"]["sha"]
        if not re.fullmatch(SHA_RE, sha):
            raise Halt("Invalid remote commit")
        return sha

    def sync_main(self, expected=None):
        self.r.clean_main()
        self.r.assert_config_current()
        self.git("fetch", "--no-tags", self.remote, "refs/heads/" + self.cfg["base_branch"])
        sha = self.git("rev-parse", "FETCH_HEAD")
        if expected is not None and sha != expected:
            raise Halt("main advanced since task approval; create a task against the new base")
        self.git("merge", "--ff-only", sha)
        return sha

    def check_live(self):
        self.r.assert_config_current()
        record = self.state["current"]
        if record["config_sha256"] != self.r.config_hash:
            raise Halt("Claimed task configuration differs from the active configuration")
        issue = self.api.api(f"{self.endpoint}/issues/{record['issue']}")
        comments = self.api.pages(f"{self.endpoint}/issues/{record['issue']}/comments")
        current = parse_task(issue, comments, self.cfg)
        if current is None or any(current[k] != record[k] for k in (
                "issue", "comment", "comment_sha256", "author", "source_base")):
            raise Halt("Task was closed, edited, duplicated or authorization changed")
        if self.remote_head() != record["source_base"]:
            raise Halt("Remote main advanced; old task validation is no longer publishable")

    def verify_candidate(self):
        record = self.state["current"]
        state = self.r.state(record["task"]["id"])
        if state["status"] != "needs_review" or state.get("protocol_version") != 2:
            raise Halt("Only reviewed protocol-v2 candidates can be published")
        if state.get("branch") != "feature/" + record["task"]["id"]:
            raise Halt("Publication is restricted to this task's feature branch")
        if (state.get("base") != record["source_base"] or state.get("config_sha256") != self.r.config_hash
                or record.get("config_sha256") != self.r.config_hash):
            raise Halt("Base/configuration evidence changed")
        task_id = state["id"]
        job = self.r.job(task_id)
        out = self.r.runtime / "outbox" / task_id
        for folder in (job, out):
            if core.digest(folder / "config.snapshot.json") != self.r.config_hash:
                raise Halt("Configuration snapshot changed")
            if core.digest(folder / "task.json") != state["task_sha256"]:
                raise Halt("Task snapshot changed")
        if core.read_json(job / "task.json") != record["task"]:
            raise Halt("Remote task and executed task differ")
        if core.read_json(out / "manifest.json") != state:
            raise Halt("Outbox manifest and controller state differ")
        if (not state.get("checks") or any(c["exit_code"] != 0 or c.get("config_sha256") != self.r.config_hash
                                           for c in state["checks"])):
            raise Halt("Final checks did not pass with this configuration")
        if [c["name"] for c in state["checks"]] != record["task"]["checks"]:
            raise Halt("Final checks do not match the approved task")
        if core.read_json(out / f"checks-{state['attempt']}.json") != state["checks"]:
            raise Halt("Final check artifact changed")
        if state.get("reviewer", {}).get("verdict") != "pass":
            raise Halt("Independent review did not pass")
        if core.read_json(out / f"reviewer-{state['attempt']}.json") != state["reviewer"]:
            raise Halt("Final review artifact changed")
        self.r.ensure_snapshot(Path(state["worktree"]), state["candidate"])
        if self.r.git("rev-parse", state["branch"]) != state["candidate"]:
            raise Halt("Candidate branch changed")
        self.r.guard(record["task"], Path(state["worktree"]), state["base"])
        self.r.assert_config_current()
        return state

    def pr_marker(self):
        record = self.state["current"]
        return f"<!-- codex-local-v1 issue={record['issue']} task={record['comment_sha256']} -->"

    def notify_status(self, stage):
        """Small, idempotent status receipt; never upload prompts or raw logs."""
        record = self.state["current"]
        marker = f"<!-- codex-local-status {record['comment_sha256']} {stage} -->"
        endpoint = f"{self.endpoint}/issues/{record['issue']}/comments"
        comments = self.api.pages(endpoint)
        if any(marker in (c.get("body") or "") and c.get("user", {}).get("login", "").lower()
               in {x.lower() for x in self.cfg["authorized_users"]} for c in comments):
            return
        messages = {"running": "本机已领取，开始执行。", "blocked": "本机执行已停止，不会自动重跑。请检查本机审阅包和状态；修订请使用新 Issue。",
                    "pr_open": "任务已上传 PR，等待人工检查和合并。",
                    "pr_stale": "PR 尚未合并，但 main 已前进。旧检查只对应原候选与原基线，执行端已暂停。请重新比较，必要时关闭本 PR 并创建新任务。"}
        body = marker + "\n\n" + messages[stage] + f"\n\n基线：`{record['source_base']}`"
        if record.get("pr_url"):
            body += "\n\n" + record["pr_url"]
        path = self.r.job(record["task"]["id"]) / "state.json"
        if stage == "blocked" and path.is_file():
            state = core.read_json(path)
            body += f"\n\n轮次：{state['attempt']}；阶段：{state.get('failure_stage', 'interrupted')}。"
            body += "\n" + "\n".join(f"- 检查 `{c['name']}`：退出码 {c['exit_code']}" for c in state.get("checks", []))
        self.api.api(endpoint, "POST", {"body": body})

    def pr_body(self, state):
        record = self.state["current"]
        lines = [self.pr_marker(), f"本地 Codex 已完成任务 #{record['issue']}，待人工检查和合并。",
                 f"任务与授权：https://github.com/{self.repo}/issues/{record['issue']}#issuecomment-{record['comment']}",
                 f"基线：`{state['base']}`", f"候选：`{state['candidate']}`",
                 f"轮次：{state['attempt']}；独立审阅：pass", f"配置 SHA-256：`{state['config_sha256']}`",
                 "\n检查（仅代表列出的检查范围）："]
        lines += [f"- `{c['name']}`：退出码 {c['exit_code']}" for c in state["checks"]]
        lines += [f"\n交接记录：`tasks/{state['id']}/handoff.md`。", "\n变更文件："]
        lines += [f"- `{p}`" for p in state["changed_files"]]
        lines += ["\n自动程序未执行合并或生产部署。请阅读差异与交接记录后决定。",
                  "本版接纳同步支持 GitHub 的 Create a merge commit；squash/rebase 合并后会暂停，需另行核验。",
                  f"\nCloses #{record['issue']}"]
        return "\n\n".join(lines)

    def publish(self):
        state = self.verify_candidate()
        record = self.state["current"]
        if record.get("candidate") not in (None, state["candidate"]):
            raise Halt("Previously recorded candidate changed")
        record["candidate"] = state["candidate"]
        self.save()
        branch = state["branch"]
        owner = self.repo.split("/")[0]
        existing = self.api.pages(f"{self.endpoint}/pulls?state=all&head={quote(owner + ':' + branch, safe='')}")
        if len(existing) > 1:
            raise Halt("Multiple PRs use this task branch")
        if existing:
            pr = self.api.api(f"{self.endpoint}/pulls/{existing[0]['number']}")
            self.validate_pr(pr, state)
        else:
            self.check_live()
            remote_ref = self.git("ls-remote", "--heads", self.remote, "refs/heads/" + branch)
            if remote_ref and remote_ref.split()[0] != state["candidate"]:
                raise Halt("Remote task branch already contains a different candidate")
            self.check_live()
            self.git("push", "--porcelain", self.remote, state["candidate"] + ":refs/heads/" + branch)
            self.check_live()
            pr = self.api.api(self.endpoint + "/pulls", "POST", {
                "title": f"{state['id']}: {record['task']['title']}", "head": branch,
                "base": self.cfg["base_branch"], "body": self.pr_body(state), "draft": False})
            pr = self.api.api(f"{self.endpoint}/pulls/{pr['number']}")
            self.validate_pr(pr, state)
        record.update(stage="pr_open", pr=pr["number"], pr_url=pr["html_url"])
        self.save()
        self.notify_status("pr_open")
        return "PR: " + pr["html_url"]

    def validate_pr(self, pr, state):
        if (pr["head"]["sha"] != state["candidate"] or pr["head"]["ref"] != state["branch"]
                or pr["head"].get("repo", {}).get("full_name") != self.repo
                or pr["base"]["ref"] != self.cfg["base_branch"]
                or pr["base"].get("repo", {}).get("full_name") != self.repo
                or self.pr_marker() not in (pr.get("body") or "")):
            raise Halt("PR identity/head/base/evidence differs from the reviewed candidate")

    def finish(self, stage):
        record = self.state["current"]
        record.update(stage=stage, finished_at=core.now())
        self.state["history"][str(record["issue"])] = record
        self.state["current"] = None
        self.save()
        return stage

    def reconcile(self):
        record = self.state["current"]
        state = self.verify_candidate()
        pr = self.api.api(f"{self.endpoint}/pulls/{record['pr']}")
        self.validate_pr(pr, state)
        if pr.get("merged"):
            # A GitHub merged flag alone is not evidence that this commit landed.
            self.r.clean_main()
            self.git("fetch", "--no-tags", self.remote, "refs/heads/" + self.cfg["base_branch"])
            remote_head = self.git("rev-parse", "FETCH_HEAD")
            self.git("merge-base", "--is-ancestor", state["candidate"], remote_head)
            self.r.assert_config_current()
            self.git("merge", "--ff-only", remote_head)
            self.r.save_state(state, status="accepted", accepted_at=core.now(),
                              reason="已确认人工合并的 GitHub main 包含同一候选提交，并同步本地主分支。",
                              github_pr=pr["number"], remote_main=remote_head,
                              github_merge_commit=pr.get("merge_commit_sha"))
            self.r.report(state)
            return self.finish("accepted")
        if pr.get("state") == "closed":
            self.r.reject(state["id"], "GitHub PR closed without merging; local evidence retained")
            return self.finish("rejected")
        if self.remote_head() != state["base"]:
            self.notify_status("pr_stale")
            raise Halt("main advanced while the PR was open; compare changes before deciding how to proceed")
        self.notify_status("pr_open")
        return "waiting_review"

    def tick(self):
        record = self.state["current"]
        if record:
            stage = record["stage"]
            if stage == "publishing":
                return self.publish()  # Resume upload only; never repeat a model run.
            if stage == "pr_open":
                return self.reconcile()
            if stage in ("claimed", "running"):
                record["stage"] = "blocked"
                record["error"] = "Previous run interrupted; not replaying automatically"
                self.save()
            issue = self.api.api(f"{self.endpoint}/issues/{record['issue']}")
            if issue.get("state") == "closed":
                task_id = record["task"]["id"]
                if (self.r.job(task_id) / "state.json").exists():
                    job = self.r.state(task_id)
                    if job["status"] == "running":
                        self.r.save_state(job, status="blocked", reason="Interrupted; issue later closed")
                    self.r.reject(task_id, "Task issue closed; retain local evidence")
                return self.finish("rejected")
            self.notify_status("blocked")
            raise Halt("Task blocked; inspect local outbox. Close its issue and submit a new issue after fixing the cause")

        issues = self.api.pages(self.endpoint + "/issues?state=open&sort=created&direction=asc")
        for issue in issues:
            if (str(issue["number"]) in self.state["history"] or "pull_request" in issue
                    or not issue.get("title", "").startswith("[codex] ")
                    or issue.get("user", {}).get("login", "").lower() not in {x.lower() for x in self.cfg["authorized_users"]}):
                continue
            comments = self.api.pages(f"{self.endpoint}/issues/{issue['number']}/comments")
            record = parse_task(issue, comments, self.cfg)
            if record is None:
                continue
            record.update(stage="claimed", config_sha256=self.r.config_hash, claimed_at=core.now())
            self.state["current"] = record
            self.save()  # Persist ownership before any model call or workspace creation.
            try:
                self.r.validate(record["task"])
                self.check_live()
                self.sync_main(record["source_base"])
                source = self.r.runtime / "github-task.json"
                core.write_json(source, record["task"])
                self.r.submit(source, refresh=False)
                record["stage"] = "running"
                self.save()
                self.notify_status("running")
                result = self.r.run_once()
                if result != "needs_review":
                    raise Halt("Task blocked before publication; see the local outbox")
                record["stage"] = "publishing"
                self.save()
            except BaseException as exc:
                record["stage"] = "blocked"
                record["error"] = str(exc)
                self.save()
                try:
                    self.notify_status("blocked")
                except (Halt, OSError, ValueError):
                    pass  # Network failure must not erase the local failure evidence.
                raise
            return self.publish()
        return "idle"


@contextlib.contextmanager
def global_lock():
    if os.name != "posix":
        raise Halt("Run this bridge in Ubuntu/WSL, Linux or macOS")
    import fcntl
    APP.mkdir(parents=True, exist_ok=True)
    with (APP / "controller.lock").open("a+") as file:
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Halt("A bridge is already running on this account; use only one instance")
        try:
            yield
        finally:
            fcntl.flock(file, fcntl.LOCK_UN)


def doctor(bridge):
    user = bridge.api.api("user")["login"]
    if user.lower() not in {s.lower() for s in bridge.cfg["authorized_users"]}:
        raise Halt("gh is logged into a different GitHub account")
    repo = bridge.api.api(bridge.endpoint)
    if not repo.get("permissions", {}).get("push"):
        raise Halt("GitHub account lacks repository push permission")
    if not repo.get("has_issues") or repo.get("archived") or repo.get("default_branch") != bridge.cfg["base_branch"]:
        raise Halt("Repository issues/default branch/archived settings do not match local policy")
    result = bridge.r.doctor()
    result.update(repository=bridge.repo, github_user=user, github_main=bridge.remote_head(),
                  allowed_roots=bridge.cfg["allowed_roots"])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("doctor", "status", "run-once"):
        sub.add_parser(name)
    watch = sub.add_parser("watch")
    watch.add_argument("--interval", type=int, default=60)
    args = parser.parse_args(argv)
    try:
        configs = [args.config] if args.config else sorted((APP / "repos").glob("*/config.json"))
        if not configs:
            raise Halt("No registered repositories; run setup.py first")
        if args.command == "status":
            # Atomic JSON snapshots can be inspected while the writer holds its lock.
            for path in configs:
                b = Bridge(path)
                current = b.state["current"]
                value = {"repository": b.repo, "stage": current["stage"] if current else "idle",
                         "issue": current["issue"] if current else None,
                         "pr_url": current.get("pr_url") if current else None,
                         "history": {k: v["stage"] for k, v in b.state["history"].items()}}
                print(json.dumps(value, ensure_ascii=False, indent=2))
            return 0
        with global_lock():
            if args.command == "doctor":
                for path in configs:
                    b = Bridge(path)
                    print(json.dumps(doctor(b), ensure_ascii=False, indent=2))
                return 0
            if args.command == "watch" and args.interval < 30:
                raise Halt("Polling interval must be at least 30 seconds")
            for path in configs:
                doctor(Bridge(path))
            last = {}
            while True:
                # Finish/reconcile existing work before claiming another task anywhere.
                bridges = [Bridge(p) for p in configs]
                active = [b for b in bridges if b.state["current"]]
                if len(active) > 1:
                    raise Halt("Multiple active repositories found; resolve them one at a time with --config")
                for b in active or bridges:
                    result = b.tick()
                    if last.get(b.repo) != result:
                        print(b.repo, result, flush=True)
                        last[b.repo] = result
                    if b.state["current"]:
                        break
                if args.command == "run-once":
                    return 0
                time.sleep(args.interval)
    except (Halt, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        APP.mkdir(parents=True, exist_ok=True)
        evidence = {"status": "blocked", "time": core.now(), "error": str(exc), "type": type(exc).__name__}
        if isinstance(exc, core.ProcessHalt):
            evidence["cleanup"] = exc.cleanup
        core.write_json(APP / "last-error.json", evidence)
        print("blocked: " + str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Stopped. State retained; interrupted model runs will not replay automatically.")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
