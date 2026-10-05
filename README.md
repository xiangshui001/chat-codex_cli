# chat-codex_cli

通过 GitHub Issue 在手机远程使用自己的电脑：领取即回执、原 Issue 可追加指示与查进度、默认不设时间/数据预算；选择新对话或旧对话，指定 GPT / 其它 API / GPT 主导协作及思考强度，完成后保留本地成果、回写 Issue、提交草稿 PR。

**main 只提供当前 V2 0.2.0（MVP-2）作为安装和运行入口。** 项目适用于不同用户与不同电脑；账号、机器标识、记录仓库和私有路径由各执行端自行配置。执行端已验证 Linux / Ubuntu / WSL；Windows 在 WSL 中运行，原生 Windows 与 macOS 尚未验收。

## 从这里开始

- [中文 HTML 使用指南](docs/使用指南.html)：下载后在浏览器打开，可离线阅读；包括首次安装、派单生成器、续接、模型设置和 API 示例。
- [首次安装](docs/安装说明.md)：从 main 安装到自己的电脑。
- [用户使用手册](docs/用户使用手册.md)：日常派单、查看工作台和成果。
- [Chat 协作手册](docs/Chat协作手册.md)：交给连接 GitHub 的 Chat 使用。
- [配置、任务协议与 API](docs/V2-MVP2.md)：完整字段及恢复边界。

每台电脑设置不同的 `host_id`，例如 `desktop`、`laptop` 或 `office-pc`；任务必须精确匹配它。`desktop` 是机器标识，模型型号另填。监听凭据可访问的本人仓库，任务 Issue 可发在目标仓库或本机配置的记录仓库；新仓库有初始提交并开启 Issues 后无需逐个登记。

当前默认命令是 `codex-github-local-v2`，直接运行最新协议。`codex-github-local-v2-mvp2` 是同一入口的兼容别名。工作台默认读取最新状态，启动后访问 http://127.0.0.1:8791/ 。

## 三种模式

| 模式 | 执行方式 |
|---|---|
| `gpt` | 已登录的本机 Codex CLI，指定 GPT 型号与思考强度 |
| `api` | 本机登记的 OpenAI 兼容其它模型，提供受授权路径约束的文件工具 |
| `gpt-led` | GPT 主导，通过 MCP 咨询登记的其它模型并作最终判断 |

另有鉴权的本机文本协作 API，支持这三种模式。CLI 的 GPT 使用 Codex 登录；HTTP 的 GPT 使用独立 OpenAI API key。其它模型的接口、型号、思考参数映射和密钥变量名在本机登记，真实密钥仅由进程环境提供。

任务支持配置并发，新安装示例为 3；同一对话串行。手机在 Issue 正文填 `/codex run desktop` 后写任务即可，不必填写 UUID/SHA；评论 `/codex status` 查进度，直接留言追加指示，`/codex retry` 原地续跑，`/codex stop` 停止，`/codex merge` 合并成果 PR。默认不设任务/API 时长、上下文/日志/响应大小或输出 token 预算，临时故障保留现场恢复。API 文件工具支持大文件、分页、分块、命令和测试。

已有 0.1.0 的 schema 3/4 状态按[升级步骤](docs/V2-MVP2.md#并发配置与升级)备份并迁移到 schema 5，保留原任务、授权和会话。公开配置通用，实际接口、密钥、任务和成果保留本机。

## 目录

| 路径 | 用途 |
|---|---|
| `codex-github-local-v2/` | 当前执行端、模型协作 API、只读工作台与测试 |
| `web/app/` | 当前前端；默认真实数据，演示须显式选择 |
| `docs/` | 当前安装、使用和协议说明 |
| [history/v1](history/v1/README.md) | V1 完整源码、测试、旧手册和旧 CI 快照 |
| [history/v2](history/v2/README.md) | 早期 V2 设计、MVP-0 / MVP-1 说明与示例 |

历史版本已退出当前安装入口，旧 CI 不再作为活跃工作流。当前执行端复用的内部模块及回归测试继续保留。已有安装的数据库、会话和成果留在原运行目录；本仓库整理不会迁移或重放它们。

[模块边界](docs/INTEGRATION.md)与[验证范围](docs/VALIDATION.md)说明当前实现及测试限度。本仓库不保存真实配置、凭据、任务数据库、业务工作区或原始模型日志。第三方素材归属见 [NOTICE](web/app/NOTICE.md)；项目整体许可证尚未另行指定。
