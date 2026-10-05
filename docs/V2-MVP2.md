# 当前协议：手机派单、持续对话与成果交付

V2 **0.2.0（MVP-2，engine schema 5）** 是当前版本。默认命令 `codex-github-local-v2`，`codex-github-local-v2-mvp2` 是兼容别名。旧版本资料保留在 history。首次部署见[安装说明](安装说明.md)，离线操作说明见[HTML 指南](使用指南.html)。

## 手机直接派单

在工作仓库新建 Issue，正文这样写，标题可自行命名：

```text
/codex run desktop
model: gpt-6.1-sol
effort: high
paths: .

这里写具体任务。完成后保存文件，提交 PR，并把结果回复到这个 Issue。
```

`desktop` 换成目标电脑的唯一 `host_id`。型号与思考强度按执行机实际能力填写。省略头部配置时使用 GPT、`gpt-6.1-sol`、`medium`、新对话、整个仓库。电脑自动生成任务编号并冻结领取时的默认分支 SHA，无需手机填写 UUID 或 SHA。Issue 和后续指示必须来自配置的 owner。

Issue 可以发布在目标仓库，也可发布在本机 `hub_repo`（例如 `OWNER/codex-cli`）；在记录仓库派单时增加 `repo: OWNER/PROJECT`。监听本人拥有且凭据可见、启用 Issues、未归档的全部仓库。目标仓库需有初始提交。

可选头部：`repo`、`mode`、`provider`、`model`、`effort`、`session`、`paths`、`collaborators`。只解析任务文字前的头部。`session: new` 创建对话，或填明确会话 UUID；路径用逗号分隔，目录以 `/` 结尾。`paths: .` 允许整仓；`./`、`*`、`/` 在范围字段也归一成整仓。外部模型需显式提供本机登记的 provider/model/effort：

```text
/codex run desktop
mode: api
provider: other
model: OTHER_MODEL
effort: high
paths: docs/review-report.md

审查整个仓库，把问题、位置、严重程度和建议写入报告并提交 PR。
```

GPT 主导模式增加 `mode: gpt-led` 与一行 JSON，例如 `collaborators: [{"provider":"other","model":"OTHER_MODEL","effort":"medium"}]`。接口地址与密钥在本机配置，不能放入 Issue。

## 同一个 Issue 继续交谈

电脑领取后立即提交领取回执，记录机器、型号与思考强度。后续直接在原 Issue 评论，电脑会确认收到，并送入原对话。运行几小时后仍可追加要求。完成后继续评论也会使用同一目录和对话开启下一轮，原任务/授权和上一轮结果快照保留。

| 留言 | 行为 |
|---|---|
| 任意任务文字，或 `/codex say 新指示` | 运行中追加到原对话；完成/失败后从保留的现场继续 |
| `/codex status`，或单独留言“进度” | 回复当前阶段、最近活动、模型和 PR；不调用模型，不重跑任务 |
| `/codex retry` | 在原目录、原对话续跑；不会重新复制一份任务 |
| `/codex allow .` | 明确扩大到整个仓库；也可逐行列出新增相对路径 |
| `/codex stop` | 停止当前模型、命令或 Git 操作，清理进程并保留文件/对话 |
| `/codex merge` | 将当前成果 PR 转为可合并并尝试合并；冲突/检查/保护状态会回复 Issue |

只接收 owner 的新评论，其他人不能指挥电脑。控制器自己的回执不会被当成新任务；重复读取不重复应用。同一对话串行，其它对话并行。回复使用持久化发件箱，GitHub 暂时故障后继续补发，未知 POST 结果先核对，避免重复回执。

默认每 15 分钟把结构化进度回写 Issue，`progress_seconds` 可调整。手机随时查进度，无需打开仅本机可用的 127.0.0.1 工作台。评论检查间隔由 `poll_seconds` 决定；电脑须开机、联网且监听器正在运行。

## 时长、数据与工具

当前默认没有任务时长、Git 操作时长、单次模型请求时长、日志大小、上下文文件大小、模型响应正文大小或本机输出 token 预算上限。`timeout_seconds`、models.json 的 `request_timeout`、`max_output_tokens`、`recovery_max_output_tokens`、`max_turns`、`max_calls` 设为 `null` 表示不设该预算；省略时同样不设。可自行设置正整数，不设程序规定的最大值。已有显式预算不会被静默覆盖，升级时按需要改为 null。

API 提供 `list_files`（offset/limit 分页）、`read_file`（字节 offset/length，UTF-8 或 base64）、`write_file`（完整写入或 append 分块）、`delete_file`、`run_command`（argv 数组、cwd、可选自定 timeout）、`read_command_output`。文件数量、单次读写大小及协作模型数量不再有固定上限。包含隐藏目录和依赖目录；跳过 `.git` 与符号链接目录以避免环路。仓库内密钥文件不再有专门禁止访问名单；请在任务中明确需要的工作范围，控制器发送公开回复前会遮盖常见凭据格式。

命令输出直接写本机文件，返回预览与 command_id；完整输出可分段读取，预览截断不终止命令。工作台分页和 GitHub 评论拆分也只控制显示，不限制任务数据。大数据仍受本机磁盘/内存、模型服务商的上下文与输出容量影响。

API 截断、空回复、缺少完成标记、传输故障、429/5xx 会保留历史并退避续写；不执行截断工具指令。400/401/403/404 等服务拒绝会保留现场并持续等待重试，同时在 Issue 提示鉴权、模型或参数问题；它们不会因重试次数耗尽而取消，恢复需上游可用或配置修正。内容过滤、用户明确停止仍会结束当前轮。没有宣称本机设置能够取消服务商限制。

上下文在每次模型回复和工具结果后原子保存，完整历史不因大小被丢弃。已确认工具结果有独立记录；崩溃时未确认的命令/追加写入由模型先核对现有现场，避免盲目重复副作用。

## 新对话与续接

GPT 使用已安装 Codex CLI 的 **app-server**，通过 `thread/start` / `thread/resume` 与 `turn/start` / `turn/steer` 保持对话并接收运行中指示。只接受明确会话 UUID，不使用 `--last`。旧对话须存在本机且绑定目标仓库、电脑、后端；不同 API 协议不能混用历史。新任务独立克隆，原 Issue 的后续轮则复用原工作目录。

连接或轮次临时失败会退避后在原 thread 继续。监听器重启先验证 worker 身份；仍在运行的 worker 不重复启动，已退出 worker 的任务在清理已确认归属的遗留进程后恢复。升级前遗留、缺少可确认执行记录的任务只暂停自身，在 Issue 提示 `/codex retry`；不冻结其它任务。

## 三种模型模式

| mode | 执行 |
|---|---|
| `gpt` | 本机 Codex 登录，指定 GPT 型号与 effort |
| `api` | 本机登记的 `kind: other` OpenAI 兼容 API，操作文件并执行命令/测试 |
| `gpt-led` | GPT 主导，调用任务专属 MCP 顾问，评估回复并实现 |

GPT 主导的 `consult_model` 启动后台咨询并返回 job_id，`get_consultation` 立即返回状态/结果，因此外部模型长时间思考不会被单次 MCP 工具等待截断。外部顾问仅收到 GPT 提交的问题，不直接获得文件工具。协作调用配置不含真实密钥。

provider 的 `base_url`、`api_key_env`、`wire_api`、`models`、`reasoning_parameter` 和 `effort_map` 见[模型示例](../codex-github-local-v2/examples/models.example.json)。`wire_api` 支持 `chat_completions` 与 `responses`。effort_map 值为 null 表示该模式不发送思考参数；模型名和 effort 必须按本机登记值精确填写。更改配置/密钥环境后重启服务；已领取的原始快照保留，owner 发起的新续跑轮单独冻结当前模型配置。

## 并发配置与升级

`max_parallel_tasks` 新安装示例为 3，省略为 1，可设任意正整数，实际并发取决于电脑与账号。每个任务有独立进程、目录、分支；同一会话排队，不丢弃指示。`full_access: true` 让 Codex 使用完整本机权限；省略/false 使用 workspace-write。公开示例不包含任何用户的真实账号或密钥。`auto_merge` 默认 false；可设 true 自动尝试合并，或从手机发送 `/codex merge`。

0.1.0 的 schema 3/4 升级前等待监听器空闲、停止服务并备份运行目录，在现有虚拟环境安装 0.2.0，再运行：

```bash
"$run_dir/venv/bin/python" -m pip install --upgrade ./codex-github-local-v2
"$run_dir/venv/bin/codex-github-local-v2" --config "$run_dir/config.json" --migrate-state
```

迁移命令持有控制器锁，先备份 SQLite，再升级 schema 5；保留原任务、授权、会话、成果，新建 Issue 收件/回执/续跑历史表。拒绝对运行中的旧引擎迁移。然后按上文取消私有配置的旧预算并重启服务。工作台只读兼容 schema 3/4/5。历史任务的旧评论不会在升级时被当成新指示。回退旧代码需使用迁移前备份，不把新事件重放到旧数据库。

## 权限、仓库与成果发布

保留 owner 身份、目标仓库归属和 host_id 路由，避免陌生人或另一台电脑领取任务。只使用目标仓库内相对路径，拒绝 `..`、绝对路径和越界符号链接；仓库内符号链接可正常使用。`.git`/`.codex` 不作为文件工具的普通任务路径，Git 操作通过命令和控制器完成。范围使用 `.` 后不会因文件数、路径条数或路径长度的人为上限拒绝。

允许在当前任务分支执行命令、测试和本地提交；发布核对仓库身份、分支、提交为冻结基线的后代及整段变更范围。main 在任务执行期间更新不会导致 `stale_base` 阻断；PR 正常以领取的基线创建。不会强推覆盖无关远端分支。外部修改/冲突会在 Issue 报告；owner 可追加解决指示。PR 创建/回执暂时失败只补做发布，不重新调用模型。提交响应不确定时核对已生成提交再继续，不丢弃成果。

目录为 `workspace_root/<目标仓库 ID>/<request_id>/`，分支 `codex-mvp2/<host_id>/<request_id>`。完成后保存本地成果、推送分支、创建草稿 PR 并回复原 Issue；无改动时不创建空 PR。同一 Issue 新一轮可继续更新未合并的 PR；旧 PR 已合并后有新成果会创建新 PR。合并遵守 GitHub 的分支保护与检查。

## 兼容的完整授权格式

原 `[codex-v2-mvp2]` 标题与 owner 唯一未编辑 `/codex-v2-mvp2 run` 授权评论仍支持。JSON 顶层字段为 request_id、host_id、repo、base_sha、session、models、task；task 含 prompt 与 write_paths。手机新用户可直接用正文派单。

```json
{"request_id":"6c9134d1-f6ae-49f3-bdfd-e3681c19e183","host_id":"desktop","repo":"OWNER/PROJECT","base_sha":"0123456789abcdef0123456789abcdef01234567","session":{"mode":"new"},"models":{"mode":"gpt","primary":{"provider":"codex","model":"gpt-6.1-sol","effort":"high"}},"task":{"prompt":"完成明确的仓库任务并提交 PR","write_paths":["."]}}
```

旧授权不能通过编辑改变已冻结任务；新要求通过原 Issue 的新评论进入收件箱。授权过多、账号/仓库不匹配或未知型号会在领取前拒绝并回写原因，修正未领取手机派单正文后自动重新检查。

## 本机 HTTP API

```bash
codex-github-local-v2-model-api --models-file /ABS/PRIVATE/models.json --port 8792
```

仅绑定 127.0.0.1，需本机随机 `CODEX_COLLABORATION_TOKEN`，请求携带 Bearer；拒绝浏览器 Origin/错误 Host。`GET /health`、`GET /v1/models`、`POST /v1/respond`（JSON `{"prompt":"...","models":{...}}`）提供文本协作，不直接派发仓库任务。HTTP 的 GPT 需要登记 kind:gpt provider 和独立 API key，CLI 登录不能代替它。HTTP 使用线程服务，长请求不会堵住其它请求，默认不设数据/时长预算。

## 工作台

构建 web/app，运行 `codex-github-local-v2-workbench --config ... --dist ... --port 8791`。工作台只读显示真实执行事件、并行任务、模型、Git 进度、恢复和追加指示；分页预览不删除完整日志，不公开内部推理。手机的日常入口是 GitHub Issue，127.0.0.1 仅在执行机可直接访问。

接口依据：[Codex app-server](https://learn.chatgpt.com/docs/app-server)、[MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)、[Responses function calling](https://developers.openai.com/api/docs/guides/function-calling)。验收范围见[VALIDATION](VALIDATION.md)。
