# codex-github-local-v2 prototype

下一阶段实施入口：[V2 远程指挥与本机工作台设计](../docs/V2设计方案.md) 及 [实施验收清单](../docs/V2实施验收.md)。新的协议、事务状态库和完整执行链尚未实现，以下仍是当前原型的实际能力。

这是 `chat-codex_cli` 的旁路 v2 原型。它**不会替换或覆盖**现有 `codex-github-local 0.1.0`。

目标是先把下一版最容易出错、也最值得稳定的核心抽出来：

- read_scope / write_scope 分离；
- protected path 决策；
- 明确状态机；
- 模型 preflight + fallback；
- GitHub Control Issue 协议：可远程切换默认模型/思考强度、pause/resume/status；
- 任务预算；
- “验证不可用 → Draft PR / 人工复核”而不是一律 blocked。

## 运行

仅依赖 Python 3.11+ 标准库。

integration 中的包版本为 **0.0.3**。运行时没有第三方 Python 依赖；构建需要
setuptools。安装到独立虚拟环境，不覆盖 0.1.0 的 launcher/profile/runtime：

```bash
cd codex-github-local-v2
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/codex-github-local-v2 --help
.venv/bin/codex-github-local-v2-control --help
```

```bash
cd codex-github-local-v2
python3 -m unittest discover -s tests -v
```

验证示例任务：

```bash
PYTHONPATH=src python3 -m codex_github_local_v2.cli validate examples/audit-readonly.json
```

查看任务摘要：

```bash
PYTHONPATH=src python3 -m codex_github_local_v2.cli explain examples/audit-readonly.json
```

## 当前边界

这仍然不是可替换现役 0.1.0 task watcher 的版本。现在已经有 GitHub Control Issue 的 gh CLI adapter、模型 preflight 子进程、runtime settings 原子持久化、带待投递回执的 ledger、task claim 模型冻结、本地 evidence store，以及独立 GitWorkspace 创建/范围守卫/候选提交 adapter。

仍未接入完整代码任务链：

- 把已有 GitWorkspace adapter 接入普通任务全流程；
- [codex] 普通任务的 v2 GitHub watcher；
- Executor/Reviewer 的真实完整执行循环；
- wall-clock/stall process supervisor；
- 候选 commit / push / PR 创建；
- 人工 merge 后 accepted 同步。

因此本分支只能作为 v2 原型和未来控制 watcher 的代码来源，不能直接替换现役 0.1.0。

设计说明见 [../docs/V2架构草案.md](../docs/V2架构草案.md)。


## GitHub 控制面原型

现在已加入控制协议核心。示例见 examples/control-set-model.json，协议见 docs/CONTROL_ISSUES.md。

目前已经实现：

- 解析与严格校验 set-default-model / pause / resume / status；
- authorized user / Issue ID / 未编辑评论 / repository 校验核心；
- gh CLI 的 Issue 查询、评论读取和状态回写 adapter；
- 真实 Codex exec 最小 preflight wrapper；
- preflight 成功后才原子写 runtime-settings.json，失败保持旧设置；
- control-ledger.json 防止旧 Issue 重放；
- 控制结果和原始回执先原子保存；发送失败后只补发回执，不重复应用或探测模型；
- 新任务 claim 时把 runtime-default 冻结成 task.resolved.json；
- GitHub Actions 对纯逻辑、mock adapter 和持久化行为持续跑测试。

后续在电脑端接入时，可以用入口 codex-github-local-v2-control。当前尚未在真实台式机上做 GitHub→Codex 的端到端现场验证。

## 持久化与模型边界

0.0.2 使用 control-ledger **schema 2**，区分动作结果与回执投递状态。旧 schema 1
没有原始回执快照，不能确定哪些评论丢失；新版会拒绝读取并保留原文件，不自动
升级或清空。0.0.3 提供显式 migration function/CLI，需完整历史状态和回执核对
证据，先保留原字节备份再原子替换；不会在启动时执行。升级运行中的 Host 前，应先停止旧 watcher、备份 runtime/ledger/冻结
任务，并逐项核对历史 Issue 与回执后进行显式迁移。不能改用空 ledger 重放仍开放
的历史控制 Issue。本轮没有迁移任何现场状态或启动 watcher。

回执投递前读取全部评论，按 control ID、fingerprint 和完整正文核对。发送账号应
在 authorized_users 中；响应丢失或投递后本地写入失败可据远端回执恢复。待投递
结果优先于新命令，即使 Issue 已关闭也会补发；持续投递错误保留证据并阻止接收
下一条控制。单实例锁仍由命令入口负责。

`model_adapter.py` 是供应商 I/O 契约，当前仅定义可用性 probe；实际实现是
`CodexProbeRunner`。模型选择、fallback、控制状态和 claim 冻结由 core 决定。
DeepSeek/OpenAI-compatible adapter、真实生成/流式事件接口尚未实现。
第二阶段增加 loopback-only local-smoke HTTP Harness，复用实际 core/持久化，明确
使用本地 GitHub source 与 model probe 替身；不是生产 API。运行与迁移见
[HARNESS_VALIDATION.md](../docs/HARNESS_VALIDATION.md)。
完整模块职责及 PR 来源见 [INTEGRATION.md](../docs/INTEGRATION.md)。
