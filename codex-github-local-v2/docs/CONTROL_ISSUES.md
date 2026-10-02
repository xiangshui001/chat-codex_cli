# GitHub Control Issues

v2 把“执行一个代码任务”和“改变本地 Codex CLI / watcher 默认状态”分成两类 Issue。

普通任务使用 [codex] Issue；控制任务使用 [codex-control] Issue。控制命令由 Local Controller 自己确定性执行，不需要调用 Codex 模型。

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

status 不改变默认模型。未来 GitHub adapter 应向 Issue 回写脱敏状态：

- paused / running / idle
- runtime settings revision
- executor 默认 model + effort
- reviewer 默认 model + effort
- 当前 task ID 与阶段（若存在）
- 最后一次 control Issue

不得回传 token、认证文件、完整本机路径、环境变量内容或原始模型日志。

## GitHub adapter 必须做的校验

未来 watcher 接入控制 Issue 时至少要满足：

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

当前原型已经实现：控制协议解析、RuntimeSettings、幂等 apply 逻辑。

当前尚未实现：GitHub watcher 对 control Issue 的实际轮询、真实 Codex model preflight、runtime settings 原子落盘和 GitHub 回执。
