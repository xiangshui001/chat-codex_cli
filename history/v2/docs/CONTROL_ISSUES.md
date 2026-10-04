> 历史档案：以下记录旧阶段，不作为当前安装说明。[当前版本入口](../../../README.md)。

# GitHub Control Issues

v2 把“执行一个代码任务”和“改变本地 Codex CLI / watcher 默认状态”分成两类 Issue。

普通任务使用 [codex] Issue；控制任务使用 [codex-control] Issue。控制动作由 Local Controller 确定性执行。pause/resume/status 不调用模型；set-default-model 会先调用 Codex 做最小可用性探测，成功后才保存默认值。

## 第一版允许的动作

- set-default-model
- pause
- resume
- status

第一版故意不支持任意 shell、任意文件路径写入、密钥操作、部署、自动 merge 或强制终止进程。

## 通过 GitHub 改默认模型

Issue 标题：

    [codex-control] set default model

Issue 中放一条唯一且未编辑的控制评论：

    /codex-local control
    ~~~json
    {
      "version": 2,
      "repository": "OWNER/REPO",
      "control": {
        "id": "GH-43",
        "action": "set-default-model",
        "role": "both",
        "model": "ACTUAL_LOCAL_MODEL_ID",
        "effort": "high",
        "reason": "Switch future tasks to this model."
      }
    }
    ~~~

role 可以是 executor、reviewer、both。

## 关键语义：不热改正在运行的任务

Control Issue 改的是 runtime defaults。

- 已经 claimed 的任务继续使用领取时冻结的 config/model snapshot。
- 新默认值只影响之后领取的任务。
- 如果未来确实需要终止当前任务，应新增独立、强确认的 cancel-current 协议；改模型本身不能偷偷 kill 当前任务。

这可以保证每个 PR 的模型、配置和证据仍然可解释。

## pause / resume

pause 只阻止领取新任务，不会杀掉正在运行的 Codex：

    {
      "version": 2,
      "repository": "OWNER/REPO",
      "control": {
        "id": "GH-44",
        "action": "pause",
        "reason": "Temporarily stop claiming new work."
      }
    }

resume 恢复新任务领取：

    {
      "version": 2,
      "repository": "OWNER/REPO",
      "control": {
        "id": "GH-45",
        "action": "resume"
      }
    }

## status

status 不改变默认模型。当前控制 processor 会向 Issue 回写脱敏状态；完整 task watcher 接入后还会补当前任务阶段：

- paused / running / idle
- runtime settings revision
- executor 默认 model + effort
- reviewer 默认 model + effort
- 当前 task ID 与阶段（若存在）
- 最后一次 control Issue

不得回传 token、认证文件、完整本机路径、环境变量内容或原始模型日志。

## GitHub adapter 必须做的校验

当前控制 watcher 做以下校验；未来普通任务集成也须保留：

1. Issue 标题以 [codex-control] 开头。
2. Issue 作者属于 authorized_users。
3. 只有一条 /codex-local control 授权评论。
4. 评论作者属于 authorized_users。
5. 评论从创建后未编辑。
6. JSON repository 与本地登记仓库完全一致。
7. control.id 与实际 Issue 号一致。
8. 命令幂等；同一 control ID 不重复应用。
9. set-default-model 先做最小模型 preflight，成功后才原子提交 runtime defaults。
10. 成功和失败都记录审计事件并回写 GitHub 状态评论。

## 安全边界

Control Issue 是远程控制面，因此比普通代码任务更敏感：

- allowlist action，拒绝未知动作；
- 不提供 arbitrary shell；
- 不允许远程任意改 ~/.codex/config.toml 键；
- 不接受 secrets；
- 不修改已冻结任务；
- 不自动 merge、不部署；
- 模型切换失败时保持上一份已知可用配置。

当前原型已经实现：

- 控制协议严格解析与未知字段拒绝；
- authorized_users、Issue ID、repository、未编辑唯一授权评论校验；
- gh CLI 查询控制 Issue、读取评论和发布回执；
- Codex read-only 最小 model preflight；
- runtime-settings.json 原子写入，preflight 失败保持原配置；
- control-ledger.json 防止历史控制 Issue 重放；
- schema 2 保存控制 fingerprint、结果、原始 settings 回执及 delivered_at；
- 每次 tick 先恢复待投递回执，再读取新命令；失败不重复动作或 model preflight；
- 按完整回执与授权作者核对远端评论，恢复响应丢失或投递后的本地写入失败；
- 串行 ControlProcessor；
- remote control run-once/watch 命令入口；
- runtime-default 在新任务 claimed 时冻结为 resolved task；
- GitHub Actions 的 mock / offline 回归。

尚未完成的是把这套 control watcher 安装到用户台式机并做真实 GitHub→Codex 端到端现场验证，以及把它与完整 v2 普通代码任务 watcher 合并成一个单实例服务。

## 回执恢复与升级

ledger 中“已应用”和“已投递”是独立事实。发送前持久化的回执包含当时的状态
快照与唯一 control ID/fingerprint。失败后沿用该正文；当前设置或 Issue 开放状态
不改变已产生的结果。若已存在由 authorized_users 成员发布、未编辑、正文完全
相同的回执，只补本地投递标记。发送用的 gh 登录账号须在该名单中。

评论按每页 100 条分页读取；达到 100 页仍未结束时明确失败，不根据截断评论判断
回执不存在。回执持续失败时队列停在待投递结果，watch 会报告错误并在下次重试。

0.0.2 只接受 schema 2，旧 schema 1 保持原文件并报错。现场迁移必须停止旧
watcher、保留备份、核对历史动作与回执；不得通过删除 ledger 或换空 state-dir
绕过防重放。详情见 [README](../../../codex-github-local-v2/README.md)。
