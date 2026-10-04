> 历史档案：以下记录旧阶段，不作为当前安装说明。[当前版本入口](../../../README.md)。

# MVP-1：账号内仓库发现与按需工作区

在 MVP-0 上增加单个个人账号名下仓库自动发现、授权后按需克隆、所有仓库共用串行队列。V1 和 MVP-0 入口保留，不实现完整 M1～M5、模型 API、多 Host、自动 PR / merge 或完整恢复。0.0.6 新增[本机只读工作台](MVP1-WORKBENCH.md)，可查看真实执行过程，不提供执行控制。

## 授权与新仓库

Ubuntu 的 gh 必须登录为配置的 owner。每轮读取登录用户和 `user/repos?affiliation=owner` 完整分页，核对 owner 账号 ID 和名称，只纳入凭据可见、本人拥有、未归档 / 禁用且开启 Issues 的仓库。组织和协作者仓库不纳入。

新仓库在下一轮自动发现，不必逐个登记；没有任务的仓库不会克隆。**派单前必须有初始提交**，才能提供 base_sha；创建仓库时可以初始化 README。本轮不自动初始化空仓库或修改默认分支。

Chat 的 GitHub 连接与 Ubuntu gh 是两套授权。若其中一端只获准访问选定仓库，需要让该端也覆盖新仓库；程序不会自动提升权限。当前功能需要读代码与读写 Issues，不需要删除仓库或账号管理权限。

## 安装与配置

V2 0.0.6，执行目标为 Linux / WSL，独立虚拟环境安装：

```bash
python3 -m venv /ABS/PATH/mvp1-venv
/ABS/PATH/mvp1-venv/bin/pip install ./codex-github-local-v2
```

把 [配置示例](../examples/mvp1-config.example.json) 复制到本机私有目录：

```json
{
  "owner": "OWNER",
  "host_id": "my-host-mvp1",
  "workspace_root": "/home/USER/codex-managed-workspaces",
  "state_dir": "/home/USER/.local/state/chat-codex-mvp1",
  "poll_seconds": 60,
  "timeout_seconds": 900
}
```

目录必须是绝对路径，状态目录与工作区根目录不能嵌套。数据库绑定 owner 账号 ID / 名称、host_id 和工作区根目录，不能在已有状态上切换绑定。真实配置、凭据、原始日志不提交仓库。

```bash
# 只读发现：不克隆、不执行
/ABS/PATH/mvp1-venv/bin/codex-github-local-v2-mvp1 --config /ABS/PATH/mvp1-config.json --list-repos

# 一轮最多执行一个任务
/ABS/PATH/mvp1-venv/bin/codex-github-local-v2-mvp1 --config /ABS/PATH/mvp1-config.json --once

# 持续轮询
/ABS/PATH/mvp1-venv/bin/codex-github-local-v2-mvp1 --config /ABS/PATH/mvp1-config.json
```

默认每轮处理完等待 60 秒，长任务会推迟下一轮。`--once` 遇到任务失败、待补回执、部分仓库读取失败返回非零。Ctrl+C / SIGTERM 尝试清理后退出。本轮没有自启动安装器、Windows 唤醒或电源管理。

## Chat 派单

使用独立前缀，防止新数据库重放旧 MVP-0 Issue。旧数据库不升级、不清空、不导入。

在目标仓库创建标题以 **`[codex-v2-mvp1]`** 开头的开放 Issue，添加唯一、未编辑的授权评论。Issue 和评论作者都必须是配置的 owner：

````text
/codex-v2-mvp1 run
```json
{
  "request_id": "6c9134d1-f6ae-49f3-bdfd-e3681c19e183",
  "host_id": "my-host-mvp1",
  "repo": "OWNER/REPOSITORY",
  "base_sha": "0123456789abcdef0123456789abcdef01234567",
  "task": {
    "prompt": "仅新增 docs/check.txt，写入指定测试内容。",
    "write_paths": ["docs/check.txt"]
  }
}
```
````

示例 UUID / SHA 必须换成实际值。base_sha 为发布时目标仓库**默认分支**的完整 SHA。执行前后都检查 owner、repository ID、默认分支和 SHA；基线变化回执 stale_base，不自动 rebase。

沿用 MVP-0 严格校验：规范 UUID、匹配 Host / repo、40 位小写 SHA、非空 prompt、相对 write_paths。未知字段、重复 JSON 键、绝对路径、`..`、`.git`、`.codex`、通配符和编辑授权拒绝。任务不能指定 cwd、CLI 参数或模型设置。

## 工作区与成果

协议通过并在 SQLite 领取成功后，才创建：

```text
workspace_root/<GitHub repository ID>/<request_id>/
```

每个任务使用独立克隆与 `codex-mvp1/<request_id>` 分支。路径由登记根目录、数字 ID 和已验证 UUID 生成；已有目录和 symlink 不覆盖，失败克隆保留人工检查。不会清理或重置其他任务。私有仓库通过现有 gh 登录克隆，token 不进入 argv 或报告。

沿用真实 `codex exec --json`、stdin 任务、独立 stdout / stderr、版本 / cwd / 时间 / exit code、超时、日志上限及进程组清理。成果留在任务目录，状态写回原仓库 Issue。用户检查 diff 后决定提交、推送和合并。**下一任务从新的已发布默认分支基线开始，不自动继承上一任务的未提交修改。**

write_paths 是输入约束和事后 Git 检查，不是容器或逐路径内核隔离。只有本人明确授权才会执行，普通 Issue 或他人评论不会派单。

## 状态与边界

独立 `mvp1.sqlite3` 使用 schema 2：沿用 tasks / events，增加仅一行绑定信息的 settings。状态仍为 queued/running/succeeded/failed/stale_base。

所有仓库共用 request_id 唯一约束、repository_id + issue_id 唯一约束、一个活动任务槽、状态目录锁和工作区根目录锁。不要使用不同状态目录 / 根目录并行启动同一 Host。先持久化领取，再克隆、启动；跨仓库按 Issue ID 先后选择任务。

重启发现 queued/running 或清理不确定，停止所有仓库接单，人工核对，不自动重放。回执按 repository ID 核对并路由，改名 / 转移 / 名称复用不会把结果发到其他仓库。只读 API 短暂错误最多尝试 3 次；评论 POST 不盲目重试，下轮先查已有回执。

单仓库不可读取会明确记错，其他仓库仍可处理。全量发现失败不假装列表完整。没有高级 rate-limit 调度、完整 outbox、取消协议、自动清理或断电恢复。

详细结果按用户要求放在 `codex-cli`，见 [记录入口](MVP1_RESULT.md)。本电脑 / CI 的通过结论不能代替台式机 WSL 验收。

GitHub 接口依据：[List repositories for the authenticated user](https://docs.github.com/en/rest/repos/repos#list-repositories-for-the-authenticated-user)。
