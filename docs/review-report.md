# 整仓审查报告

审查日期：2026-10-05。当前基线：`c14cda01551d3f71c620852bc9a0e1db6b5a5cc6`。本报告续接 Issue #17 的调查；前轮基线为 `9dd497f4c56c8ae6a400b0ec2cea2a5fda8479f1`，已比较两者的 Git 差异和文件内容。仅更新本报告，代码修复与 GitHub 发布由后续授权和本机控制器处理。

共确认 8 项问题：2 项 P1、5 项 P2、1 项 P3。P1 表示影响执行安全或候选一致性，应优先修复；P2 表示特定条件下的交付、恢复、超时或状态错误；P3 表示观察信息不完整。全部问题均核对当前行号，并在当前源码的隔离副本中定向复现。

## 问题索引

| 编号 | 严重程度 | 问题 | 当前文件位置 |
| --- | --- | --- | --- |
| R01 | P1 | 发布重试前未冻结已验证的文件内容，可发布后来替换的成果 | `codex-github-local-v2/src/codex_github_local_v2/mvp2.py:76–79,142–155,301–305` |
| R02 | P1 | 只等待进程组 leader，却记录整个进程组已清理 | `codex-github-local-v2/src/codex_github_local_v2/mvp0_runner.py:55–69,112–118` |
| R03 | P2 | 授权产物被 Git 忽略时，错误地按无变更完成 | `codex-github-local-v2/src/codex_github_local_v2/mvp0.py:419–430`；`codex-github-local-v2/src/codex_github_local_v2/mvp2.py:142–147` |
| R04 | P2 | API 会话只绑定 provider 名，协议变化后仍回放旧格式 | `codex-github-local-v2/src/codex_github_local_v2/mvp2.py:64–74,209–218,270–277`；`codex-github-local-v2/src/codex_github_local_v2/mvp2_runner.py:175–178` |
| R05 | P2 | 读取授权评论的网络错误被归为拒绝，检查状态仍可显示正常 | `codex-github-local-v2/src/codex_github_local_v2/mvp2.py:362–386,435–436`；`codex-github-local-v2/src/codex_github_local_v2/listener_status.py:67–72` |
| R06 | P2 | API 响应读取没有总截止控制，超时后的最终响应仍算成功 | `codex-github-local-v2/src/codex_github_local_v2/model_api.py:125–133`；`codex-github-local-v2/src/codex_github_local_v2/mvp2_runner.py:202–215` |
| R07 | P2 | 工具输出超过 1 MiB 后仍先发送下一次模型请求 | `codex-github-local-v2/src/codex_github_local_v2/mvp2_runner.py:202–206,225,234–236` |
| R08 | P3 | 长任务详情仅显示最早 500 条事件，遗漏完成阶段且无截断提示 | `codex-github-local-v2/src/codex_github_local_v2/workbench.py:193–197`；`web/app/client/LiveWorkbench.tsx:505–514` |

## 可复核问题与建议

### R01：发布恢复可替换执行完成时的成果（P1）

位置：[mvp2.py](../codex-github-local-v2/src/codex_github_local_v2/mvp2.py)，第 76–79、142–155、301–305 行。

执行检查通过后，数据库仅记录 `execution_completed=1` 与 `publication_state=pending`，没有记录文件内容、文件类型或待发布树的摘要。若第一次发布在 commit 前因 GitHub 查询失败而退出，恢复时重新读取可变工作目录；`check_changes()` 只检查 HEAD、路径与符号链接，无法识别授权路径内的内容已经变化。

前轮离线复现并在当前基线重跑：授权 `docs/check.txt`，先完成路径检查并记录执行完成；模拟第一次发布的 `github_transport_unavailable`，将该文件内容替换后再次发布。结果为 `pending → succeeded`，临时 Git 仓库中的候选提交包含替换内容。push、PR 和回执均使用替身，没有真实远端写入。

建议：在标记执行完成前冻结待发布树或包含内容摘要、模式及删除项的清单，并将摘要与完成标志原子记录。首次提交及重试都必须核对同一候选；内容变化应保留现场并要求人工核对。补充“commit 前网络失败后替换、删除或增加授权文件”的回归；不能重新调用模型、编辑冻结任务或 force push 绕过校验。

### R02：进程清理证据没有确认整个原进程组消失（P1）

位置：[mvp0_runner.py](../codex-github-local-v2/src/codex_github_local_v2/mvp0_runner.py)，第 55–69、112–118 行；当前 MVP-2 的 `SessionCodexRunner` 继承此实现。

`_stop_group()` 向原组发送 TERM/KILL 后，只调用 `proc.wait()` 等待 leader。leader 已退出时，这些等待立即返回；代码没有检查原组是否仍存在，却写入 `cleanup=process_group_terminated`。`process_cleanup_failed` 的阻塞分支只在清理调用抛异常时触发，因此没有覆盖“信号已发送，但整组退出未确认”的情况。

前轮真实本地子进程复现并在当前基线重跑：离线 CLI 替身创建同组子进程并正常输出 `turn.completed`。清理返回 `Execution(error=None)`，证据记录已清理；此时 `killpg(original_pgid, 0)` 仍成功。观察到的遗留子进程处于待回收状态，诊断进程随后将其回收。没有调用模型；本证据不声称观察到了仍在写业务文件的活进程。

建议：在有界等待内检查原组消失及 leader 回收，保存 PGID、已发信号、组存在性、错误和确认结果；无法确认时保留运行槽并停止接单。归档 [runner.py](../history/v1/codex-github-local/engine/runner.py) 第 77–131 行已有该类确认结构，可作为参考。主动脱离原组的进程属于另一个隔离边界，本项复现针对原组本身。修改核心执行边界应设计独立版本迁移并补充真实 POSIX 子进程回归。

### R03：Git 忽略规则使授权产物被误判为无文件变化（P2）

位置：[mvp0.py](../codex-github-local-v2/src/codex_github_local_v2/mvp0.py)，第 419–430 行；[mvp2.py](../codex-github-local-v2/src/codex_github_local_v2/mvp2.py)，第 142–147 行。

新文件检测使用 `git ls-files --others --exclude-standard`。任务即使明确授权某个文件，它仍会被仓库或本机全局忽略规则排除；随后发布端把空列表记录为 `no_changes`，完成回执称没有文件变化，也不创建 PR。

前轮离线复现并在当前基线重跑：通过仅作用于临时 Git 命令的 `core.excludesFile` 忽略 `docs/check.txt`，创建该授权文件后 `changes()` 返回空列表，路径检查通过，发布结果为 `no_changes`。文件实际存在。本轮没有更改工作仓库或用户 Git 配置。

建议：区别“授权交付文件被忽略”和普通测试缓存。在执行前明确拒绝无法交付的忽略路径，或在执行后独立识别授权文件的实际变化并给出诊断；发布策略须显式处理这类文件。不能为此统一强制添加所有忽略文件，尤其不能把凭据、运行记录或缓存带入 PR。补充仓库忽略规则与全局忽略规则两种回归。

### R04：API 续接未绑定消息协议（P2）

位置：[mvp2.py](../codex-github-local-v2/src/codex_github_local_v2/mvp2.py)，第 64–74、209–218、270–277 行；[mvp2_runner.py](../codex-github-local-v2/src/codex_github_local_v2/mvp2_runner.py)，第 175–178 行。

会话表的后端标识仅为 provider 字符串，恢复时不核对原任务冻结的 `wire_api`。若本机保留 provider ID 而将其从 `responses` 改为 `chat_completions`，旧 Responses 的 reasoning、function-call 或输出项仍会原样放入新接口的 `messages`。这与协议文档要求避免不兼容消息回放的边界不一致。

前轮离线复现并在当前基线重跑：保存含 Responses reasoning 项的 API 会话，使用同名 provider 的 Chat Completions 配置续接，`check_session()` 接受；注入内存 opener 后观察到旧 reasoning 项被放入请求的 `messages`。没有访问外部 API；真实服务对此请求的响应未验证。

建议：将 provider ID、消息协议及上下文格式版本绑定到会话。协议不一致时在模型请求前拒绝；需要转换时采用独立、可审查的迁移，不修改旧冻结任务。补充两个方向的协议变化、相同协议正常续接及未知上下文版本的回归。

### R05：评论读取失败没有计入监听检查错误（P2）

位置：[mvp2.py](../codex-github-local-v2/src/codex_github_local_v2/mvp2.py)，第 362–386、435–436 行；[listener_status.py](../codex-github-local-v2/src/codex_github_local_v2/listener_status.py)，第 67–72 行。

初次读取评论、领取前重读评论或仓库身份查询抛出传输错误时，与授权或配置错误共用 `task_rejected` 分支，没有增加 `self.errors`。新增工作台投影会把此类 Issue 放入未领取列表，但本轮仍可能记录 `error_count=0`、`phase=idle`；没有已领取任务时，`--once` 的退出判定也可能返回成功。网络失败使本轮无法判断授权是否合法，不能视为完成正常检查。

前轮离线复现并在当前基线重跑：令待处理 Issue 的 `comments()` 抛出 `github_transport_unavailable`，轮询返回 `0`、错误计数为 `0`，没有执行模型。本轮进一步读取 `DesktopReader.overview()`，确认 `monitor.phase=idle`、`error_count=0`，拒绝原因则为 `github_transport_unavailable`；以相同 GitHub 替身执行 `main(... --once)`，实际退出码也为 `0`。

建议：区分授权拒绝与 GitHub 查询失败。查询失败应增加检查错误计数、保留可复查原因，并让 `--once` 返回非零；连续监听可只重试只读检查，不能重放执行任务。补充评论列表、领取前二次读取和身份查询失败的状态与退出码回归。

### R06：慢速 API 响应可越过总执行时限（P2）

位置：[model_api.py](../codex-github-local-v2/src/codex_github_local_v2/model_api.py)，第 125–133 行；[mvp2_runner.py](../codex-github-local-v2/src/codex_github_local_v2/mvp2_runner.py)，第 202–215 行。

`ModelClient.call()` 只把剩余时长传给 `opener.open(timeout=...)`，随后一次性读取整个响应，没有在读取期间核对单调时钟截止点。底层单次 I/O 的等待限制不能保证整次请求在相同时长内结束。返回后，文件执行端只在处理工具调用时再次检查 deadline；没有工具调用的最终响应可以直接返回成功。新增加的 `model_request_timeout` 分类因此没有覆盖这条超时路径。

当前基线离线复现：通过标准库 `HTTPResponse` 解析本地慢速字节流，每段延迟 0.008 秒；总执行预算 0.05 秒，实际约 0.204 秒后返回最终响应，结果仍为 `Execution(error=None)`。传给 opener 的 timeout 约为 0.0499 秒。没有创建 socket 或调用外部模型；该复现确认执行端接受逾期返回，真实网络的逐段响应行为未在此环境测试。

建议：以单调时钟控制连接、响应体读取和请求完成的总时长，截止后真正停止读取并释放串行执行槽；接收响应后再次检查任务 deadline，禁止逾期成功或继续工具写入。区分单次模型请求超时与整个任务超时，保留不自动重试付费请求的规则。补充持续小段数据、临近截止最终响应和工具响应的回归；仅在返回后检查仍不能解决读取永久占用的问题。

### R07：上下文超过上限后仍发生下一次请求（P2）

位置：[mvp2_runner.py](../codex-github-local-v2/src/codex_github_local_v2/mvp2_runner.py)，第 202–206、225、234–236 行。

1 MiB 上限只在模型响应加入 history 后检查，文件工具结果加入 history 时没有检查；下一轮又先调用模型再检查。取消每轮文件操作次数上限后，一批合法的读文件结果就能越界，超限上下文仍会进入下一次可能付费的请求。若请求成功，最终才报 `api_context_limit`；若服务拒绝，诊断会先变成模型 HTTP 错误。越界 history 也不会保存为 `context.json`。

当前基线离线复现：一轮读取同一个 65,536 字节文件 17 次。下一轮捕获到的请求 history 为 1,117,888 字节，大于 1,048,576 字节限制；已发生第二次替身请求，随后才返回 `api_context_limit`，未保存 context。没有真实费用产生。

建议：在请求之前及每次追加工具结果之后检查大小，并在处理批量调用前评估剩余上下文空间；超限时停止外部请求，保存有界诊断和已交付文件。需要压缩或分段时显式设计上下文策略，不删除授权或截断必要消息来规避检查。补充大文件批量读取、工具结果恰好越界和超限后无额外请求的回归。此项不建议恢复已取消的任意操作次数上限。

### R08：长任务时间线隐藏后续执行与完成事件（P3）

位置：[workbench.py](../codex-github-local-v2/src/codex_github_local_v2/workbench.py)，第 193–197 行；[LiveWorkbench.tsx](../web/app/client/LiveWorkbench.tsx)，第 505–514 行。

详情查询使用 `ORDER BY id LIMIT 500`，一直取最早 500 条，而前端直接展示这份列表，没有截断标记或翻页。无限轮数下，每次请求、响应和文件操作都产生事件，长任务很容易超过此窗口；刷新也看不到后面的写入、完成或回执阶段。独立的 `activity` 字段能取最新一条，但不能补全详情时间线；任务最终状态本身仍可正确显示。

当前基线离线复现：临时状态库保存 505 条事件，详情返回 500 条；`finished` 和 `receipt_sent` 都不在 events 中，`activity.kind=receipt_sent`，接口没有 events 截断标记。本项验证了读取端返回值和前端映射，未执行浏览器测试。

建议：返回最近一页并保持页面内时间顺序，或提供基于事件 ID 的分页；明确提示窗口大小和历史截断。补充超过 500 条时完成阶段可见、翻页连续及刷新不会永久停在旧阶段的回归。

## 审查覆盖与验证范围

已覆盖当前执行端的协议解析、账号与 Host 路由、串行领取和 SQLite 状态、独立克隆、会话绑定、模型登记及文件工具、发布恢复和回执；也审查了保留的早期控制/迁移/Harness 模块、只读工作台、前端真实与演示入口、安装示例、文档生成与 CI。归档 V1 的桥接、引擎、安装器、候选核对和回归夹具已复用前轮审查。历史文档中的成功记录只作为历史描述。

当前基线比前轮新增或修改 17 个文件，集中于 API 操作上限/超时、监听状态、工作台和对应文档、测试；已逐项审查增量，没有从头重读已确认且未变化的文件。仓库清单共 193 个跟踪文件，清单核对不等于每个第三方文件都完成了逐行安全审计。

| 范围 | 覆盖方式与边界 |
| --- | --- |
| `codex-github-local-v2/src/`、`tests/` | 复用前轮模块审查；补查本轮 5 个变动/新增源文件与 2 个测试文件；运行全部后端测试及定向复现。 |
| `history/v1/`、`history/v2/`、历史移交与验证材料 | 复用未变化的桥接、引擎、安装、冻结候选与早期架构审查；重新执行 V1 回归。历史回传记录不是本轮测试证据。 |
| `web/app/` | 复用真实/演示入口、API 客户端、页面与本地资源的审查；补查工作台、样式和浏览器测试增量，并复现后端投影。没有运行前端构建、Vitest 或 Playwright。 |
| `docs/`、`scripts/`、示例与 `.github/` | 已读规定的四份入口文档并核对本轮文档差异；检查当前示例、离线 HTML、文档链接、发布/安装边界与 CI 配置。 |
| 第三方库、资产、截图、归属与历史 JSON 证据 | 检查集成与归属记录；未逐行审计第三方源码，也未把截图或历史 JSON 当作当前运行证明。 |

本轮亲自执行的验证（当前基线的隔离副本，Linux / Python 3.14.4）：

| 检查 | 结果 |
| --- | --- |
| `python3 -m unittest discover -s codex-github-local-v2/tests -v` | 共 209 项，181 项通过、28 项错误、0 项断言失败、0 跳过；28 项均因环境禁止创建 socket 而报 `PermissionError: [Errno 1] Operation not permitted`：Harness 9、模型 API 18、工作台 HTTP 服务 1。该命令退出码为 1。 |
| `python3 history/v1/codex-github-local/verify.py` | Linux / Python 3.14.4，53 项通过，0 跳过、0 失败、0 错误。 |
| `python3 scripts/check_docs.py` | 38 份 Markdown、离线 HTML、配置生成器和当前示例检查通过。 |
| 模型 API 的独立内存验证 | 在临时诊断中复用 17 个原测试的断言，替换 HTTP 服务夹具与 opener，17 项通过；包括新增无限次数、62 轮后交付报告、20 个同轮工具、预算提醒和超时分类。未纳入 HTTP 服务鉴权测试，不能替代原来的 socket 测试。 |
| 8 项问题定向复现 | R01–R05 使用当前源码重跑前轮诊断；增补 R05 状态投影及 R06–R08。远端与模型调用均用替身；R02 使用真实本地子进程并回收。 |
| 前端依赖准备 | 复用前轮相同 `package.json` / lockfile 的离线安装失败证据：`npm ci --offline --ignore-scripts` 报 `ENOTCACHED`，缺少 `why-is-node-running` 包。当前没有可用完整依赖，未宣称构建或浏览器测试通过。 |

前轮基线的后端结果为 201 项、178 通过、23 项 socket 错误；它仅用于续接与比较。本轮增加的 8 项测试中，3 项 MVP-2 状态测试通过，5 项模型 API 测试受同一 socket 限制；这些新增 API 断言已另行纳入内存验证。

增量行为核对：省略或设为 `null` 的 `max_turns` / `max_calls` 不限制次数，显式正整数仍有效；默认单次请求超时 600 秒，上限 3600 秒；API 上下文仍有 1 MiB 上限。安装示例和配置生成器显式设置总时限 3600 秒，底层 `AccountConfig` 在省略 `timeout_seconds` 时仍默认 900 秒。已有本机配置不会自动覆盖，应以实际配置为准。未把前次 900 秒停止误判为次数或额度错误。

验证在从本仓库复制的 `/tmp` 隔离副本中执行，日志及历史验证脚本生成的证据留在临时目录；Git 复现使用独立临时仓库。工作仓库只写本报告，没有提交、换分支、改 Git 配置、push、创建 PR 或部署，没有调用外部模型 API 或其他模型。

未覆盖真实 GitHub 发布、真实 GPT/第三方模型请求、完整断电恢复、原生 Windows/macOS、CI 的 Python 3.11 环境、前端动态运行、在线依赖漏洞审计与独立 wheel 安装冒烟（当前 Python 无 pip）。socket 限制导致后端全量命令未通过，不能声明完整 Linux 验证通过。本报告是上述范围内的审查结果，不是无缺陷保证。

本轮延续原因依据用户说明：前次因本机原 900 秒执行时限停止。报告未将其归因于模型轮数或额度错误。
