# MVP-0 实现与验证记录

日期：2026-10-04。设计基线：`design/v2-issue-workbench` / `5a4422b`。实现分支：`feature/v2-mvp0-issue-to-codex`。本记录仅说明已完成的 MVP-0，不代表完整 M1～M5 或台式机 WSL 已验收。

## 实际实现

- `mvp0.py`：本地配置、严格 Issue 协议、SQLite、gh REST 轮询、仓库核对、回执与独立命令入口。
- `mvp0_runner.py`：本机 CLI 版本探测、参数数组和 stdin、分别记录 stdout/stderr、进程组清理、精确 JSONL 结果判定。
- V2 包 0.0.4 增加 `codex-github-local-v2-mvp0` 入口；不改变旧入口的任务协议，不加载完整 V2 controller/model adapter，不改 V1。
- [V2-MVP](V2-MVP.md) 给出安装、配置、协议、运行方式、恢复限制和安全测试步骤；完整设计文档保留。

## Issue 与轮询

只接开放的 `[codex-v2-mvp]` Issue，排除 PR。唯一未编辑授权评论以 `/codex-v2-mvp run` 开头，最小 JSON 为 request_id、host_id、repo、base_sha、task.prompt、task.write_paths。顶层与 task 的未知字段拒绝，双方作者必须在本地名单中。

轮询使用 `gh api --hostname github.com` 的仓库 Issues 列表与评论分页，不使用搜索索引。默认间隔 60 秒，一次轮询最多启动一个新任务。HTTP/CLI 错误记录受控错误码，不回显可能包含敏感内容的原始 stderr。

## SQLite schema 和防重复

只有两张表：

| 表 | 数据 |
| --- | --- |
| tasks | repository_id、issue_id/number、唯一 request_id、host_id/repo、state、base_sha、冻结 prompt/write_paths、授权 comment_id/原文哈希、created_at/started_at/finished_at、exit_code、CLI 版本/argv/cwd、结果/错误、diff_nonempty、receipt_comment_id |
| events | 递增 id、task_id 外键、kind、UTC 时间、JSON detail；记录 claimed、started、process_started、finished、receipt_sent 等事实 |

`request_id` 和 `(repository_id, issue_id)` 分别唯一，queued/running 的部分唯一索引保证一个活动槽。领取状态与事件在同一事务提交，再启动进程。PRAGMA user_version=1 预留显式迁移边界；不自动读取或升级旧 V2/V1 状态。

重复 request_id、同 Issue 重复 poll、重新打开或更换该 Issue 的授权都不会建立第二次执行。新任务须新 Issue、新 request_id。未结任务重启不自动重放，直接停下来要求人工核对。

## CLI 与结果

调用 `codex --ask-for-approval never exec --json --sandbox workspace-write --color never -`，prompt 走 stdin，不调用模型 API。CLI 正常退出、精确 turn.completed、有效 JSONL 和范围核对均通过才是 succeeded；过期基线为 stale_base，其他失败为 failed。

结束后 Issue 评论包含 request_id、领取/开始/结束时间、exit code、固定短摘要和 Git 可见 diff 是否非空。本地日志不会上传；回执失败仅重试评论，不重试执行。无 PR/commit/push/merge 自动化。

## 验证按环境分开记录

| 环境 | 本轮证据 | 不代表什么 |
| --- | --- | --- |
| 本电脑：Windows，Python 3.11.9，Git 2.55.0.windows.3 | 能调用 Codex CLI 0.160.0 的版本与帮助；未发现 gh，本电脑没有已安装的 WSL 发行版。MVP 单测 42 项：35 通过、7 个 POSIX 项明确跳过 | 不代表 CLI 已完成真实任务；不代表台式机的安装/登录状态 |
| Linux CI | 待 feature 分支 CI 完成后补充；使用离线 CLI 子进程夹具，无真实模型登录 | 不代表真实 GitHub → Codex → 回执 smoke，更不代表台式机 WSL |
| 台式机 WSL | 未访问、未运行；工作区、登录、实际 CLI 版本、常驻与进程行为尚未验证 | 不沿用本电脑或 CI 的通过结论 |

单测覆盖合法/非法字段、错误 host/repo、作者允许名单、重复授权/编辑、重复 request_id/Issue、并发 SQLite 领取、事务回滚、stale base、成功/失败、回执生成与补发、分页/PR 过滤、范围与工作区核对。POSIX 子进程用例另验证独立日志、超时子进程清理、非零退出、JSONL、item.completed 和日志上限。

本电脑运行未修改的 `python codex-github-local/verify.py`：V1 共发现 53 项，27 通过、26 个 POSIX 项跳过，0 失败、0 错误。CI 也运行未修改的 V1 53 项回归和 V2 安装入口检查；不能以 Windows 跳过项宣称完整 Linux 验证。

## 真实 smoke

**未完成。** 目前未选择/登记安全测试仓库，也没有在台式机 WSL 运行。没有真实 smoke Issue、真实模型会话或回执证据可报告；离线测试不冒充真实链路。

代码与离线验证完成后，请用户指定目标测试仓库、要验证的是本电脑还是台式机 WSL、对应工作区。若选择本电脑，当前 Linux/WSL 执行前置条件尚未满足；不自动安装 WSL、修改登录或改用另一台主机。

## 当前明显限制与 MVP-1

MVP 只用专用干净测试分支。完成后留下未提交 diff，需人工处理再做下一任务。write_paths 是运行后 Git 范围检查，不提供逐路径内核隔离；忽略文件、外部副作用与可读 HOME 凭据不在完整隔离保证内。长任务期间不读取取消指令，没有独立 reviewer、检查流水线、网页、SSE、模型设置或自动发布。断电/强制终止后不自动恢复；只做简单结果回执补发。

MVP-1 建议先在台式机 WSL 完成同一真实 smoke 与重复 poll 验收，再补人工核对中断任务的操作入口及更清楚的本地日志查询。是否扩大到其他能力应另行决定，不在本轮实现。
