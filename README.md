# chat-codex_cli

网页 Chat 规划与发布 GitHub 任务，本机 Ubuntu / WSL 中的 Codex CLI 执行。也可直接进入原生 CLI 对话、选择模型和思考强度。执行分支上传为 PR，是否合并由用户决定。

## 两份主要手册

- **[用户使用手册](docs/用户使用手册.md)**：日常命令、新仓库登记、模型设置、自动与交互混合使用、PR 处理。第 9 节为原生 CLI 使用。
- **[给网页 Chat 的协作手册](docs/Chat协作手册.md)**：上传或提供给新 Chat，另附目标仓库和本地配置摘要。第 0 节先区分自动与交互任务。

## 获取与验证

在 Ubuntu 中，安装并登录 Git、GitHub CLI 和 Codex CLI 后，获取这份工具库：

```bash
mkdir -p "$HOME/codex-tools"
```

```bash
gh repo clone xiangshui001/chat-codex_cli "$HOME/codex-tools/chat-codex_cli"
```

```bash
python3 "$HOME/codex-tools/chat-codex_cli/codex-github-local/verify.py"
```

测试不调用真实模型或 GitHub 写入。Ubuntu 应执行 53 项，无跳过。已有目录请确认内容后继续使用，不覆盖已有工作。

接入业务仓库按用户手册第 5 节，用自己的配置文件登记。**工具库和业务仓库是两个角色；下载本工具不会自动把本仓库或任何业务仓库加入任务队列。**

## 三种用法

| 入口 | 执行方式 |
|---|---|
| Chat 自动派单 | `[codex] ` Issue + 唯一未编辑执行评论，watch 自动执行、检查和上传 PR |
| Chat 整理、CLI 交互 | `[manual] ` Issue，无自动执行评论；用户让原生 CLI 读取任务并执行 |
| 直接 CLI | 在独立交互克隆中直接输入任务 |

当前不能把正在运行的自动 exec 会话直接变成可插话的 CLI。不同入口不重复执行同一任务。自动 PR 使用 Create a merge commit 后，程序还需核对同步才能记录 accepted；手动 PR 不自动产生此记录。

## 管理与证据

- [本机真实任务工作台](docs/MVP1-WORKBENCH.md)：查看 MVP-1 的任务时间线、Codex 执行输出、文件变化与 Issue 回执；默认本机地址 `http://127.0.0.1:8791/`。

- [MVP-1 账号内仓库自动接入](docs/V2-MVP1.md)：发现本人仓库、授权后创建独立工作区、跨仓库串行去重；[本电脑真实验证记录（codex-cli）](https://github.com/xiangshui001/codex-cli/blob/mvp1-records-20261004/docs/MVP1_SMOKE_2026-10-04.md)。
- [V2 远程指挥与本机工作台设计](docs/V2设计方案.md)：单人、WSL 单主机、多仓库的正式实施设计；含协议、故障恢复与分阶段验收，尚未全部实现。
- [MVP-0 本电脑 Ubuntu 真实验证记录](https://github.com/xiangshui001/codex-cli/blob/mvp0-smoke-20261004/docs/MVP0_SMOKE_2026-10-04.md)：Issue → Codex CLI → 回执及重复轮询已验证；记录保存在 codex-cli，台式机 WSL 尚未验证。
- [integration 模块边界与吸收决策](docs/INTEGRATION.md)：0.1.0、v2、Harness 契约、React 和视觉组件的维护入口。
- [本地 Harness 与迁移验证](docs/HARNESS_VALIDATION.md)：真实 HTTP/core 的隔离 smoke、前端环境与显式 ledger 迁移。
- `codex-github-local-v2/` 是独立旁路原型；`web/app/` 是唯一活跃前端，提供显式 Mock 演示及本地 HTTP 验证入口。二者都尚未替换现役 0.1.0。
- [验证范围](docs/VALIDATION.md)：明确离线测试、真实演示、GitHub PR 和未验证步骤。
- [环境排查](docs/环境排查.md)：WSL 代理、沙箱审批、PATH 与依赖。
- [修复历史](history/README.md)：可靠性修复、退出码补丁、桥接和交互文档。
- `codex-github-local/`：程序、通用 profile、schema、完整测试夹具。
- `validation/historical/`：历史脱敏验证摘要；`PUBLICATION.json`：此次归档文件校验和。

本仓库公开。仅收录通用源码、操作说明和脱敏证据，不收录认证文件、真实业务数据、运行 worktree、原始模型日志、个人路径或现用配置。许可证尚未另行指定；本次上传没有代用户选择开源许可证。

现版保持串行、人工合并，不提供自动部署、开机自启或跨电脑抢占。
