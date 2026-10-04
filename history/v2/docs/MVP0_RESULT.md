> 历史档案：以下记录旧阶段，不作为当前安装说明。[当前版本入口](../../../README.md)。

> MVP-0 历史验证阶段；当前推荐使用 [MVP-1](V2-MVP1.md)，保留此文作为证据入口。

# MVP-0 结果与验证记录

按用户要求，详细实现与验收记录保存在独立的 `codex-cli` 仓库：

**[MVP-0 本电脑 Ubuntu / WSL2 真实验证记录（2026-10-04）](https://github.com/xiangshui001/codex-cli/blob/mvp0-smoke-20261004/docs/MVP0_SMOKE_2026-10-04.md)**

记录包含实现结构、Issue 协议、SQLite schema、poller、Codex 调用、防重复机制、各环境测试结果、真实 Issue / 回执 / 生成文件、当前限制和 MVP-1 建议。

本电脑真实核心链路已成功，重复轮询两次没有再次执行 Codex。**此结论不代表台式机 WSL 已验证。** 原始日志、运行配置与登录凭据仅保存在本机。

本仓库继续维护 [MVP-0 范围与使用说明](V2-MVP.md) 和原有完整 V2 设计；本轮不扩大到 M1～M5。
