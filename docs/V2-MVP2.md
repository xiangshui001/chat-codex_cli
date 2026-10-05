# 当前协议：指定对话、模型协作、机器路由与 PR

V2 **0.1.0（MVP-2）** 是 main 的当前版本。默认命令 `codex-github-local-v2`，`codex-github-local-v2-mvp2` 为同一入口的兼容别名。旧源码和阶段说明已归档到 history。首次部署见[安装说明](安装说明.md)和[HTML 指南](使用指南.html)。新协议为 `[codex-v2-mvp2]` 和 `/codex-v2-mvp2 run`，当前执行数据库为 schema 4 的 `mvp2.sqlite3`。schema 3 可显式原地迁移；其它旧协议数据库不导入、覆盖或自动重放。

## 安装与账号监听

在 Linux / WSL 安装 Python 3.11+、已登录的 `gh` 和 `codex`。`gh api user --jq .login` 必须与 owner 相同。参考配置见 [mvp2-config.example.json](../codex-github-local-v2/examples/mvp2-config.example.json) 和 [models.example.json](../codex-github-local-v2/examples/models.example.json)。实际配置、凭据和模型日志保存在仓库外。

```bash
python3 -m venv /ABS/PRIVATE/mvp2-venv
/ABS/PRIVATE/mvp2-venv/bin/pip install ./codex-github-local-v2
/ABS/PRIVATE/mvp2-venv/bin/codex-github-local-v2 --config /ABS/PRIVATE/config.json --list-repos
/ABS/PRIVATE/mvp2-venv/bin/codex-github-local-v2 --config /ABS/PRIVATE/config.json
```

配置 `owner` 为本人账号，各电脑使用唯一 `host_id`，例如 **desktop**、**laptop**；任务必须精确匹配它。每轮完整分页扫描凭据可见的本人仓库；排除组织、协作者、归档、禁用或未开启 Issues 的仓库。新仓库无需登记，先有初始提交即可。所有仓库共用本机并发名额。GitHub 连接与执行端 gh 的授权分别配置，程序不自动提升权限。

## 并发配置与升级

在私有 config.json 设置 `"max_parallel_tasks": 3`，允许 1–16 的整数；省略时为 1，保留已有串行行为。新安装示例设为 3。它只限制同时执行的任务数，不限制一个任务内的模型操作次数。重启监听器后生效。名额满时其余 Issue 留在 GitHub，下一轮自动检查；无效参数和已失败任务不会自动重跑。

同一个旧会话一次只能运行一个任务，避免上下文覆盖；同一仓库的不同对话可在独立克隆与分支中并行。监听器持续扫描，工作台列出所有正在执行的任务、型号和最近活动。并发可能提高模型服务负载，遇到上游限流不会自动重发付费请求。

已有 schema 3 用户：先等待当前任务完成，停止监听器；保留原配置、状态和成果目录，在已安装新代码的环境中执行：

```bash
codex-github-local-v2 --config /ABS/PRIVATE/config.json --migrate-state
```

该命令持有控制器锁，先备份 SQLite，再将执行数据库升级至 schema 4；拒绝迁移未结束的任务，不修改原任务、授权或会话记录。桥接核心数据库不迁移。旧程序不支持 schema 4，回退代码时应保留新状态并使用升级前备份，不能把新运行记录自动重放到旧库。新版工作台只读兼容 schema 3 和 4。

worker 意外退出后，已完成且提交结果确定的任务只补做发布；执行/进程清理或 commit 不确定时暂停新领取，现有正常 worker 可以完成，未知任务不自动重跑。

`hub_repo` 是本机任务记录仓库，例如 `OWNER/codex-cli`。任务 Issue 可位于工作目标仓库，或 hub_repo；授权中的 `repo` 始终是**实际工作目标**。基线、克隆、commit 和 PR 针对目标仓库；回执返回原 Issue。其它本人仓库不能用来代发对第三个仓库的任务。

## 派单格式

### API 不完整回复与失败会话恢复

API 的截断、缺少完成标记、空回复、可恢复的格式错误或连接中断不再立即终止任务。保留已完成对话与工具结果，下一次请求要求继续；不执行不完整回复中的任何工具调用，要求模型重新给出完整指令，避免重复已成功操作。单次输出截断时，将预算逐步提高到 models.json 的 `recovery_max_output_tokens`（默认 32768，可设不低于 `max_output_tokens` 的值）；反复空回复逐步退避，最长每次等待 30 秒。恢复仍受任务总时限、上下文大小和用户自设有限轮数约束。鉴权错误、服务拒绝、内容过滤或超出授权路径不通过续写绕过。工作台记录恢复原因和新的输出预算，不公开原始模型内容。

用户明确要求继续某个已失败 API 任务时，先停止监听器，执行：

```bash
codex-github-local-v2 --config /ABS/PRIVATE/config.json --recover-api-session ORIGINAL_REQUEST_UUID
```

此命令只登记保留的上下文并返回 session_id，不执行旧任务、不修改旧授权、任务或交付记录。校验失败状态、本机/仓库/后端绑定、协议、会话元数据、私有上下文大小和完整工具结果序列；进程清理结果不确定的任务不允许恢复。随后按当前 main 基线发布新 Issue、新 request_id，使用 `session.mode: resume` 和返回的 session_id。新任务继续原对话，但不自动复制旧工作区未合并文件；如果旧任务已有必要成果，应先按用户授权处理它们。

Issue 标题以 `[codex-v2-mvp2]` 开头，Issue 和唯一授权评论均由 owner 发布。评论第一行必须为 `/codex-v2-mvp2 run`，评论不能编辑。

````text
/codex-v2-mvp2 run
```json
{
  "request_id": "6c9134d1-f6ae-49f3-bdfd-e3681c19e183",
  "host_id": "desktop",
  "repo": "OWNER/PROJECT",
  "base_sha": "0123456789abcdef0123456789abcdef01234567",
  "session": {"mode": "new"},
  "models": {
    "mode": "gpt",
    "primary": {"provider": "codex", "model": "gpt-6.1-sol", "effort": "high"}
  },
  "task": {
    "prompt": "新增 docs/check.txt，写入指定内容。",
    "write_paths": ["docs/check.txt"]
  }
}
```
````

示例 UUID、SHA、仓库与模型须换成实际值。`base_sha` 是派单时**目标仓库默认分支**的完整 40 位小写 SHA。领取前重新读取 Issue、授权评论和仓库身份；执行前后检查默认分支和基线。`host_id` 严格区分大小写，不匹配即不领取。`desktop` 是机器标识，与模型型号无关。

沿用明确相对路径、目录 `/` 后缀、拒绝绝对路径、`..`、`.git`、`.codex` 与通配符的规则。Issue 不能指定接口地址、密钥、环境变量、cwd 或 CLI 参数。

## 新对话与续接

新对话：`"session": {"mode": "new"}`。CLI 新建持久化会话，回执和工作台返回实际 `session_id`。

旧对话：`"session": {"mode": "resume", "id": "完整会话 UUID"}`。GPT 模式使用 `codex exec resume <UUID>`。只接受明确 UUID，不使用 `--last`，避免续错电脑或仓库的对话。已有会话绑定 Host、目标仓库 ID 和执行后端；其它 API 模式续接本机保存的消息历史。API 会话不能当作 Codex 会话使用，也不能切换 provider 后重放不兼容的消息格式。

允许导入本机已有的 Codex CLI 对话：UUID 必须在该执行用户的 `CODEX_HOME` 中有有效 rollout，原工作目录的 Git origin 必须与目标仓库一致。不存在或来源不匹配时拒绝，不悄悄创建新对话。新任务依然使用独立克隆与当前基线；**续接的是对话上下文，不是旧目录未提交的代码**。GPT 本轮的路径权限以新任务为准。

## 三种模型模式

| mode | primary | 行为 |
|---|---|---|
| `gpt` | `provider: codex`，指定 GPT 型号与 effort | 本机已登录 Codex CLI 执行，仅使用指定 GPT；本轮不挂接其它模型 MCP |
| `api` | 本机登记的 `kind: other` provider | 直接调用兼容 API；文件工具读取/写入/删除授权路径；不启动 Codex、不调用 GPT |
| `gpt-led` | `provider: codex`，指定 GPT 型号与 effort | GPT 主导执行，通过本轮专属 MCP `consult_model` 工具选择外部模型并提问，评估结果后自行实现 |

其它模型示例：

```json
{"mode": "api", "primary": {"provider": "other", "model": "OTHER_MODEL", "effort": "high"}}
```

GPT 主导示例：

```json
{
  "mode": "gpt-led",
  "primary": {"provider": "codex", "model": "gpt-6.1-sol", "effort": "high"},
  "collaborators": [
    {"provider": "other", "model": "OTHER_MODEL", "effort": "medium"}
  ]
}
```

模型列表、`base_url`、密钥环境变量名、协议与 effort 映射由本机 models.json 登记。更改配置或密钥环境后重启监听器和模型 API；已经领取的任务仍使用冻结快照。第三方默认 `chat_completions`；官方 OpenAI HTTP 接口用 `responses`，保留 function call 与 reasoning 输出项用于后续工具调用。不同服务的思考参数可通过 `reasoning_parameter` 和 `effort_map` 映射。只有登记的 effort 才可选择；映射为 null 表示本机明确选择不发送该参数，程序不会擅自降档。

GPT CLI 使用既有登录，不需要 OpenAI API key。HTTP 的 GPT 模式需独立 OpenAI API key。`OTHER_MODEL_API_KEY` 等真实值由运行服务的环境提供；JSON 仅保存变量名。每轮保存无密钥配置快照。缺少密钥、未知 provider/模型或 effort 时在执行前拒绝。

协作者只获得 GPT 明确提交的问题；它们作为顾问返回回答，不能直接获得文件工具或控制 PR。GPT 决定是否调用和调用次数，并承担最终判断；外部调用上限由本机 `max_calls` 配置。其它模型单独执行时提供受路径约束的文件工具，不提供任意 shell；其最终回答不代表测试已运行。CLI sandbox 与事后 Git 检查保留，文件路径约束不是完整容器隔离。

## 本机 HTTP API

### API 仓库任务的轮数

models.json 的 max_turns 和 max_calls 默认 null，表示不设模型回复轮数和协作调用次数上限；API 文件工具也不设每轮操作次数上限。模型可以继续探索并写出交付物。需要自行设预算时可配置正整数，有限轮数下最后三轮会提醒交付。整仓审查应在报告中明确实际覆盖范围，未检查的部分不能声称已审查。仍受总执行时限和上下文大小限制。默认单次请求超时为 600 秒，可配置至 3600 秒；超时报告 model_request_timeout，不自动重试付费请求。

已有配置中的显式 max_turns / max_calls 不会被升级覆盖，取消次数限制需本机设为 null，再重启监听器和模型 API；已领取任务的冻结配置保持原样。有限预算耗尽仍报告 model_turn_limit，不将未完成任务当作成功。失败任务保留受大小限制的私有 context.json 和轮数诊断，不登记为可恢复会话、不自动重跑。核对后可用新的 request_id 和当前 main 基线发布新任务。

```bash
export CODEX_COLLABORATION_TOKEN='<至少 32 个 ASCII 字符的随机本机令牌>'
# 同时在当前进程环境设置各 provider 所需的 API key
/ABS/PRIVATE/mvp2-venv/bin/codex-github-local-v2-model-api \
  --models-file /ABS/PRIVATE/models.json --port 8792
```

仅绑定 `127.0.0.1`。所有请求需 `Authorization: Bearer <本机令牌>`，拒绝浏览器 Origin 和错误 Host；令牌与模型密钥不放入 Issue。不自动进行收费请求重试。

| 接口 | 用途 |
|---|---|
| `GET /health` | 服务和三种模式可用性 |
| `GET /v1/models` | 本机登记的 provider、型号和 effort；不返回密钥或地址 |
| `POST /v1/respond` | JSON `{ "prompt": "...", "models": {...} }`，返回 mode、model、text 和 collaboration_calls |

HTTP 模式使用 provider ID；GPT 模式 primary 选本机登记的 `kind: gpt` provider（例如 `openai`），不是 `codex`。`gpt-led` 时 GPT 经 Responses function calling 决定调用外部模型，再综合最终答案；`api` 时只调用其它模型。接口是文本协作服务，**不会修改工作目录或发布 GitHub 任务**。要执行仓库工作，使用上述 Issue 协议。请求大小、模型返回体、输出 token 和调用时限有限制；轮数和协作调用次数可自行配置预算，默认不设次数限制。截断或未完成的模型结果不当作成功。

## 本地成果、PR 与恢复

工作目录为 `workspace_root/<目标仓库 ID>/<request_id>/`，分支为 `codex-mvp2/<host_id>/<request_id>`。执行结束检查授权路径、基线与工作目录，随后由控制器提交、推送并创建**草稿 PR**。PR 发到目标仓库，回执发到 Issue 所在仓库；回执包含会话 ID、commit 与 PR 链接。PR 仍需人工审查和合并。无文件变化时不制造空 PR，回执明确说明。

网络错误时保留本地文件和发布进度。确认模型执行已完成的任务可只补做 push、查找/创建 PR 和回执；PR POST 或评论 POST 响应丢失后先查询已有对象，不重新执行模型、不 force push。模型执行途中中断、进程清理不确定或 commit 结果不确定则停止领取，要求人工核对。不清空数据库、不自动重放或 rebase。账号改名/仓库转移、基线变化、目标分支冲突都会被检查。

## 工作台

构建 `web/app` 后启动：

```bash
/ABS/PRIVATE/mvp2-venv/bin/codex-github-local-v2-workbench \
  --protocol mvp2 --config /ABS/PRIVATE/config.json --dist /ABS/SOURCE/web/app/dist --port 8791
```

浏览器打开 `http://127.0.0.1:8791/`。显示真实任务、会话 ID、模型/思考强度、发布阶段和 PR；已提交的文件变化相对任务基线展示。hub 派单时 Issue 链接仍指向 hub。工作台继续只读，不是模型 API 的写入口。

监听器原子更新本机私有 listener-status.json（version 1），记录检查阶段、仓库数量、检查完成时间、下次检查时间及最多 50 项未领取原因。它是可选的状态投影，不修改任务数据库结构、冻结授权或历史任务，也不产生自动重放。旧安装缺少记录时明确显示尚无检查详情；身份不匹配或无效记录不展示。页面每 3 秒读取本机状态，区分页面刷新与 GitHub 检查。API 任务的当前轮数、等待模型回复和文件操作来自真实运行事件，不输出模型内部推理或文件正文。

官方接口依据：[Codex CLI 会话与参数](https://learn.chatgpt.com/docs/developer-commands?surface=cli)、[MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)、[Responses function calling](https://developers.openai.com/api/docs/guides/function-calling)。实际型号/effort 是否可用由账号和 provider 决定，未在代码中假定所有型号支持所有强度。

MVP-2 的 `timeout_seconds` 可设为 1–10800 秒，当前安装示例为 10800 秒（3 小时）。这是单个任务的总执行时限，与模型单次 API 请求超时分开。已有执行使用启动时的时限；修改本机配置后须在任务结束、监听器空闲时重启监听服务，新任务才使用新值。

Codex CLI 执行日志默认不设大小上限，超过 16 MiB 或 1 GiB 不会因日志大小终止任务。输出直接写入本机文件，完成检查按行读取日志。工作台仍分页显示日志，完整日志留在本机；任务总时限仍由 `timeout_seconds` 决定。
