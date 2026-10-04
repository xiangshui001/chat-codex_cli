# MVP-1 验证记录入口

本轮增加单账号仓库自动发现、授权后按需克隆、跨仓库串行防重复执行。实现与使用说明见 [V2-MVP1](V2-MVP1.md)。

详细记录按用户要求保存在 **[codex-cli：MVP-1 本电脑验证](https://github.com/xiangshui001/codex-cli/blob/mvp1-records-20261004/docs/MVP1_SMOKE_2026-10-04.md)**，包含环境、实现、协议、SQLite、真实 Issue / 回执、Codex 进程与文件证据、重复轮询、使用方法及限制。

本轮本电脑 Ubuntu V2 153 项、V1 53 项全部通过，无跳过；[代码 CI](https://github.com/xiangshui001/chat-codex_cli/actions/runs/37194571453) 通过。Windows MVP 测试发现 71 项，执行 63 项、POSIX 跳过 8 项。

真实 smoke 已完成：配置不变时发现新建私有仓库，两个安全仓库各通过 Chat 发布一个任务，本机真实 Codex CLI 串行执行、文件与回执核对成功；额外两轮未重复启动。没有使用替身冒充 smoke。原 main、设计分支、V1 与 MVP-0 分支保留。

**这些是本电脑与 CI 的验证结果，不能代表台式机 WSL 已通过。** 台式机仍需独立验收。程序不提供自动启动 / 唤醒、自动 PR / merge 或完整故障恢复。
