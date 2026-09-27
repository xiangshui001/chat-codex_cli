#!/usr/bin/env python3
"""A local, serial Codex task queue. Python 3.10+, Git, Linux/WSL/macOS.

Only the controller changes task state, creates commits and accepts results.
Model output is evidence, never authorization or a state transition command.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import uuid


class Halt(RuntimeError):
    pass


class ProcessHalt(Halt):
    def __init__(self, message, cleanup):
        super().__init__(message)
        self.cleanup = cleanup


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def atomic_bytes(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    tmp.write_bytes(content)
    os.replace(tmp, path)


def atomic_text(path, text):
    atomic_bytes(path, text.encode("utf-8"))


def write_json(path, value):
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def command(argv, cwd, include_stderr=False):
    p = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = communicate(p, timeout=45)
    finally:
        p.stdout.close()
        p.stderr.close()
    if p.returncode:
        raise Halt(stderr.decode("utf-8", "replace")[-3000:] or str(argv))
    output = stdout + stderr if include_stderr else stdout
    return output.decode("utf-8", "replace").rstrip("\n")


def terminate_group(p, grace_seconds=3.0, kill_wait_seconds=3.0):
    """Bounded cleanup of a group created with start_new_session=True.

    The leader exiting is not proof that its process group disappeared.
    A still-detectable group (including unreaped zombies) is reported honestly.
    Processes that deliberately leave the group require stronger containment.
    """
    result = {"pgid": p.pid, "term_sent": False, "kill_sent": False,
              "group_absent": False, "leader_returncode": None, "errors": []}
    if p.pid <= 1 or p.pid == os.getpgrp():
        result["errors"].append("Refusing to signal an unsafe process group.")
        result["confirmed"] = False
        return result

    def present():
        try:
            os.killpg(p.pid, 0)
            return True
        except ProcessLookupError:
            return False
        except OSError as exc:
            message = type(exc).__name__ + ": " + str(exc)
            if message not in result["errors"]:
                result["errors"].append(message)
            return True  # Unknown is not evidence of successful cleanup.

    def send(sig, key):
        try:
            os.killpg(p.pid, sig)
            result[key] = True
        except ProcessLookupError:
            pass
        except OSError as exc:
            result["errors"].append(type(exc).__name__ + ": " + str(exc))

    def wait_group(seconds):
        deadline = time.monotonic() + seconds
        while True:
            p.poll()  # Reap the leader, but keep checking its entire group.
            if not present():
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.05, remaining))

    send(signal.SIGTERM, "term_sent")
    gone = wait_group(grace_seconds)
    if not gone:
        send(signal.SIGKILL, "kill_sent")
        gone = wait_group(kill_wait_seconds)
    result["group_absent"] = gone
    result["leader_returncode"] = p.poll()
    result["confirmed"] = gone and p.returncode is not None
    return result


def communicate(p, timeout, prompt=None):
    try:
        return p.communicate(prompt, timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        cleanup = terminate_group(p)
        cleanup["trigger"] = "timeout" if isinstance(exc, subprocess.TimeoutExpired) else "interrupt"
        reason = "运行超时" if cleanup["trigger"] == "timeout" else "用户中断"
        if cleanup["confirmed"]:
            reason += "；已确认原进程组消失，主进程已回收。"
        else:
            reason += "；已尝试清理，但无法确认原进程组全部停止，请检查清理记录。"
        raise ProcessHalt(reason, cleanup) from exc


def logged_process(argv, cwd, stem, timeout, prompt=None):
    """No shell interpolation. Logs are streamed to disk, not held in RAM."""
    stem = Path(stem)
    with stem.with_suffix(".stdout.log").open("wb") as out, \
         stem.with_suffix(".stderr.log").open("wb") as err:
        p = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE,
                             stdout=out, stderr=err, start_new_session=True)
        try:
            communicate(p, timeout, None if prompt is None else prompt.encode("utf-8"))
        except ProcessHalt as exc:
            write_json(stem.with_suffix(".cleanup.json"), exc.cleanup)
            raise
        finally:
            if p.stdin and not p.stdin.closed:
                p.stdin.close()
    return p.returncode


def valid_path(path):
    return (isinstance(path, str) and bool(path) and "\\" not in path
            and not path.startswith("/") and ":" not in path
            and all(p not in ("", ".", "..") for p in path.split("/"))
            and not any(ord(c) < 32 for c in path))


def covered(path, pattern):
    return path.startswith(pattern) if pattern.endswith("/") else path == pattern


class Runner:
    def __init__(self, root, *, control=None, runtime=None, config_path=None, branch_prefix="task/"):
        self.root = Path(root).resolve()
        self.control = Path(control).resolve() if control else self.root / "automation"
        self.config_path = Path(config_path).resolve() if config_path else self.control / "config.json"
        self.branch_prefix = branch_prefix
        self.cfg = None
        self.config_bytes = None
        self.config_hash = None
        self.runtime = Path(runtime).resolve() if runtime else self.root / "runtime"
        for name in ("jobs", "inbox", "outbox", "worktrees"):
            (self.runtime / name).mkdir(parents=True, exist_ok=True)

    def load_config(self):
        """Parse and hash the same read; refresh only at command/task boundaries."""
        content = self.config_path.read_bytes()
        cfg = json.loads(content)
        required = {"base_branch", "codex_command", "max_attempts", "model_timeout_seconds",
                    "max_changed_files", "max_file_bytes", "protected_paths", "roles", "checks"}
        if not isinstance(cfg, dict) or not required.issubset(cfg):
            raise Halt("配置缺少必需字段。")
        if not isinstance(cfg["base_branch"], str) or not cfg["base_branch"]:
            raise Halt("base_branch 必须是非空字符串。")
        for name in ("max_attempts", "max_changed_files", "max_file_bytes"):
            if type(cfg[name]) is not int or cfg[name] < 1:
                raise Halt(name + " 必须是正整数。")
        def positive_timeout(value):
            return type(value) in (int, float) and math.isfinite(value) and value > 0
        def argv_ok(value):
            return isinstance(value, list) and bool(value) and all(isinstance(x, str) and x for x in value)
        if not argv_ok(cfg["codex_command"]) or not positive_timeout(cfg["model_timeout_seconds"]):
            raise Halt("Codex 命令或超时配置无效。")
        if (not isinstance(cfg["protected_paths"], list) or
                not all(isinstance(x, str) and valid_path(x.rstrip("/")) for x in cfg["protected_paths"])):
            raise Halt("protected_paths 配置无效。")
        if not isinstance(cfg["roles"], dict):
            raise Halt("roles 配置无效。")
        for role in ("worker", "reviewer"):
            settings = cfg["roles"].get(role)
            if not isinstance(settings, dict) or any(
                    settings.get(k) is not None and not isinstance(settings[k], str)
                    for k in ("model", "reasoning_effort")):
                raise Halt(role + " 角色配置无效。")
        if not isinstance(cfg["checks"], dict) or not cfg["checks"]:
            raise Halt("必须配置至少一项检查。")
        for name, check in cfg["checks"].items():
            if (not re.fullmatch(r"[A-Za-z0-9_-]+", name) or not isinstance(check, dict)
                    or not argv_ok(check.get("argv")) or not positive_timeout(check.get("timeout_seconds"))):
                raise Halt("检查配置无效：" + name)
        self.cfg = cfg
        self.config_bytes = content
        self.config_hash = hashlib.sha256(content).hexdigest()

    def assert_config_current(self):
        if digest(self.config_path) != self.config_hash:
            raise Halt("本次任务期间控制配置发生变化，已停止；请按新配置重新提交任务。")

    def freeze_config(self, state):
        self.save_state(state, protocol_version=2, config_sha256=self.config_hash)
        for directory in (self.job(state["id"]), self.runtime / "outbox" / state["id"]):
            atomic_bytes(directory / "config.snapshot.json", self.config_bytes)

    def scheduler_status(self, status, reason="", stage=None, task_id=None, error=None):
        value = {"status": status, "reason": reason, "stage": stage,
                 "task_id": task_id, "updated_at": now()}
        if error is not None:
            value["error_type"] = type(error).__name__
            if isinstance(error, ProcessHalt):
                value["cleanup"] = error.cleanup
        write_json(self.runtime / "scheduler.json", value)
        atomic_text(self.runtime / "outbox" / "scheduler.md",
                    f"# 调度器状态\n\n状态：{status}\n\n阶段：{stage}\n\n原因：{reason}\n")

    def preflight_failed(self, state, exc):
        reason = "启动预检失败：" + type(exc).__name__ + ": " + str(exc)
        self.save_state(state, status="blocked", failure_stage="preflight", reason=reason)
        self.scheduler_status("blocked", reason, "preflight", state["id"], exc)
        evidence = {"error_type": type(exc).__name__, "reason": str(exc), "time": now()}
        if isinstance(exc, ProcessHalt):
            evidence["cleanup"] = exc.cleanup
        write_json(self.runtime / "outbox" / state["id"] / "preflight.json", evidence)
        self.report(state)

    def git(self, *args, cwd=None):
        return command(["git", *args], cwd or self.root)

    @contextlib.contextmanager
    def lock(self):
        if os.name != "posix":
            raise Halt("此启动版运行在 Linux/WSL/macOS；Windows 请在 WSL 中启动。")
        import fcntl
        with (self.runtime / "controller.lock").open("a+") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Halt("已有调度器正在处理任务；等待当前任务完成或先停止它。")
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def job(self, task_id):
        if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", task_id):
            raise Halt("任务 ID 只允许 1–64 位字母、数字、下划线或连字符。")
        return self.runtime / "jobs" / task_id

    def jobs(self):
        return sorted((read_json(p) for p in (self.runtime / "jobs").glob("*/state.json")),
                      key=lambda s: (s["submitted_at"], s["id"]))

    def state(self, task_id):
        return read_json(self.job(task_id) / "state.json")

    def save_state(self, state, **updates):
        state.update(updates, updated_at=now())
        write_json(self.job(state["id"]) / "state.json", state)

    def validate(self, task):
        expected = {"id", "title", "goal", "inputs", "allowed_paths", "checks",
                    "acceptance", "depends_on", "context"}
        if not isinstance(task, dict) or set(task) != expected:
            raise Halt("任务字段必须与 automation/examples/DICT-001.json 完全一致。")
        self.job(task["id"])
        for key in ("title", "goal", "context"):
            if not isinstance(task[key], str) or len(task[key]) > 30000:
                raise Halt("任务文本无效或过长：" + key)
        if not task["title"].strip() or not task["goal"].strip():
            raise Halt("title 与 goal 不能为空。")
        for key in ("inputs", "allowed_paths", "checks", "acceptance", "depends_on"):
            if not isinstance(task[key], list) or not all(isinstance(x, str) and x for x in task[key]):
                raise Halt("任务列表无效：" + key)
        if not all(task[k] for k in ("allowed_paths", "checks", "acceptance")):
            raise Halt("必须提供可改路径、检查项与验收条件。")
        for p in task["inputs"] + task["allowed_paths"]:
            if not valid_path(p.rstrip("/")):
                raise Halt("无效相对路径：" + p)
        if len(task["inputs"]) > 8:
            raise Halt("最多显式提供 8 个上下文文件；其余由执行器按需读取。")
        for check in task["checks"]:
            if check not in self.cfg["checks"]:
                raise Halt("检查项未注册：" + check)
        for dep in task["depends_on"]:
            if dep == task["id"] or not (self.job(dep) / "state.json").exists():
                raise Halt("依赖必须是已入队任务，不能自引用：" + dep)
        return task

    def submit(self, task_path, refresh=True):
        if refresh:
            self.load_config()
        task = self.validate(read_json(task_path))
        directory = self.job(task["id"])
        try:
            directory.mkdir()
        except FileExistsError:
            raise Halt("该任务 ID 已存在；不会重复执行，请使用新 ID 提交修订任务。")
        write_json(directory / "task.json", task)
        stamp = now()
        write_json(directory / "state.json", {"id": task["id"], "status": "queued",
                   "submitted_at": stamp, "updated_at": stamp, "attempt": 0,
                   "task_sha256": digest(directory / "task.json")})
        return task["id"]

    def ingest(self):
        for path in sorted((self.runtime / "inbox").glob("*.ready.json")):
            try:
                self.submit(path, refresh=False)
                path.rename(path.with_suffix(".ingested"))
            except (Halt, ValueError, OSError) as exc:
                write_json(path.with_suffix(".error.json"), {"error": str(exc), "time": now()})
                path.rename(path.with_suffix(".rejected"))

    def clean_main(self):
        if self.git("branch", "--show-current") != self.cfg["base_branch"]:
            raise Halt("主工作目录须位于配置的 base_branch。")
        if self.git("status", "--porcelain", "--untracked-files=normal"):
            raise Halt("主工作目录有未提交改动，请先形成一个可复现的提交。")
        self.git("rev-parse", "HEAD")

    def doctor(self, refresh=True):
        if refresh:
            self.load_config()
        self.clean_main()
        if any(os.environ.get(k) for k in ("OPENAI_API_KEY", "CODEX_API_KEY")):
            raise Halt("当前有 API key 环境变量；本方案要求 ChatGPT 登录，请先自行确认并移除冲突。")
        prefix = self.cfg["codex_command"]
        version = command(prefix + ["--version"], self.root)
        help_text = command(prefix + ["exec", "--help"], self.root)
        for flag in ("--json", "--output-schema", "--output-last-message", "--sandbox"):
            if flag not in help_text:
                raise Halt("当前 CLI 缺少所需参数：" + flag)
        status = command(prefix + ["login", "status"], self.root, include_stderr=True)
        if "chatgpt" not in status.lower():
            raise Halt("尚未确认 ChatGPT 登录；请执行 codex login 与 codex login status。")
        self.assert_config_current()
        return {"codex": version, "base": self.git("rev-parse", "HEAD"),
                "authentication": "ChatGPT", "runtime": str(self.runtime)}

    def changed(self, wt, base):
        tracked = self.git("diff", "--no-renames", "--name-only", "-z", base, cwd=wt)
        new = self.git("ls-files", "--others", "--exclude-standard", "-z", cwd=wt)
        return sorted(set(p for p in (tracked + "\0" + new).split("\0") if p))

    def guard(self, task, wt, base):
        paths = self.changed(wt, base)
        if len(paths) > self.cfg["max_changed_files"]:
            raise Halt("变更文件过多，超过单任务限制。")
        for p in paths:
            if not valid_path(p):
                raise Halt("变更包含不支持的路径。")
            if any(covered(p, x) for x in self.cfg["protected_paths"]):
                raise Halt("触及受保护路径：" + p)
            if not any(covered(p, x) for x in task["allowed_paths"]):
                raise Halt("变更超出任务范围：" + p)
            target = Path(wt) / p
            if target.is_symlink() or not target.resolve().is_relative_to(Path(wt).resolve()):
                raise Halt("不接受符号链接或跨工作区变更：" + p)
            if target.exists() and (not target.is_file() or target.stat().st_size > self.cfg["max_file_bytes"]):
                raise Halt("文件类型或大小超出本启动版范围：" + p)
        return paths

    def context(self, task, wt):
        parts = []
        for p in task["inputs"]:
            target = (wt / p).resolve()
            if not target.is_relative_to(wt.resolve()) or not target.is_file():
                raise Halt("上下文文件缺失或越界：" + p)
            text = target.read_text(encoding="utf-8")
            if len(text) > 16000:
                text = text[:16000] + "\n[仅注入前 16000 字符，请按需读取原文件]"
            parts.append(f"文件 {p}:\n{text}")
        return "\n\n".join(parts)

    def model(self, role, prompt, wt, outdir, attempt):
        schema = self.control / "schemas" / f"{role}.json"
        output = outdir / f"{role}-{attempt}.json"
        atomic_text(outdir / f"{role}-{attempt}.prompt.txt", prompt)
        argv = self.cfg["codex_command"] + ["--ask-for-approval", "never", "exec",
                "--sandbox", "workspace-write" if role == "worker" else "read-only",
                "--json", "--output-schema", str(schema), "--output-last-message", str(output),
                "-c", "agents.enabled=false"]
        setting = self.cfg["roles"][role]
        if setting.get("model"):
            argv += ["--model", setting["model"]]
        if setting.get("reasoning_effort"):
            argv += ["-c", "model_reasoning_effort=" + json.dumps(setting["reasoning_effort"])]
        argv += ["-"]
        code = logged_process(argv, wt, outdir / f"{role}-{attempt}",
                              self.cfg["model_timeout_seconds"], prompt)
        if code:
            raise Halt(f"{role} 退出码 {code}；检查对应日志。额度、认证、网络或权限问题不自动重试。")
        if not output.is_file():
            raise Halt(role + " 没有生成结构化结果。")
        value = read_json(output)
        key = "status" if role == "worker" else "verdict"
        options = ("completed", "blocked") if role == "worker" else ("pass", "revise", "blocked")
        if (not isinstance(value, dict) or set(value) != {key, "summary", "issues", "evidence"}
                or value.get(key) not in options or not isinstance(value.get("summary"), str)
                or any(not isinstance(value.get(k), list) or
                       not all(isinstance(s, str) for s in value[k]) for k in ("issues", "evidence"))):
            raise Halt(role + " 结果字段不符合协议。")
        return value

    def checks(self, task, wt, outdir, attempt):
        results = []
        for name in task["checks"]:
            spec = self.cfg["checks"][name]
            argv = [x.replace("{python}", sys.executable).replace("{control}", str(self.root)).replace("{task_id}", task["id"])
                    for x in spec["argv"]]
            code = logged_process(argv, wt, outdir / f"check-{name}-{attempt}",
                                  spec["timeout_seconds"])
            results.append({"name": name, "exit_code": code,
                            "argv": argv, "config_sha256": self.config_hash,
                            "stdout": f"check-{name}-{attempt}.stdout.log",
                            "stderr": f"check-{name}-{attempt}.stderr.log"})
        write_json(outdir / f"checks-{attempt}.json", results)
        return results

    def ensure_snapshot(self, wt, candidate):
        if self.git("rev-parse", "HEAD", cwd=wt) != candidate or self.git("status", "--porcelain", cwd=wt):
            raise Halt("检查或审阅期间工作区被修改；原结果不再对应当前快照。")

    def execute(self, state):
        task_id = state["id"]
        job = self.job(task_id)
        outdir = self.runtime / "outbox" / task_id
        outdir.mkdir(exist_ok=True)
        wt = self.runtime / "worktrees" / task_id
        self.save_state(state, status="running")
        try:
            self.assert_config_current()
            if digest(job / "task.json") != state["task_sha256"]:
                raise Halt("入队后任务已被修改；请使用新 ID 重新提交。")
            task = self.validate(read_json(job / "task.json"))
            write_json(outdir / "task.json", task)
            base = self.git("rev-parse", "HEAD")
            branch = self.branch_prefix + task_id
            self.save_state(state, base=base, branch=branch, worktree=str(wt),
                            config_sha256=self.config_hash)
            self.git("worktree", "add", "-b", branch, str(wt), base)
            context = self.context(task, wt)
            feedback = "首次执行。"
            for attempt in range(1, self.cfg["max_attempts"] + 1):
                self.assert_config_current()
                self.save_state(state, attempt=attempt)
                before = self.git("rev-parse", "HEAD", cwd=wt)
                prompt = ("你是执行者。阅读 AGENTS.md；按任务修改文件，遵守 allowed_paths。\n"
                          "不自行提交、切换分支、合并、推送或更改调度配置，不启动额外代理。\n"
                          "有学术定义歧义或需要扩大范围时返回 blocked 并具体说明。\n"
                          "完成必须有可审阅的文件变更，模型自述不等于通过验收。\n"
                          + json.dumps(task, ensure_ascii=False, indent=2)
                          + "\n\n上下文：\n" + context + "\n\n上一轮反馈：\n" + feedback)
                worker = self.model("worker", prompt, wt, outdir, attempt)
                if self.git("rev-parse", "HEAD", cwd=wt) != before:
                    raise Halt("执行者自行改变了提交，需人工检查现场。")
                paths = self.guard(task, wt, base)
                if worker["status"] == "blocked":
                    raise Halt("执行者需要决策：" + worker["summary"] + "；" + "；".join(worker["issues"]))
                if not paths:
                    raise Halt("没有可审阅的变更。")
                self.git("add", "--all", cwd=wt)
                if self.git("diff", "--cached", "--name-only", cwd=wt):
                    self.git("commit", "-m", f"task({task_id}): attempt {attempt}", cwd=wt)
                candidate = self.git("rev-parse", "HEAD", cwd=wt)
                self.guard(task, wt, base)
                self.ensure_snapshot(wt, candidate)
                self.save_state(state, candidate=candidate, changed_files=paths)
                self.assert_config_current()
                results = self.checks(task, wt, outdir, attempt)
                self.assert_config_current()
                self.ensure_snapshot(wt, candidate)
                self.save_state(state, checks=results)
                failures = [x for x in results if x["exit_code"]]
                if failures:
                    feedback = "确定性检查失败。\n" + json.dumps(failures, ensure_ascii=False)
                    for x in failures:
                        for key in ("stdout", "stderr"):
                            feedback += "\n" + (outdir / x[key]).read_text(encoding="utf-8", errors="replace")[-7000:]
                    if attempt == self.cfg["max_attempts"]:
                        raise Halt("检查未通过且已达到修复次数上限。")
                    continue
                review_prompt = ("你是独立审阅会话。只读检查当前提交与基线的差异；不要修改任何文件。\n"
                    "以实际代码、任务验收条件、检查证据为准，不因执行者声称成功而通过。\n"
                    "重点检查范围、错误处理、语义/数据口径和遗漏。测试通过不代表学术结论正确。\n"
                    f"基线提交：{base}\n候选提交：{candidate}\n可运行 git diff {base} HEAD 查看差异。\n"
                    + json.dumps(task, ensure_ascii=False, indent=2) + "\n检查结果：\n"
                    + json.dumps(results, ensure_ascii=False) + "\n执行者陈述（待验证）：\n"
                    + json.dumps(worker, ensure_ascii=False))
                review = self.model("reviewer", review_prompt, wt, outdir, attempt)
                self.ensure_snapshot(wt, candidate)
                self.save_state(state, reviewer=review)
                if review["verdict"] == "pass":
                    self.assert_config_current()
                    self.save_state(state, status="needs_review", reason="检查与自动审阅通过，待确认合入。")
                    break
                if review["verdict"] == "blocked":
                    raise Halt("审阅者需要决策：" + review["summary"])
                feedback = json.dumps(review, ensure_ascii=False, indent=2)
                if attempt == self.cfg["max_attempts"]:
                    raise Halt("审阅仍要求修订，已达到修复次数上限。")
        except (Halt, OSError, ValueError, subprocess.SubprocessError) as exc:
            extra = {"cleanup": exc.cleanup} if isinstance(exc, ProcessHalt) else {}
            self.save_state(state, status="blocked", failure_stage="execution", reason=str(exc), **extra)
        except KeyboardInterrupt:
            self.save_state(state, status="blocked", reason="用户中断；保留现场。")
        finally:
            self.report(state)
        return state["status"]

    def report(self, state):
        outdir = self.runtime / "outbox" / state["id"]
        outdir.mkdir(exist_ok=True)
        write_json(outdir / "manifest.json", state)
        lines = [f"# {state['id']} 审阅包", "", f"状态：{state['status']}",
                 f"更新时间：{state['updated_at']}", f"轮次：{state['attempt']}",
                 "", "## 结论", state.get("reason", ""), "", "## 提交",
                 f"基线：{state.get('base', '尚未创建')}",
                 f"候选：{state.get('candidate', '尚未形成')}", "", "## 变更文件"]
        lines += ["", "配置 SHA-256：" + state.get("config_sha256", "尚未读取"),
                  "失败阶段：" + state.get("failure_stage", "无")]
        lines += ["- " + p for p in state.get("changed_files", [])]
        lines += ["", "## 确定性检查"]
        lines += [f"- {x['name']}：exit_code={x['exit_code']}" for x in state.get("checks", [])]
        lines += ["", "## 自动审阅", state.get("reviewer", {}).get("summary", "尚未通过自动审阅。")]
        lines += ["- " + x for x in state.get("reviewer", {}).get("issues", [])]
        lines += ["", "## 给 Chat 的审阅任务", "检查 task.json 的验收口径与 changes.patch 的实际变更。",
                  "重点指出必须修改的问题和需要用户决定的语义口径；不要只复述执行者报告。",
                  "needs_review 表示自动检查通过，尚未合入主分支；accepted 才表示已合入。"]
        atomic_text(outdir / "review.md", "\n\n".join(lines) + "\n")
        if state.get("candidate"):
            patch = subprocess.run(["git", "diff", "--binary", state["base"], state["candidate"]],
                                   cwd=self.root, capture_output=True, timeout=45)
            if patch.returncode == 0:
                (outdir / "changes.patch").write_bytes(patch.stdout)
        index = ["# 协作任务状态", "", "| 任务 | 状态 | 更新 |", "|---|---|---|"]
        index += [f"| [{s['id']}]({s['id']}/review.md) | {s['status']} | {s['updated_at']} |" for s in self.jobs()]
        atomic_text(self.runtime / "outbox" / "index.md", "\n".join(index) + "\n")

    def run_once(self):
        with self.lock():
            try:
                self.load_config()
            except (Halt, OSError, ValueError) as exc:
                self.scheduler_status("blocked", str(exc), "configuration", error=exc)
                return "blocked"
            self.scheduler_status("ready")
            self.ingest()
            recovered = False
            for state in self.jobs():
                if state["status"] == "running":
                    self.save_state(state, status="blocked", reason="上次运行未正常结束；不自动重放，保留工作区。")
                    self.report(state)
                    recovered = True
            if recovered:
                return "blocked"
            states = {s["id"]: s for s in self.jobs()}
            if any(s["status"] == "needs_review" for s in states.values()):
                return None
            for state in states.values():
                if state["status"] != "queued":
                    continue
                if digest(self.job(state["id"]) / "task.json") != state["task_sha256"]:
                    self.save_state(state, status="blocked", reason="入队后任务被修改，请以新 ID 提交。")
                    self.report(state)
                    return "blocked"
                task = read_json(self.job(state["id"]) / "task.json")
                if any(states.get(d, {}).get("status") != "accepted" for d in task.get("depends_on", [])):
                    continue
                try:
                    self.freeze_config(state)
                    self.doctor(refresh=False)
                except (Halt, OSError, ValueError, subprocess.SubprocessError) as exc:
                    self.preflight_failed(state, exc)
                    return "blocked"
                except KeyboardInterrupt:
                    self.preflight_failed(state, Halt("预检被用户中断。"))
                    return "blocked"
                return self.execute(state)
        return None

    def accept(self, task_id):
        with self.lock():
            self.load_config()
            self.clean_main()
            state = self.state(task_id)
            if state["status"] != "needs_review":
                raise Halt("只能接纳 needs_review 状态的任务。")
            head = self.git("rev-parse", "HEAD")
            if head not in (state["base"], state["candidate"]):
                raise Halt("主分支已前进，旧检查不适用。请基于新主分支以新 ID 重跑任务。")
            if state.get("protocol_version") != 2:
                raise Halt("旧任务没有新版配置证据，请以新 ID 重新运行后再接纳。")
            for directory in (self.job(task_id), self.runtime / "outbox" / task_id):
                snapshot = directory / "config.snapshot.json"
                if not snapshot.is_file() or digest(snapshot) != state["config_sha256"]:
                    raise Halt("任务配置快照缺失或被修改，不能使用该验收结果。")
            if self.config_hash != state["config_sha256"]:
                raise Halt("控制配置发生变化，需重新验证。")
            task = read_json(self.job(task_id) / "task.json")
            if digest(self.job(task_id) / "task.json") != state["task_sha256"]:
                raise Halt("任务定义在执行后发生变化。")
            wt = Path(state["worktree"])
            self.ensure_snapshot(wt, state["candidate"])
            if self.git("rev-parse", state["branch"]) != state["candidate"]:
                raise Halt("候选分支已变化。")
            self.guard(task, wt, state["base"])
            self.assert_config_current()
            if head != state["candidate"]:
                self.git("merge", "--ff-only", state["candidate"])
            self.save_state(state, status="accepted", accepted_at=now(), reason="已快进合入本地主分支。")
            self.report(state)
            return state

    def reject(self, task_id, reason):
        with self.lock():
            state = self.state(task_id)
            if state["status"] not in ("queued", "needs_review", "blocked"):
                raise Halt("只能关闭 queued / needs_review / blocked 任务。")
            if not reason.strip():
                raise Halt("请写明关闭或要求修订的原因。")
            self.save_state(state, status="rejected", reason=reason, rejected_at=now())
            self.report(state)
            return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("doctor", "status", "run-once"):
        sub.add_parser(name)
    s = sub.add_parser("submit"); s.add_argument("file")
    s = sub.add_parser("accept"); s.add_argument("id")
    s = sub.add_parser("reject"); s.add_argument("id"); s.add_argument("--reason", required=True)
    s = sub.add_parser("watch")
    s.add_argument("--max-jobs", type=int, default=5)
    s.add_argument("--interval", type=float, default=5)
    args = parser.parse_args()
    if os.name != "posix":
        parser.error("此启动版支持 Linux/WSL/macOS；Windows 请使用 WSL。")
    try:
        runner = Runner(args.root)
        if args.cmd == "doctor":
            try:
                print(json.dumps(runner.doctor(), ensure_ascii=False, indent=2))
            except (Halt, OSError, ValueError, subprocess.SubprocessError) as exc:
                runner.scheduler_status("blocked", str(exc), "preflight", error=exc)
                raise
            runner.scheduler_status("ready")
        elif args.cmd == "submit":
            print("已入队：" + runner.submit(args.file))
        elif args.cmd == "status":
            scheduler = runner.runtime / "scheduler.json"
            if scheduler.exists():
                value = read_json(scheduler)
                if value["status"] == "blocked":
                    print("调度器 blocked", value.get("reason", ""))
            for state in runner.jobs():
                print(state["id"], state["status"], state.get("reason", ""))
        elif args.cmd == "accept":
            runner.accept(args.id)
            print("已合入：" + args.id)
        elif args.cmd == "reject":
            runner.reject(args.id, args.reason)
            print("已关闭，保留现场：" + args.id)
        elif args.cmd == "run-once":
            result = runner.run_once()
            print(result or "暂无可执行任务（检查依赖是否已接纳）。")
            return 1 if result == "blocked" else 0
        elif args.cmd == "watch":
            if args.max_jobs < 1 or args.interval < 1:
                raise Halt("max-jobs 必须为正整数，interval 至少为 1 秒。")
            count = 0
            while count < args.max_jobs:
                result = runner.run_once()
                if result:
                    count += 1
                    print(result, flush=True)
                    if result == "blocked":
                        print("遇到阻塞，结束本次 watch；请查看审阅包。", flush=True)
                        return 1
                time.sleep(args.interval)
    except (Halt, OSError, ValueError, subprocess.SubprocessError) as exc:
        print("暂停：" + str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("已停止监听；现有任务保留。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
