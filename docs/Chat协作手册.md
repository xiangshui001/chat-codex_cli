# Chat 协作手册：手机派单与原对话续跑

优先使用手机简化协议，完整说明见[MVP-2](V2-MVP2.md)。账号、机器标识、模型和密钥映射按执行端配置，不假定所有电脑相同。

## 新任务

1. 明确目标仓库、电脑 host_id、任务范围、新/旧对话及型号/思考强度。
2. 在 owner 的目标仓库创建 Issue，或在目标电脑配置的 hub_repo 创建 Issue 并指定 repo。
3. 正文第一行 `/codex run HOST_ID`，后接可选头部和任务文字。整仓范围填 `paths: .`；审查只写报告可填报告路径。电脑自动冻结领取时的 SHA 并生成任务编号。
4. API 模式指定本机登记的 provider、model、effort；GPT 主导模式加一行 collaborators JSON。接口地址和密钥留在电脑，不公开到 Issue。
5. 给用户 Issue 链接，读取领取回执与进度。未知型号/错误参数会在领取前回复原因，修正未领取正文后继续检查。

示例：

```text
/codex run desktop
model: gpt-6.1-sol
effort: high
paths: .

完成用户要求，运行适当检查，保存本地成果、创建 PR 并回复这个 Issue。
```

## 同一 Issue 的新指示

用户要求“继续”“补充”“调整”时，优先在原 Issue 追加 owner 评论；不用新 Issue、新 UUID 或重新克隆。运行中评论送入原对话，已结束任务开启下一轮并保留旧结果快照。原始冻结授权不编辑。

查询进度用 `/codex status`，它不消耗模型生成调用，也不触发续跑。`/codex retry` 原地续跑；`/codex allow .` 明确扩大范围；`/codex stop` 停止；用户授权合并时发送 `/codex merge`。不要为了查看状态把普通指令文字误发成追加任务。

临时网络故障、空回复或输出截断会自动保留上下文恢复；等待期间读取 Issue 的状态，不发布重复任务。服务鉴权、型号或参数拒绝不会因为次数上限取消，需修正实际接口问题。升级前缺乏可确认进程记录的旧任务由 owner 评论 `/codex retry` 明确恢复。

## 成果与兼容性

成功回执包含会话 ID、commit 和成果 PR，PR 发到目标仓库，回执回到原 Issue。同一 Issue 续跑复用当前目录和未合并成果；全新 Issue 续接对话则使用独立工作区，不自动带入其它工作区的未合并文件。

原完整 `/codex-v2-mvp2 run` JSON 授权仍兼容，使用它时保留唯一未编辑授权、正确仓库/Host、基线 SHA 与 request_id。不要删除数据库、force push 或伪造执行结果。PR 合并须遵守用户授权和 GitHub 分支保护。
