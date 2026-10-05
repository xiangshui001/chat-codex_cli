# 当前执行端与本机工作台（V2 0.2.0 / MVP-2）

支持账号仓库发现、机器精确路由、新/旧对话、三种模型模式、本地成果、完成回执与草稿 PR。账号和路径按自己的电脑配置。

- [首次安装](../docs/安装说明.md)
- [中文 HTML 使用指南](../docs/使用指南.html)
- [配置、派单协议与 API](../docs/V2-MVP2.md)
- [验证范围](../docs/VALIDATION.md)

## 安装后的命令

| 命令 | 作用 |
|---|---|
| `codex-github-local-v2` | 默认最新监听器 |
| `codex-github-local-v2-mvp2` | 同一监听器的兼容别名 |
| `codex-github-local-v2-model-api` | 本机 HTTP 文本协作 API / stdio MCP 顾问工具 |
| `codex-github-local-v2-workbench` | 默认读取最新状态的只读 API 与前端 |

当前安装包不再注册 control / MVP-0 / MVP-1 原型命令。被当前实现复用的内部模块和测试仍在源码中；历史说明和示例见 [history/v2](../history/v2/README.md)。V1 单独归档在 [history/v1](../history/v1/README.md)。

0.1.0 升级按协议显式备份并迁移 schema 3/4 → 5，保留原数据库、对话与成果。默认不设时间/数据预算；支持同一个 Issue 的进度查询、追加指示、停止、原地续跑及远程合并。
