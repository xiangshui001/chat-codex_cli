# DSH → chat-codex v2 前端适配设计

设计目标：保留 DSH 的侧栏、内容区、详情区及基础控件体验，以现有 v2 的任务和
控制语义构建管理界面。浏览器只展示服务端投影、提交控制意图；v2 继续决定权限、
模型探测、任务领取、快照与执行。

## 读取基线

| 对象 | 本轮实际读取的版本 |
| --- | --- |
| 用户最新需求 | [Issue #3](https://github.com/xiangshui001/chat-codex_cli/issues/3) |
| 修改版 | [Draft PR #2](https://github.com/xiangshui001/chat-codex_cli/pull/2)，`prototype/orchestrator-v2` |
| v2 提交 | `fe4785840ee41f7df36c0bc3b186302c3d5dcaac`；包含 22 → 16 模块的简化 |
| main | `76e15db0c630f46f2d4aad832cdbe774b6946877`；当前没有 v2 目录 |
| DSH | [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)，`639ed015397290b3745d163aafe02ffee4aa3f84` |

已读项目 AGENTS、README、两份协作/用户手册、VALIDATION、V2 架构草案、控制
协议及 control/claim/contract/state/controller/evidence/Codex/Git adapter 等相关源码。
DSH 检查了 web-app 依赖、Web Client 文档、API Gateway 文档、host 包图及下列
组件源码。以上是源码研究，不证明用户台式机在线或真实模型可用。

Issue #3 指定实际实现使用 GPT-6.1 Sol。本提交按当前用户请求交付适配设计和离线
设计预览；该实现要求留在交接中，不声明更换了另一执行会话的模型。

## 从 DSH 取哪些部分

`packages/bundle/web-app/` 是组装大量 Host/Client 插件的 bundle，包含工作区、
终端、账户、Agent 等依赖。它不是单独可替换接口地址的前端模板。适配的起点应是
下列 UI 文件，而不是复制 web-app 的 package.json 或 Cordis patch。

| DSH 源码位置（均相对固定提交） | 研究结果 | 正式实现的取用方式 |
| --- | --- | --- |
| `packages/client/ui-primitives/src/Button.tsx`、`Button.module.css` | 仅 React、clsx、CSS；原生属性透传 | 选择性复制，保留 MIT notice；本预览只改写部分 CSS |
| `ui-primitives/src/Input.tsx`、`Input.module.css` | 相同的轻依赖；单行输入 | 同上，用于搜索与模型 ID 输入 |
| `ui-primitives/src/Pill.tsx`、`Pill.module.css` | 轻依赖；筛选与静态胶囊 | 同上；状态仍保留 v2 的原始枚举 |
| `ui-theme/src/styles/design-platform.css` | 亮/暗语义色、表面、控件 token；含品牌命名 | 只提取需要的中性色和语义色，改为本项目 token；不整包引入 theme 插件 |
| `ui-layout/src/client/AppFrame.tsx`、`columns.ts` | 布局组件依赖 Slots 注入、layout store、Panel runtime | 保留三列组织思路；用普通 React props 重写 AppShell |
| `ui-sidebar/src/client/SidebarRoot.tsx` | runtime/Slots、DSH 图标、品牌、工作区/会话服务 | 重写 Navigation；入口改为任务、模型、主机、证据 |
| `ui-model-selection/src/client/ModelSelect.tsx` | 依赖 DSH 模型目录、Session、Remote API 的 reasoning metadata | 本轮用薄表单重写；模型目录由未来 chat-codex API 提供 |
| `docs/subsystems/web-client.md` | Host 权威状态 → transport → model → UI 的边界 | 采用边界原则，不复制多层插件体系 |
| `docs/api-gateway.md` | Typert 生成、Cordis lookup、Remote 运行时与连接 carrier | 定义一个自己的 typed HTTP client；不导入 DSH Gateway |
| `packages/host/` | 提供 DSH WebServer、静态服务、目录选择、应用启动等 | 静态前端由未来 chat-codex API 服务承载；不复制 Host runtime |

路径缩写中的 `ui-*` 均指 `packages/client/ui-*`。可从上游固定提交定位，例如
[Button](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/packages/client/ui-primitives/src/Button.tsx)、
[AppFrame](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/packages/client/ui-layout/src/client/AppFrame.tsx)。

不取用 FishLogo、BrandWordmark、官方品牌插件、账户/计费 UI、品牌字体。只复制
确实需要的原子组件；不依赖 `ui-primitives` 的整个 barrel，避免把 markdown、
终端、图标和其他 UI 依赖全部带入。完整版权文本见 NOTICE 和 third-party 文件。

## 页面与交互

离线设计稿在 `index.html`。主导航固定，顶栏显示项目、数据来源、队列状态和
角色预览；桌面内容宽度受限，任务详情有独立证据区域。手机收起侧栏并使用遮罩，
表格在自己的容器内滚动，详情区向下排列。亮/暗主题使用本项目语义色。

| 入口 | 内容及动作 | 对应边界 |
| --- | --- | --- |
| Dashboard | 队列统计、当前任务、当前主机、默认模型、最近异常和 PR | 统计取服务端投影；运行中的模型取冻结快照 |
| Tasks | 关键词、状态筛选；任务 ID、状态、模型、更新时间、PR | 不将所有异常合并成 blocked；异常标签保留具体原因 |
| 任务详情 | 合同目标、读写范围、预算、状态时间线、检查、独立审阅、证据 | 已领取任务只读；缺失时间线明确为不完整 |
| Models | Executor/Reviewer 独立表单、model + effort、每角色的应用按钮 | 每次操作自然对应一个 `set-default-model` 命令 |
| Hosts | online/offline/busy/unknown、CLI 版本、当前任务、心跳 | 当前没有真实 host registry；先 mock |
| Evidence | raw/resolved 合同、runtime snapshot、events、检查/审阅摘要 | API 只暴露审核过的证据，不能把 runtime 目录直接当静态目录 |
| PR Review | Draft/普通 PR、检查和审阅摘要、返回任务详情 | 本轮只读；人工合并仍在 GitHub 完成 |
| Users / Roles | Owner、Admin/Operator、Reviewer、Viewer 权限矩阵 | 仅接口与 route guard；角色切换是设计演示 |

顶栏“暂停新任务”会显示“当前任务继续执行”。两个模型表单采用各自应用按钮，
避免让用户误以为不同 Executor/Reviewer 配置能一次原子提交。若以后添加共同
Apply，应顺序提交两个命令并明确部分成功，不能借助前端 Promise.all 假装事务。

模型 ID 为自由输入加候选目录；候选必须来自 Host 能力查询。预览中的模型名只是
示例，不证明账号 entitlement。effort 当前严格对应 v2 的 low/medium/high/xhigh；
未来候选可进一步由 Host 的模型能力约束。探测失败时保留已确认默认值，同时保留
用户的表单输入供修订。控件在命令等待期间禁止重复提交。

## 必须保留的 v2 语义

| 源码事实 | 设计处理 |
| --- | --- |
| `RuntimeSettings.to_dict()` 用 `executor/reviewer: {model, effort}` | Runtime DTO 保留这些键；不和 `ModelChoice: {name, effort}` 混用 |
| `freeze_claim()` 保存 `task.raw.json`、`task.resolved.json`、`runtime-settings.snapshot.json` | 展示冻结版本及 revision；模型应用后不刷新已领取任务的模型 |
| claim 只替换名为 `runtime-default` 的 choice | 默认值只影响未来领取的继承项；合同显式指定的模型继续生效 |
| evidence 中 raw/resolved 是 `asdict(TaskContract)` 的平铺结构 | 不能假定这两个文件仍是 `{version, repository, base_sha, task:{...}}` Issue 信封 |
| `pause` 不终止执行 | 文案使用“暂停新任务”，不出现“停止当前任务”按钮 |
| control 只有四种动作 | Command 为 discriminated union；拒绝任意 shell、配置键和 cancel 扩展 |
| `set-default-model` 先 preflight，后保存；失败不覆盖原值 | 收到 applied 之前不把输入画成已生效配置 |
| `control.id` 关联实际 GitHub Issue 号 | 浏览器不生成虚构 GH 编号；服务端分配命令身份 |
| control-ledger 防重放 | 请求超时显示“结果待确认”，按 request_id 查询；不创建新命令自动重试 |
| `RunRecord.events` 与 `EvidenceStore.append_event()` 是不同结构 | API 分别投影状态轨迹和审计 events；不声称现有 JSONL 包含所有状态变化 |
| `manual_review_required` 是过渡状态；验证不可用仍可能去 reviewing/PR | 页面保留 checks=unavailable；不因最后状态变化抹掉缺失验证 |
| 单实例控制器和串行操作 | Web/GitHub 通过同一控制流程；不建立第二个无锁 runtime 文件写入者 |

GitWorkspace 的创建/范围守卫已有实现和测试；完整普通任务 watcher、进程监督、
发布/接纳集成仍未完成。部分 README 的“尚无 worktree”表述早于该代码；设计以
本轮读取源码为准，同时不把孤立 adapter 说成完整链路已接通。

## 拟议 API 边界

以下路由和 DTO 是设计建议，当前仓库没有 HTTP 服务。见 `contracts.ts`。

| 路由 | client 方法 | v2 来源 / 待补能力 |
| --- | --- | --- |
| `GET /api/v2/session` | `getSession()` | 待实现会话、服务端角色/能力投影 |
| `GET /api/v2/runtime` | `getRuntimeStatus()` | RuntimeSettingsStore；controller/host 在线数据需新投影 |
| `GET /api/v2/tasks` | `listTasks()` | 合同、运行记录、证据的只读投影；没有现成任务列表 API |
| `GET /api/v2/tasks/{task_id}` | `getTask()` | raw/resolved、状态轨迹、检查和审阅摘要 |
| `GET /api/v2/hosts` | `listHosts()` | 待实现 registry；缺失字段返回 null/unknown |
| `GET /api/v2/tasks/{task_id}/evidence/{name}` | `getEvidence()` | EvidenceStore + 服务端 allowlist / 脱敏投影 |
| `POST /api/v2/controls` | `setDefaultModel/pauseQueue/resumeQueue/requestStatus()` | 四动作统一提交入口；返回 pending/回执标识 |
| `GET /api/v2/controls/{request_id}` | `getControlReceipt()` | GitHub 回执/ledger 映射；等待已提交命令的结果 |

表单提交示例（浏览器 → API）：

```json
{
  "request_id": "opaque-client-request-id",
  "repository": "OWNER/REPO",
  "intent": {
    "action": "set-default-model",
    "role": "executor",
    "model": "ACTUAL_HOST_MODEL_ID",
    "effort": "high",
    "reason": "future inherited tasks"
  }
}
```

API 以固定登记的 repository 校验输入，不允许客户端自行切到未登记仓库。
推荐第一个真实接入版本由服务端生成 Control Issue 和唯一未编辑授权评论，再由
现有 watcher 校验和执行。分配实际 Issue 号之后，才构造现有信封：

```json
{
  "version": 2,
  "repository": "OWNER/REPO",
  "control": {
    "id": "GH-实际Issue号",
    "action": "set-default-model",
    "role": "executor",
    "model": "ACTUAL_HOST_MODEL_ID",
    "effort": "high"
  }
}
```

这样保留当前 GitHub 唯一授权路径，也避免 Web 和 watcher 同时直接改设置。Web
API 创建评论的身份必须对应获准的人：先 owner 单人、服务端已登录身份；多人阶段
需明确用户身份映射/服务端 OAuth 授权。不能只用共享机器人 token 把 Viewer
输入变成 authorized author，也不能把 role 下拉菜单视为认证。

request_id 的幂等映射和双写崩溃恢复是新 API adapter 的责任，当前 core 尚未实现。
同一请求得到已有 Issue 号时复用映射；网络不确定时先查回执。最后返回的 settings
来自权威读取。现有 revision 是快照版本，不是 compare-and-swap 锁；未来若加入
防覆盖的版本检查，应明确新增服务端验证，而不是仅靠浏览器传 revision。

未来若改成直接 HTTP 控制，应先解决非 GH 身份、统一锁/ledger 和 Web 审计路径，
再修改协议。不要让一个 HTTP wrapper 擅自绕过 Issue 作者及不可变评论验证。

读取失败显示数据时间和连接状态；写入请求超时显示 unknown，403 清空可写能力。
真实 transport 出错时禁止自动降级为 mock，以免误报成功。事件更新初期用轮询
权威快照即可；等真实 API 存在后再决定 SSE，不预先复制 DSH 多路 RPC 协议。

## 认证与证据

| 角色 | 查看任务/主机/证据/PR | 更改模型与队列 | 查看成员管理 |
| --- | --- | --- | --- |
| Owner | 按仓库授权 | 是 | 是 |
| Admin / Operator | 按仓库授权 | 是 | 是（是否可改角色由后续服务端定义） |
| Reviewer | 按仓库授权 | 否 | 否 |
| Viewer | 按仓库授权 | 否 | 否 |

前端路由和按钮读取 API 返回的 capabilities，后端对每次读取、修改和证据请求
再次校验。设计稿只演示角色差异；不处理密码、真实登录、邀请或权限授予。

生产适配：会话由服务端管理，浏览器不持有 GitHub token/Codex auth；同源 HTTP
client 不接受任意 Host URL。证据以 task_id + 白名单 artifact name 查询，服务端
校验仓库/任务权限、路径归属与符号链接，先生成脱敏投影；不给原始模型 stdout、
环境、认证和配置文件提供公共下载。简单字符串替换不能代替脱敏/发布清单。
checks/reviewer 文件目前没有固定完整生成链，返回 missing/withheld，而非伪造通过。

## 实现结构和顺序

正式原型建议 React + TypeScript + Vite。最初保留六个有实际职责的单元即可：
`client/AppShell.tsx`、`client/useWorkspace.ts`、`features/WorkspaceViews.tsx`、
`api-client/types.ts`、`api-client/client.ts`、`api-client/mock.ts`，加静态 fixtures
和选择性抽取的 primitives。`client.ts` 是唯一 HTTP I/O 边界，useWorkspace
是唯一应用数据入口；页面不新建 service/manager/facade。mock 必須显式选择，
mock/live 不共存且不在失败时切换。页面变大后再按真实职责拆分。

1. GPT-6.1 Sol 读取 Issue #3、本设计及最新 v2；固定基线，确认没有其他执行器
   同时实现。v2 未合并时，新原型分支可依赖其分支，开独立 Draft PR；正式生产化
   则等所需 v2 进入 main，再从最新 main 建分支，不默认继承设计稿代码。
2. 实现 React 壳、统一 client 和 mock fixture。选择性抽取 Button/Input/Pill，
   重写 AppShell/Nav/模型表单；保留上游版权。先导航/build/交互验收。
3. 新建薄 API adapter，先只读 runtime + 允许发布的 evidence。需要任务列表、
   心跳或轨迹时补对应服务端数据源，不能用浏览器“推算已运行”。
4. owner 单人授权链接入四个控制动作：Web → Control Issue → watcher → receipt。
   验证探测失败、超时、重试幂等、双控制面顺序和已领取任务冻结。
5. 完成服务端身份/仓库权限/证据权限后，再接多人管理。人工 merge 继续保留。

## 验证和交接

本轮交付仅新增 `web/design/`，旧 0.1.0、v2 core、现有 CI 文件没有修改。
当前设计预览使用一个 mock API 对象和一个界面状态入口；模拟动作按表分派。
它只供布局、交互和语义讨论，不是已有真实服务的客户端。

验证结果在完成本轮检查后记录在下方。真实 Codex、真实 Host、HTTP API、多人
认证、GitHub Control Issue 端到端以及公网部署均不属于本设计预览的实际验证。

- `node web/design/check.mjs`：通过；内联 JS 语法、七路由、无远程资产、版权文本。
- TypeScript 5.9.3：`tsc --strict --noEmit --target ES2022 web/design/contracts.ts` 通过。
- Chromium 153.0.8010.0：27 组浏览器交互检查通过，包括导航、模型成功/失败、
  pending、Executor/Reviewer 独立提交、快照不变、pause/resume、角色只读及直接
  路由守卫、缺失证据、搜索/异常筛选、键盘搜索、亮暗主题、七个手机入口、离线
  file URL；无 page error、无远程资产请求。设计稿修复了键盘搜索跨页面后的焦点。
- 浏览器尺寸：桌面 1440 × 1080，手机 390 × 844；检查页面无横向溢出（表格在
  自己的滚动区域中）。截图已实际检查中文字体与布局。
- `python3 -m unittest discover -s codex-github-local-v2/tests -v`：48/48 通过。
- `python3 codex-github-local/verify.py`：53/53 通过，Linux、0 skipped；真实
  模型/GitHub 调用均为离线替身，不将这些回归描述为现场执行成功。

浏览器记录见 [screenshots/verification.json](screenshots/verification.json)。
截图：[桌面概览](screenshots/desktop-light.png)、[暗色模型设置](screenshots/desktop-dark-models.png)、
[手机任务详情](screenshots/mobile-task.png)。这些截图是模拟设计稿，不是生产界面。

任务：Issue #3 的适配设计参考。基线：上述固定提交。修改：新设计包。
检查：以上本轮实际结果。未运行：真实执行链及认证。风险：拟议 API 尚未实现。
部署：无。
