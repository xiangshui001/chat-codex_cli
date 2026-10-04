# V2 执行端与本机工作台（0.0.6）

当前日常入口为 MVP-1：发现本人账号仓库，领取严格授权的 Issue，在独立目录运行已登录的 Codex CLI，SQLite 防重放并回写状态。与 V1 分开安装、配置和存储。

- [MVP-1 安装 / 配置 / 协议](../docs/V2-MVP1.md)
- [只读真实工作台](../docs/MVP1-WORKBENCH.md)
- [MVP-0 单仓库验证](../docs/V2-MVP.md)
- [当前验证范围](../docs/VALIDATION.md)

## 命令入口

| 命令 | 作用 |
|---|---|
| `codex-github-local-v2-mvp1` | 当前账号内仓库发现与串行执行 |
| `codex-github-local-v2-workbench` | 本机只读 API 与构建后的前端 |
| `codex-github-local-v2-mvp0` | 早期单仓库验证入口 |
| `codex-github-local-v2` | 保留的策略 / 执行原型，开发使用 |
| `codex-github-local-v2-control` | 保留的控制 Harness，开发使用 |

真实任务入口不调用模型 API，不自动创建 PR，不实现完整 V2 恢复。成果保存在本地任务目录。完整目标继续保留于 [V2 设计](../docs/V2设计方案.md)；原型接口和测试不表示所有设计能力已交付。
