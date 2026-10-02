# codex-github-local-v2 prototype

这是 `chat-codex_cli` 的旁路 v2 原型。它**不会替换或覆盖**现有 `codex-github-local 0.1.0`。

目标是先把下一版最容易出错、也最值得稳定的核心抽出来：

- read_scope / write_scope 分离；
- protected path 决策；
- 明确状态机；
- 模型 preflight + fallback；\n- GitHub Control Issue 协议：可远程切换默认模型/思考强度、pause/resume/status；
- 任务预算；
- “验证不可用 → Draft PR / 人工复核”而不是一律 blocked。

## 运行

仅依赖 Python 3.11+ 标准库。

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

这仍然不是可替换现役 0.1.0 task watcher 的版本。现在已经有 GitHub Control Issue 的 gh CLI adapter、模型 preflight 子进程、runtime settings 原子持久化、replay ledger、task claim 模型冻结和本地 evidence store。

仍未接入完整代码任务链：

- Git worktree 创建与回收；
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
- 新任务 claim 时把 runtime-default 冻结成 task.resolved.json；
- GitHub Actions 对纯逻辑、mock adapter 和持久化行为持续跑测试。

后续在电脑端接入时，可以用入口 codex-github-local-v2-control。当前尚未在真实台式机上做 GitHub→Codex 的端到端现场验证。
