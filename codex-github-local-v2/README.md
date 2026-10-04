# V2 执行端与本机工作台（0.1.0）

当前日常入口为 MVP-2：账号仓库发现、Host 精确路由、新/旧对话、三种模型模式、本地保留成果、完成回执与草稿 PR。与 V1 / MVP-1 分开安装、配置和存储，不迁移旧状态。

- [MVP-2 安装 / 配置 / 协议 / API](../docs/V2-MVP2.md)
- [保留的 MVP-1 协议](../docs/V2-MVP1.md)
- [只读真实工作台](../docs/MVP1-WORKBENCH.md)
- [MVP-0 单仓库验证](../docs/V2-MVP.md)
- [当前验证范围](../docs/VALIDATION.md)

## 命令入口

| 命令 | 作用 |
|---|---|
| `codex-github-local-v2-mvp1` | 保留的账号内串行执行、仅本地成果 |
| `codex-github-local-v2-mvp2` | Host 路由、会话续接、三种模型模式与草稿 PR |
| `codex-github-local-v2-model-api` | 本机 HTTP 文本协作 API / GPT 的 stdio MCP 顾问工具 |
| `codex-github-local-v2-workbench` | 本机只读 API 与构建后的前端 |
| `codex-github-local-v2-mvp0` | 早期单仓库验证入口 |
| `codex-github-local-v2` | 保留的策略 / 执行原型，开发使用 |
| `codex-github-local-v2-control` | 保留的控制 Harness，开发使用 |

MVP-2 的实际能力与恢复边界以 [MVP-2 协议](../docs/V2-MVP2.md)为准；成果保存在本地任务目录并提交草稿 PR，人工合并。完整目标继续保留于 [V2 设计](../docs/V2设计方案.md)；原型接口和测试不表示所有设计能力已交付。
