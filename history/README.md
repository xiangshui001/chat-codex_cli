# 历史资料索引

这些资料保留当时结论，不作为当前安装说明。最新入口见[仓库主页](../README.md)。

- [V1 使用手册](../docs/v1/用户使用手册.md) / [V1 Chat 手册](../docs/v1/Chat协作手册.md)：仅供现役 V1 使用。
- [2026-09-28 验证记录](VALIDATION-20260928.md)与 [发布清单](PUBLICATION-20260928.json)：清单路径和哈希对应当时快照，不对应当前目录。
- [2026-10-02 集成决策](INTEGRATION-20261002.md) / [Harness 验证](HARNESS_VALIDATION-20261002.md)：保留原型阶段证据。
- [前端早期交接](frontend/HANDOFF.md) / [组件库交接](frontend/LIBRARY_HANDOFF.md)。
- `../validation/` 下 JSON 为历史脱敏证据，不能当作本轮运行结果。

## 原迁移记录

# 历史与迁移

1. 启动包 1.1 已修复：配置读取/哈希/快照的一致绑定；预检 blocked 的持久报告；原进程组的退出确认。进程组清理不覆盖主动脱离该组的后代，不等于操作系统隔离。
2. 退出码补丁让 run-once 和 watch 的本轮 blocked 返回 1；正常待审阅及空闲仍返回 0。新增 9 项测试，合计 30 项。补丁是历史参考，当前引擎已包含，不要再次应用。
3. GitHub 本地协作 0.1.0 增加单机串行领取、授权评论校验、分支与 PR 发布、人工 merge commit 后核对同步；23 项新增测试与原 30 项共 53 项。
4. 增补原生 CLI 交互操作手册。手动 Issue 不进入自动队列；不同克隆使用同一远端，仍需协调主线变化。
5. 2026-09-28 归档为公开管理仓库：将项目专属 profile 替换为通用 example.json，调整安装入口默认 profile 和测试读取路径；执行器、桥接核心与 schema 保持原字节。两份手册改为通用路径，真实业务记录只保留脱敏结论。

`codex-github-local/tests/upstream/` 是原启动演示的测试夹具，使用最小适配后的引擎，不是生产业务仓库。原始与适配引擎的差异摘要在 validation/historical/engine-delta.json。
