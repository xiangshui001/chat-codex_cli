# 当前模块边界

当前链路：GitHub Issue → MVP-1 轮询器 → SQLite 领取去重 → 独立任务克隆 → 本机 Codex CLI → Issue 状态回执。只读工作台从本地数据库、事件和日志读取执行过程。

- `codex-github-local-v2` 0.0.6：`mvp1` 为当前账号仓库模式；`mvp0` 为早期单仓库验证入口；`workbench` 提供本机只读 HTTP 与前端静态文件。
- `web/app`：默认真实工作台；只有 `?view=demo` 才加载 Mock 演示，`?harness=local-smoke` 为确定性开发测试。后者不是 GitHub → Codex 真机验证。
- 原型 `codex-github-local-v2` / `codex-github-local-v2-control` CLI 与 Harness 契约保留用于开发，不是日常 MVP-1 的启动入口。
- `codex-github-local/`：独立 V1 0.1.0，不随本次整理迁移或修改。

完整 V2 的模型策略、审批与恢复设计不代表已在 MVP-1 实现。实际安装看 [用户手册](用户使用手册.md)，架构目标看 [V2 设计](V2设计方案.md)。

旧吸收决策与上游来源保存在 [2026-10-02 集成记录](../history/INTEGRATION-20261002.md)，旧确定性测试保存在 [Harness 记录](../history/HARNESS_VALIDATION-20261002.md)。第三方 NOTICE 与许可证继续保留。
