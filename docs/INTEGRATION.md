# 当前模块边界

当前链路：目标仓库或 hub 的 GitHub Issue → MVP-2 Host 路由 → SQLite 领取去重 → 独立目标仓库克隆 → 指定对话/模型执行 → 本地成果 → 专用分支与草稿 PR → 原 Issue 完成回执。只读工作台读取数据库、事件和日志。

- `codex-github-local-v2` 0.1.0：`mvp2` 为当前模式；`mvp1` / `mvp0` 保留旧协议；`workbench --protocol mvp2` 读取新状态库。
- `model-api` 独立提供本机 HTTP 文本协作服务；GPT 主导任务还使用本轮专属 stdio MCP 调用登记的外部模型。其它模型模式直接运行受限文件工具，不启动 Codex。
- `web/app`：默认真实工作台；只有 `?view=demo` 才加载 Mock 演示，`?harness=local-smoke` 为确定性开发测试。后者不是 GitHub → Codex 真机验证。
- 原型 `codex-github-local-v2` / `codex-github-local-v2-control` CLI 与 Harness 契约保留用于开发，不是日常 MVP-1 的启动入口。
- `codex-github-local/`：独立 V1 0.1.0，不随本次整理迁移或修改。

实际交付以 [MVP-2 协议](V2-MVP2.md)为准；完整 V2 的审批与恢复设计仍包含未来功能。架构目标看 [V2 设计](V2设计方案.md)。

旧吸收决策与上游来源保存在 [2026-10-02 集成记录](../history/INTEGRATION-20261002.md)，旧确定性测试保存在 [Harness 记录](../history/HARNESS_VALIDATION-20261002.md)。第三方 NOTICE 与许可证继续保留。
