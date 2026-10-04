# Chat 协作手册：MVP-1

当前执行协议是 `[codex-v2-mvp1]`，完整字段示例见 [MVP-1 派单协议](V2-MVP1.md#chat-派单)。V1 使用者改读 [V1 Chat 手册](v1/Chat协作手册.md)，不要混用前缀和授权评论。

## 发布任务

1. 从用户授权中明确目标仓库、登记的 host_id、任务要求与允许写入的相对路径。只向当前配置 owner 拥有且凭据可访问的仓库派单。
2. 读取目标仓库默认分支当前完整 40 位 SHA；空仓库必须先有初始提交。为本任务生成新的规范 UUID request_id。
3. 创建标题以 `[codex-v2-mvp1]` 开头的开放 Issue。Issue 作者和授权评论作者均须为配置 owner。
4. 添加唯一、未编辑的授权评论，第一行 `/codex-v2-mvp1 run`，随后 JSON 仅含 `request_id`、`host_id`、`repo`、`base_sha`、`task`；task 仅含 `prompt` 和 `write_paths`。不要添加未来设计中的字段。
5. 向用户提供 Issue 链接，通过机器回执确认执行结果；需查看过程时打开本机工作台。

write_paths 使用明确相对路径；拒绝绝对路径、父目录跳转、保留目录和通配符。不要在任务里传凭据、环境变量、任意 cwd、CLI 参数或远程模型设置。

## 判断结果

状态仅为 queued / running / succeeded / failed / stale_base。`succeeded` 表示本轮 CLI 和检查完成，不意味着成果已经推送、PR 已创建或用户已验收。使用回执、文件变化和用户验收判断成果，不以演示页面或生成 Issue 本身当作实际执行证明。

不要编辑已授权评论重试，不要重用 request_id，不要删库解锁。失败或 stale_base 后先核对原因、基线与已有文件，再按用户授权决定是否发布新的任务。重启遗留未完成任务需人工核对。

当前工作台只读，没有取消、重跑、远程模型设置、自动 PR / merge。完整 V2 文档是未来目标；当前功能以 [用户手册](用户使用手册.md)和 [MVP-1 协议](V2-MVP1.md)为准。
