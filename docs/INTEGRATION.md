# integration 维护基线

后续远程指挥与工作台的目标设计见 [V2设计方案](V2设计方案.md)。本文记录当前 integration 已有实现；两者不应混为已经完成的功能。

本地 `integration/maintenance-20261002` 从 PR #7 head 建立，已经包含 PR #2、#5
的祖先代码。第一阶段逐项保留可复用功能、修复两个确认缺陷、收拢边界。它不是
main 的发布状态，也没有整体 merge Draft PR。0.1.0 继续作为完整执行链基线。

## 模块职责

| 模块 | 当前路径/接口 | 职责与状态 |
| --- | --- | --- |
| CLI | `codex-github-local/bridge.py`、v2 `cli.py` / `remote_control.py` | 用户命令、会话/本地工作流、参数和组合入口；不按供应商名称分支 |
| 任务/控制 core | v2 `contract`、`policy`、`state`、`controller`、`control`、`claim` | 权限和范围、状态转换、动作、幂等 ledger/回执、领取快照；状态的单一来源 |
| 工作流 I/O | v2 `controller.Backend`、`git_workspace`、`evidence` | 执行/检查/审阅/发布及 Git/证据；Backend 是任务工作流，不是模型供应商 |
| Model backend | v2 `model_adapter.ModelAdapter`、`codex_adapter.CodexProbeRunner` | 供应商 I/O 和错误映射；目前仅可用性 probe 有真实 Codex subprocess 实现 |
| Harness / API | `web/app/api-client/{client,types,http}.ts`；v2 `github_protocol` / `gh_cli` / `harness` | typed 通信、状态/事件与控制；第二阶段已有隔离 local-smoke HTTP/core，生产 HTTP/GitHub 写入仍未接通 |
| React frontend | `web/app/client`、`features` | 导航、展示、表单草稿；只经 useWorkspace/ChatCodexClient 调用 Harness，不执行模型或写 runtime |
| Library / visual | `web/app/visual`、`primitives`、`public/tisu` | 独立视觉呈现；LibraryModel 不依赖任务/模型/控制状态；vendor 保持原件 |
| GitHub workflow | `.github/workflows`、Issue/PR 协议 | CI 验证与候选交付；人工决定合并，不能替代本地 watcher 或实际模型验证 |

```text
React pages → useWorkspace → ChatCodexClient
                               ├─ MockClient（显式演示/测试）
                               └─ HttpClient / local-smoke Harness（实际 HTTP/core）
                                       ↓ 隔离、确定性 source；生产 API 待实现
GitHub Issue/comment → gh_cli / github_protocol → control / claim / controller
                                                    ├─ GitWorkspace / Evidence
                                                    └─ model_adapter → Codex I/O
LibraryModel → 本地 TISU 场景（独立视觉生命周期）
```

ModelAdapter 的当前契约是 `(role, ModelChoice) -> ProbeResult`，供应商细节封装在
实现中，由组合入口注入。routing 只决定 primary/fallback；control 只决定何时
探测、保存和冻结。生成/流式能力等下一条真实后端路径出现后再按实际需求扩展，
不预设空 registry、fake DeepSeek provider 或供应商 if/else。

## 四个 Draft PR 的功能吸收

| PR / 固定 head | 分类 | integration 保留/吸收 | 不引入的内容 |
| --- | --- | --- | --- |
| [#2](https://github.com/xiangshui001/chat-codex_cli/pull/2) `fe478584` | CLI、backend adapter、GitHub Harness、config、tests | 16 模块收敛后的 v2 core、Codex/Git adapter、control/claim/evidence、示例与原 48 项测试；修复安装和回执并补安装 CI | 不恢复早期分支已淘汰的小模块，不把原型当作完整 v1 替代品 |
| [#4](https://github.com/xiangshui001/chat-codex_cli/pull/4) `184acd74` | Harness 契约建议、视觉设计、docs | 将状态权威、投影、授权、回执、组件来源/轻依赖原则整理到本文；React 已实现的布局/表单继续保留 | `web/design/index.html`、另一套 `contracts.ts`、mock 状态机、截图运行入口不复制；HTML 留远端作设计参考 |
| [#5](https://github.com/xiangshui001/chat-codex_cli/pull/5) `7697b29e` | React、Harness client/DTO、visual primitives、deployment config、tests | 一个 useWorkspace、ChatCodexClient、DTO、MockClient、页面/表单/路由、Vite/TS/锁文件和测试；保留 DSH 原子组件来源与 MIT notice | 不复制 DSH runtime、Cordis/Slots/store、Typert gateway 或官方品牌/账户 UI；不补第二套页面 service |
| [#7](https://github.com/xiangshui001/chat-codex_cli/pull/7) `5722e124` | React 登录演示、library visual、tests | 入口页、TISU 薄 wrapper、失败占位/清理、完整固定 vendor 和浏览器回归；wrapper 移到 visual | 不把演示入口当真实登录，不启用上游 tour/Web Component/demo 控件；完整上游目录仍保留来源要求 |

保留不等于 main 已合并：三组源码原已存在于 integration，本轮没有重复复制或
cherry-pick。#4 有价值的设计判断按主题吸收，并指向原稿，不建立第二份运行方案。
Issue #3 的前端原型与 #6 的外景入口已实现但仍待评审；真实 API/认证是后续任务。

## 从 DSH 设计稿吸收的边界

依据 [PR #4 适配设计](https://github.com/xiangshui001/chat-codex_cli/blob/184acd74da6c2f47a7037282d2a386249e8002f1/web/design/DSH_ADAPTATION.md)。
DSH 固定来源 `639ed015397290b3745d163aafe02ffee4aa3f84`，按轻依赖原子组件
选择性复用；布局、侧栏和 model form 用普通 React props 重写。具体文件和许可
保留在 [NOTICE](../web/app/NOTICE.md)。不整套复制 web-app/Host/Gateway 插件。

- runtime 用 `{model, effort}`，合同 ModelChoice 用 `{name, effort}`，API 显式投影。
- raw/resolved evidence 是平铺的 asdict(TaskContract)，不是 Issue 信封。
- 已领取模型和快照保持冻结；默认值变更影响未来继承项，pause 不杀当前任务。
- 提交不等于 applied；unknown 只查询同一个 request_id。真实失败不能切回 mock。
- 身份、capabilities、仓库和证据权限由服务端确认；角色下拉框只供演示。
- GitHub 与未来 HTTP 共用单一授权/控制写入路径；request_id ↔ GH-N 映射是 API
  的责任，不能另造无锁 runtime writer。revision 不是已实现的 CAS。
- RunRecord 状态轨迹和审计 JSONL 分开；未知 Host/catalog 观测用 null/unknown，
  不取 fixture 补成在线状态。证据由白名单与脱敏投影发布。

## DeepSeek 核查

目前 Harness 中没有真实 DeepSeek 或 OpenAI-compatible 后端调用，没有供应商
HTTP client、endpoint、credential 管理或生成流。DeepSeek 名称来自 DSH 的 UI
源码/样式版权和来源说明。`api-client/mock.ts` 是内存演示 transport；fixtures
的模型目录/Host/回执是虚构数据。`client/main.tsx` 默认注入 MockClient；显式
local-smoke query 注入 HttpClient，模型 probe 使用明确的确定性后端。

PR #4 的 `contracts.ts` 与 API 路由是设计建议，HTML script 是另一套演示实现。
仅保留 PR #5 的 typed client/DTO 作为当前契约，真实 API 不以 HTML/mock 为后端。
现有真实模型 I/O 是 Codex availability probe；不声称普通任务执行链或 DeepSeek
已接通。下一阶段供应商 adapter 持有 endpoint/认证/错误映射，React 和 CLI 只
消费契约；不能仅凭模型名把 Codex model 参数当成 DeepSeek 接入。

## 重复实现与验证

唯一活跃前端是 React；停止在 HTML 参考中平行实现功能。MockClient 是显式测试
替身，不是待保留的第二个生产控制器。v1 与 v2 是独立迁移版本，当前没有两条
完整可替代执行链；保留 v1。upstream runner 是来源回归夹具，不是另一套 launcher。
历史退出码 patch 已在 engine 中，不再次应用。TISU 未执行的文件为来源完整性
保留，不能按未导入就删除或改写 vendor。

Python CI 继续跑全部 v2 回归，并新增实际 wheel 构建、隔离安装、两个 console
入口与样例验证。0.1.0 继续用 verify.py。前端 Node >=22.12.0，优先 Node 24，
lockfileVersion=3；第一阶段缺 Node，第二阶段用户级 nvm/Node 24.21.0 已用于实际
验证，运行与 migration function 见 [HARNESS_VALIDATION.md](HARNESS_VALIDATION.md)。
历史截图仍为历史证据。未启用现场 watcher/远端写入。

现场升级前必须按 [v2 README](../codex-github-local-v2/README.md) 核对 schema 1
ledger；不清空历史防重放状态。Node 与本地 HTTP/core 已验证。后续先定义真实
模型生成接口与 adapter，再核对 Codex 隔离 probe 的实际运行条件、生产 GitHub
身份/请求映射和单一 Owner 授权，最后按证据完善 v2 普通任务执行链。
