# 验证范围

## MVP-2 功能交付（2026-10-04，本电脑）

本轮亲自执行的检查：Ubuntu / WSL V2 后端 **200 项**、V1 回归 **53 项**全部通过，无跳过；前端构建和 **15 项**单元测试通过；**23 项**浏览器测试通过（原有 22 项，加 MVP-2 会话、型号/effort、hub Issue 和 PR 展示测试）。浏览器测试使用可控数据。

真实 GitHub 与本机执行链路通过：

- hub Issue → 新 GPT CLI 对话 → 本地文件 → commit/push → 目标仓库草稿 PR → 原 Issue 回执。
- 目标仓库 Issue → 精确续接同一会话 UUID → 在新工作目录写出上一轮仅在对话中给出的校验码 → PR 与回执。新一轮任务没有重复提供校验码，确认保留对话上下文。
- GPT CLI 主导 → 本轮 MCP 工具 → 本地 OpenAI 兼容模拟 API → GPT 按咨询结果写文件 → PR 与回执。
- 其它 API 单独执行 → 本地 OpenAI 兼容模拟 API 文件工具 → PR 与回执；没有启动 Codex CLI 或调用 GPT。

后两项验证了协议及执行端协作，但**没有调用真实第三方厂商 API**。本机没有配置真实第三方密钥，也没有配置独立 OpenAI HTTP API key；HTTP 三种模式、Responses reasoning/function call 回放、effort 映射、鉴权和文件权限使用本地 HTTP 测试服务验证。GPT CLI 使用本机已有 ChatGPT 登录，真实调用已通过。

首轮 GPT 主导 smoke 因 MCP 未继承密钥变量而失败，原失败任务和回执保留。补充显式环境变量名转发及回归测试后，以新 request_id 验证通过；没有编辑或重放已冻结任务。

当前本机 `desktop` 监听、只读工作台和鉴权模型 API 已作为 WSL 用户服务启动，成功发现 12 个可用的本人仓库，轮询无仓库错误。安装采用独立 V2 0.1.0 环境和 schema 3 状态。旧监听器确认无未完成任务后停止；原数据库和成果保留。

详细链接、commit、session_id 与本机部署摘要见 [codex-cli MVP-2 真机记录](https://github.com/xiangshui001/codex-cli/blob/desktop-mvp2-records-20261004/docs/MVP2_DESKTOP_SMOKE_2026-10-04.md)，可能需要该仓库权限。真实配置、凭据、任务数据库、工作目录和原始模型日志不进入公开工具仓库。

## 范围限制

验证范围是当前电脑的 Ubuntu / WSL、GitHub 账号与本机浏览器，不能代表其它电脑。用户服务在 WSL 启动后自动运行；没有安装 Windows 开机或唤醒任务，没有验证远程访问或完整断电恢复。

API 单独执行仅提供受授权路径约束的文件工具，不提供任意 shell；生成文件不代表已运行项目测试。工作台只读，HTTP API 仅作文本协作。PR 为草稿，仍需人工审查合并。无文件变化时不创建空 PR。

## 历史阶段

MVP-0 / MVP-1 阶段性结论见 [MVP0_RESULT](MVP0_RESULT.md)、[MVP1_RESULT](MVP1_RESULT.md)；之前工作台真机记录见 [工作台验证](https://github.com/xiangshui001/codex-cli/blob/workbench-records-20261004/docs/WORKBENCH_SMOKE_2026-10-04.md)。旧阶段测试数量、分支状态与用户回传证据只描述当时情况，不能代替本轮亲自执行结果。

[历史验证档案](../history/VALIDATION-20260928.md)及 `validation/` 下 JSON 继续保留为当时证据。
