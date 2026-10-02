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

这不是可替换现役 watcher 的版本。当前没有：

- GitHub 轮询/写评论；
- Git worktree；
- Codex CLI 子进程；
- PR 创建；
- 真正的 wall-clock 预算和进程回收；
- 本地 JSONL evidence bundle。

这些会通过 adapter 层逐步接入，而不是直接修改 0.1.0。

设计说明见 [../docs/V2架构草案.md](../docs/V2架构草案.md)。


## GitHub 控制面原型

现在已加入控制协议核心。示例见 examples/control-set-model.json，协议见 docs/CONTROL_ISSUES.md。

目前已经能在纯 Python 核心中解析和幂等应用 set-default-model / pause / resume / status；真实 GitHub watcher、模型 preflight 和 runtime settings 原子落盘仍属于下一步 adapter 工作。
