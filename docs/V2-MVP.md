# V2 MVP-0：GitHub Issue → 本机 Codex CLI → Issue 回执

MVP-0 是独立、受限的连通性验证入口，基于 `design/v2-issue-workbench` 的 `5a4422b` 开发。完整 [V2 设计](V2设计方案.md)、[协议与恢复](V2协议与恢复.md) 和 [实施验收](V2实施验收.md) 保留为未来目标。本轮不实现完整 M1～M5，不改 main，不修改现役 `codex-github-local/`。

## 范围

实现单用户、单 Host、一个明确登记的测试仓库；主机主动轮询 GitHub REST；同一时间一个任务；使用本机已登录的 `codex exec --json`；两张 SQLite 表防止重复执行；结束后写 Issue 机器状态评论。

暂不实现 React、SSE、多 Host、多用户权限、policy_digest、远程模型设置、独立 reviewer、自动 merge、App Server、DeepSeek/API backend、完整 outbox/recovery、容器级 sandbox。也不自动 commit、push 或创建 PR。状态只有 `queued / running / succeeded / failed / stale_base`。

**执行端目标为 Linux/WSL，原生 Windows 入口会明确拒绝运行。** 本电脑 Windows 上的离线测试、Linux CI 上的测试、台式机 WSL 的真实派单是三类证据，不能互相替代。实际结果见 [MVP0_RESULT](MVP0_RESULT.md)。

## 独立入口和本地登记

仅在选定的 Linux/WSL 上安装 V2 到独立虚拟环境，不使用 V1 安装器。已有 V2 原型可保留，本入口使用自己的数据库和锁，不迁移旧 JSON 状态。包版本为 0.0.4。

```bash
python3 -m venv /ABS/PATH/mvp0-venv
/ABS/PATH/mvp0-venv/bin/pip install ./codex-github-local-v2
/ABS/PATH/mvp0-venv/bin/codex-github-local-v2-mvp0 --help
```

执行环境须具备 Python 3.11+、Git、已登录的 GitHub CLI `gh` 和已登录的 Codex CLI。GitHub 凭据只通过现有 `gh` 使用，不新增模型 API 或密钥管理。CLI 参数已对本电脑的 0.160.0 帮助文本核对；Linux/WSL 上安装的实际版本仍需现场验证。

复制 [配置示例](../codex-github-local-v2/examples/mvp0-config.example.json) 到本机私有目录，替换占位符：

```json
{
  "host_id": "test-host",
  "repo": "OWNER/SAFE-TEST-REPO",
  "allowed_authors": ["OWNER"],
  "workspace": "/home/USER/mvp0-test",
  "workspace_allowlist": ["/home/USER/mvp0-test"],
  "state_dir": "/home/USER/.local/state/chat-codex-mvp0",
  "base_branch": "main",
  "poll_seconds": 60,
  "timeout_seconds": 900
}
```

`workspace` 必须是 allowlist 中某个精确的绝对目录，必须是 Git 仓库根目录。`origin` 只接受与登记仓库一致的 GitHub HTTPS 或 SSH URL。状态目录必须在工作区外；Issue 不能传 cwd 或命令路径。使用可丢弃的专用测试克隆，不默认使用本工具库或生产代码仓库。

在测试克隆中，从最新远程基线创建专用测试分支，例如 `mvp0-smoke`。运行前必须干净；拒绝在 `base_branch` 本身运行。任务结束后保留文件变化，下个任务不会自动清理、覆盖或重置现场。V1、手工 Codex 和其他工具不能同时操作此克隆，MVP 的锁不会约束它们。

```bash
/ABS/PATH/mvp0-venv/bin/codex-github-local-v2-mvp0 --config /ABS/PATH/mvp0-config.json --once
```

`--once` 最多执行一个新任务；失败、过期基线或待补发回执返回非零退出码。去掉 `--once` 按配置间隔轮询，默认 60 秒。本轮没有常驻安装、自启动或电源管理。

## Issue 协议

标题以 **`[codex-v2-mvp]`** 开头。Issue 必须开放且不是 PR。Issue 作者和授权评论作者都必须在本地 `allowed_authors` 中。

只能有一条明确授权评论，第一行必须完全等于 `/codex-v2-mvp run`。后面是 JSON，可直接写 JSON 或用一个 `json` 代码块包住。下面的 SHA 只是格式示例，必须替换为发布时登记基线分支的真实完整 SHA。

````text
/codex-v2-mvp run
```json
{
  "request_id": "6c9134d1-f6ae-49f3-bdfd-e3681c19e183",
  "host_id": "test-host",
  "repo": "OWNER/SAFE-TEST-REPO",
  "base_sha": "0123456789abcdef0123456789abcdef01234567",
  "task": {
    "prompt": "在 docs/mvp0-check.txt 新增一行 MVP-0 smoke。仅创建这一文件。",
    "write_paths": ["docs/mvp0-check.txt"]
  }
}
```
````

约束：

- request_id 是规范小写 UUID；同一次发布重试复用它，新任务生成新的 UUID。
- host_id 和 repo 必须匹配本地登记；SHA 是 40 位小写十六进制。
- prompt 非空且最多 12000 字符；write_paths 是 1～32 个不重复的相对路径。
- 路径使用 `/`；末尾 `/` 明确授权目录内文件，否则精确匹配单文件。不接受绝对路径、`..`、通配符、`.git`、`.codex` 或越界 symlink。
- 顶层及 task 的未知字段、重复 JSON 键、非法类型、编辑后的授权评论均拒绝。普通评论和 V1/完整 V2 前缀不会触发执行。

收到任务后先事务性领取；执行前核对本地 HEAD、远程 `base_branch` 的最新 SHA 与授权 base_sha 完全一致。任一不一致记 `stale_base` 并回执，不运行 Codex，不自动 rebase。成功运行后再次核对；期间远端基线改变也记 stale_base，保留已经产生的修改和实际 exit code。

## 执行、状态和证据

数据库 `state_dir/mvp0.sqlite3` 只有 `tasks` 和 `events`，使用 `PRAGMA user_version=1`、WAL、同步持久化。原子领取同时写 queued 和 claimed 事件；running 在 spawn 前持久化。因此崩溃可能留下“已记 running 但尚未 spawn”的记录，MVP 保守停止，不猜测并重跑。

`request_id` 唯一、`(repository_id, issue_id)` 唯一；部分唯一索引限制同一数据库只有一个 queued/running。主进程同时持有状态目录锁与测试仓库 Git 公共目录锁，以拒绝两个 poller 同时使用同一工作区。

执行命令以参数数组启动，不经 shell 拼接：

```text
codex --ask-for-approval never exec --json --sandbox workspace-write --color never -
```

任务通过 stdin 输入，使用当前 CLI 的本地登录与模型配置。stdout 保存为 `runs/<request_id>/stdout.jsonl`，stderr 单独保存为 `stderr.log`；`execution.json` 保存 CLI 版本、argv 摘要、cwd、PID、时间、exit code 和进程组清理记录。这些只留本机，不提交仓库或上传 Issue。

执行有超时（默认 900 秒）与日志总量限制（16 MiB，检查间隔约 0.2 秒）。到限或中断会终止所属进程组。只有 CLI exit code 为 0、出现精确 `turn.completed`、无失败终态、JSONL 有效且 Git 可见修改在 write_paths 内才报告 succeeded；`item.completed` 不代表任务完成。

`workspace-write` 是 CLI 的工作区权限配置；write_paths 是输入约束和运行后 Git 差异检查，不是逐路径的操作系统隔离。忽略文件和仓库外副作用不能靠 Git 差异完整发现。清除子进程中的常用 GitHub token 环境变量也不等于隔离整个 HOME 的凭据。MVP 只适合本人授权的无敏感数据测试克隆。

## Issue 回执和重启

执行结束后发布一条带 request_id 标识的机器评论，包含状态、claimed/started/finished 时间、exit code、固定格式短摘要、Git diff（含未跟踪文件）是否非空。摘要由程序生成，不直接转发模型文本、命令或环境变量。

回执失败不改变执行结果。下次轮询只补发未确认回执；先按发帖账号 ID 和完整正文检查是否已经存在，处理“已发送但响应丢失”。这只是 tasks 上的单条结果回执标记，没有完整 outbox、后台 reconciliation 或严格跨系统 exactly-once 保证；极端情况下评论仍可能重复，Codex 不会因此重跑。

重启发现 queued/running 时明确报 `unfinished_task_requires_manual_inspection`，停止接单；不自动恢复、重置或删除记录。需要人工检查该环境的进程、日志和工作区，MVP 不提供自动解锁重放命令。正常 Ctrl+C/SIGTERM 会尝试清理；SIGKILL、断电等仍可能留下子进程。清理无法确认时保留 running，不释放槽位。

## 真实 smoke 的验收边界

先由用户指定安全测试仓库、目标主机与该主机中的工作区。只创建一个 docs 测试文件任务，回读真实 Issue 与授权评论，运行真实 poller，再核对 SQLite、真实 CLI 进程证据、文件内容、Issue 回执。再次 poll 后，process_started 事件数量和运行次数必须保持为 1。

报告记录执行机器、操作系统、WSL 发行版（若有）、Python/Git/gh/Codex 版本、Issue/回执链接、任务 ID、进程时间和退出码以及实际变化。**本电脑跑通、Linux CI 通过，都不能宣称台式机 WSL 已跑通。** 测试中的 Mock 和子进程夹具只属于离线测试，不计入真实 smoke。

Codex 参数与 JSONL 事件依据：[官方非交互执行文档](https://learn.chatgpt.com/docs/non-interactive-mode)。
