> 历史快照，当前状态见[最新主页](../README.md)。

# 本地 HTTP / core 验证与 ledger 迁移

第二阶段在 integration 增加一个 **local-smoke** Harness。HTTP、React transport、
控制核心和磁盘状态是真实运行；GitHub source 是持久化的本地确定性替身，模型
probe 也是确定性实现。它不能证明真实 GitHub/模型调用成功，不能用于生产接管。

## 环境与依赖

`web/app/.nvmrc` 固定 Node 24.21.0（24 LTS），npm 使用该 Node 自带版本。
package.json/lockfile 的依赖版本不变。Node 下限 >=22.12.0；Vite 8.3.2、plugin-react
6.1.1 和 Vitest 5.0.3 的 engines/peer ranges 与 Node 24 相容。React/react-dom
19.3.0 配对，类型包配对；@types/node 26.6.4 是编译期类型，不代表运行时升级到
Node 26。本轮代码只用 Node 24 可用 API。

运行依赖 React/react-dom、clsx、lucide-react 均实际使用；TS/Vite/plugin、Vitest、
Playwright、Prettier 和类型包服务构建/检查。没有 ESLint 配置，不新装 ESLint。
没有重复直接依赖或可确认无用的 Draft 遗留包。npm ls 中其它平台 native 包、
可选编译器/样式预处理器等未安装项是 optional，不应为消除显示就整树升级。
Three.js 是固定来源的 vendored 文件，不另装 npm Three.js。

使用已有用户级 nvm，在当前 shell 加载；不需要 sudo/global npm 或修改初始化文件：

```bash
cd web/app
source "$HOME/.nvm/nvm.sh"
nvm use
npm ci
npm run typecheck
npm run build
npm test
npm run format:check
npm run dev
```

## 运行真实本地通信

先 build，然后在仓库根启动模块；state-dir 必须是专用空目录或同一身份的既有
smoke 目录，不能指向现场 runtime。这里的 repository 是本地验证标识。

```bash
PYTHONPATH=codex-github-local-v2/src python3 -m codex_github_local_v2.harness \
  --mode local-smoke --state-dir /tmp/chat-codex-smoke \
  --dist web/app/dist --repository local/smoke --port 4180
```

打开 `http://127.0.0.1:4180/?harness=local-smoke#/models`。入口和工作区明确显示
“本地确定性验证”；省略 query 时仍是显式 Mock 演示。HTTP 出错不切换到 MockClient。
该入口没有真实登录/OAuth；只绑定 loopback，校验 Host/Origin 和专用 header，不
提供 CORS。不作为公网或多人授权服务。

```text
React 用户操作
  → useWorkspace（生成 request_id）
  → HttpClient（真实 fetch、相同请求查询、无自动 POST 重试）
  → Python Harness /api/v2/controls
  → durable LocalSmokeSource（登记请求；唯一映射；确定性 GitHub source 替身）
  → 原 ControlProcessor（授权/解析/幂等；恢复回执优先）
  → 原 RuntimeControlService / apply_control
  → 原子 runtime-settings.json + control-ledger.json
  → local receipt 投递 → GET /controls/{request_id}
  → React 查询权威 /runtime → 已确认值
```

核心目前绑定 GitHub Control 协议。smoke source 为复用原逻辑提供内部 synthetic
GH-N 信封，**并非真实 Issue**；API control_id/issue_url 始终 null，不冒充 GitHub
身份。未来生产 API 应使用真实 GitHub 授权/映射，或先独立设计统一的非 GH 身份
与审计协议，不能直接拿这个测试 source 当 GitHub writer。

运行时查询读真实文件；任务/Host 为空，未知观测为 null，不用 fixtures 造数据。
Probe 只接受 auto/deterministic-test，拒绝其它模型；不存在真实模型 catalog。
ControlReceipt.settings 为 null：旧 core ledger 保存文本快照，没有结构化历史
settings，API 不拿当前设置冒充历史回执；React 终态后再查权威 runtime。

请求映射、授权评论替身、投递评论和故障标记存在 local-controls.json。重启后
session.pending_control 返回原请求，React 查询相同 request_id 恢复，不重新 POST。
回执/网络失败时保留最后读取状态并禁用写操作，原 ledger 恢复逻辑继续执行。
CLI 的 `--fail-first-receipt` 仅用于显式确定性故障注入，不是网络成功证据。

```bash
cd web/app
npm run test:harness
```

此测试自行启动真正的 Python CLI / HTTP 服务、真实浏览器与独立临时 state-dir，
覆盖 pause→回执失败→断线→服务重启→页面重连→原请求补发→resume→模型设置，
并验证 actual 文件内容和 POST 数量。可用 `HARNESS_SMOKE_EVIDENCE_DIR` 指定仓库
外证据目录。无 GPU 环境可复用已有 Chrome，设 PLAYWRIGHT_CHROMIUM_EXECUTABLE
及 PLAYWRIGHT_SWIFTSHADER=1；软件 WebGL 不证明真机 GPU 性能。

## 显式 ledger migration

0.0.3 继续使用 schema 2；迁移只经函数/CLI 显式调用，不在 watcher/Harness 启动
时自动执行。本轮只迁移临时测试数据，没有修改用户现场 ledger。

| 格式 | 字段 / 处理 |
| --- | --- |
| schema 1 | fingerprint、outcome、message、revision、recorded_at；没有回执快照或投递事实 |
| schema 2 | 保留上述字段，增加 issue_number、唯一完整 receipt、delivered_at；有效 schema 2 再跑是只读 no-op |
| 未知/损坏 | 拒绝，保留原数据，不猜版本/默认值 |

函数：`ledger_migration.migrate_control_ledger(path, reconciliation, authorized_users=...)`。
reconciliation 的 key 必须精确覆盖每个旧 control ID，每项包含：

- `settings`：完整历史 RuntimeSettings（paused、executor、reviewer、revision、
  last_control_id；两个 role 都有 model/effort）。revision 须与旧记录一致，applied
  的 last_control_id 须匹配。不能使用后来设置或填默认值推测历史。
- `receipt_comment`：已确认投递时填实际 CommentView 的 comment_id、author、
  created_at、updated_at、body；须为授权账号、未编辑，且正文与历史 result/settings
  完全一致。否则填 null，显式表示投递未确认，将保存待投递回执。无法确认历史
  settings 时应停止人工核对，不调用迁移。

```bash
codex-github-local-v2 migrate-ledger /path/to/control-ledger.json \
  --reconciliation /path/to/reconciliation.json --authorized-user OWNER
```

迁移获取同一个 control.lock，拒绝活跃 watcher；先全量验证，再创建 mode 0600
的原字节备份 `control-ledger.json.schema1.<原文件SHA256>.bak`，最后原子替换。
重复运行不再转换/造新备份；同名备份不一致则拒绝覆盖。失败保留原文件；替换
失败时已有完整备份可用于恢复/重试。拒绝 symlink。数据仍以旧 fingerprint 防
重放；已证明投递的行不会再次投递，未证明的只补发回执，不重做动作。

测试覆盖 pending/delivered、幂等、缺证据/不完整快照、版本和 revision、作者/编辑、
备份和原子替换故障、锁、symlink。运行前仍须核对现场历史，不自动将所有旧结果
一律设为 delivered 或 pending。

## 下一阶段模型边界

当前 ModelAdapter 仅承载 `(role, ModelChoice) -> ProbeResult`。模型 ID 是不透明
名称；契约测试用 OpenAI-compatible、DeepSeek、Qwen 名称通过同一注入接口，
没有供应商分支进入 React/control/routing。Endpoint、认证、供应商参数/错误映射
应在 adapter 实现/组合配置中管理，不从浏览器传入凭证。

可以开始下一阶段的后端接口与单一路径实现；生成、流式事件、能力/effort 映射、
timeout/retry 尚未定义或现场验证。不能把 availability probe 契约说成已有完整
DeepSeek 生成后端。真实 GitHub、Codex probe、OAuth、完整 v2 普通任务链仍另行验收。
