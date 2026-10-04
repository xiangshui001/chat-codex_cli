# 当前模块边界

当前链路：目标仓库或记录仓库的 GitHub Issue → 机器精确路由 → SQLite 领取去重 → 独立目标仓库克隆 → 指定对话/模型执行 → 本地成果 → 专用分支与草稿 PR → 原 Issue 完成回执。

- `codex-github-local-v2` 和兼容别名 `codex-github-local-v2-mvp2` 均进入最新监听器，使用 schema 3 的 `mvp2.sqlite3`。
- `model-api` 提供鉴权的本机 HTTP 文本协作，以及 GPT 任务专属 stdio MCP 顾问工具。
- `workbench` 默认读取最新数据库、事件、日志和发布进度；保留显式旧协议读取以兼容已有本机数据。
- `web/app` 默认真实工作台；`?view=demo` 显式加载演示，`?harness=local-smoke` 用于确定性开发测试。
- 早期 V2 原型的公共命令已退出安装入口，当前实现复用的模块和回归测试保留。
- V1 源码、测试、旧手册和 CI 快照在 [history/v1](../history/v1/README.md)，早期 V2 文档及示例在 [history/v2](../history/v2/README.md)。

当前能力以[配置与协议](V2-MVP2.md)为准。历史设计和旧验证只描述当时阶段，不能作为当前部署说明。第三方来源及许可证继续保留在 [NOTICE](../web/app/NOTICE.md)。
