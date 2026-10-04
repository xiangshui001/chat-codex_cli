> 历史快照，当前状态见[最新主页](../README.md)。

# 验证范围与证据

以下是历史事实，不是对任意新机器的保证。公开库不包含模型完整输出、认证文件、真实业务配置或业务仓库的提交标识。

| 阶段 | 已有证据 | 限制 |
|---|---|---|
| 启动包退出码修复 | 用户 Ubuntu 回传 30 项通过、无跳过；含 9 项退出码测试 | 模型为离线替身 |
| 独立演示任务 | 实际 CLI 执行、固定检查、独立审阅；用户回传本地人工接纳成功 | 查询条件示例，不验证真实辞书数据 |
| GitHub 桥接离线回归 | 原版在 Windows 27 项执行、26 项跳过；用户 Ubuntu 完整 53 项通过，0 跳过 | GitHub、模型为替身；Git 使用临时仓库 |
| GitHub 真实任务 | 用户回传 waiting_review；已回读确认 PR 存在且未合并，正文记录两项检查及独立审阅通过 | 完整 PR 差异/本地原始日志未在这次归档中复核；人工合并与 accepted 尚未确认 |
| 原生 CLI | 用户截图证明进入交互界面；回传只读项目检查与获准的远端 SHA 查询成功 | 不代表运行依赖齐全或产品测试通过 |

历史 53 项完整 Linux 回归摘要保存在 `validation/historical/`。公开版只调整示例 profile、安装默认值及测试引用；核心运行组件未改。公开版 Windows 重跑结果另存 `validation/public-windows-summary.json`，不能替代 POSIX 进程组与锁验证。GitHub Actions 如有成功记录，可作为公开版新的 Linux 离线验证；未运行或失败时不得声称通过。

复现（没有真实模型或 GitHub 写入）：

```bash
python3 codex-github-local/verify.py
```

结果写入 `codex-github-local/validation/`（已忽略，不混入历史证据）。Linux 应执行全部 53 项，无跳过；Windows 因 POSIX 锁/进程组限制会跳过相关项。

模型、数据、GPU、生产服务和跨机抢占不属于这组离线测试覆盖范围。
