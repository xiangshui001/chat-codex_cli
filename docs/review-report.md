# 整仓审查报告（Issue #19 续接）

- 审查对象：本仓库当前 main（独立新工作区、最新基线）。
- 审查方式：**只读**。未修改任何现有业务代码或其他文件；本文件是本次唯一写入。
- **未执行任何测试**：没有运行 `python3 -m unittest ...`、`history/v1/codex-github-local/verify.py`、`npm test`、Playwright、`scripts/check_docs.py`，也没有进行任何 GitHub / 模型 API 网络调用。下文所有"行为"描述来自源码与测试源码的静态阅读，不代表已经运行验证。

## 1. 覆盖范围

### 已逐行阅读（本次）

| 区域 | 文件 |
|---|---|
| 执行端源码（全部 25 个模块） | `codex-github-local-v2/src/codex_github_local_v2/`：`mvp0.py`、`mvp0_runner.py`、`mvp1.py`、`mvp2.py`、`mvp2_contract.py`、`mvp2_runner.py`、`model_api.py`、`collaboration_api.py`、`workbench.py`、`listener_status.py`、`controller.py`、`contract.py`、`state.py`、`routing.py`、`policy.py`、`claim.py`、`control.py`、`evidence.py`、`gh_cli.py`、`git_workspace.py`、`github_protocol.py`、`harness.py`、`ledger_migration.py`、`model_adapter.py`、`remote_control.py`、`cli.py`、`__init__.py`、`codex_adapter.py` |
| 打包与示例 | `pyproject.toml`、`examples/models.example.json`、`examples/mvp2-config.example.json` |
| 后端测试（18 / 22） | `test_mvp0.py`、`test_mvp1.py`、`test_mvp2.py`、`test_workbench.py`、`test_model_api.py`、`test_processor.py`、`test_receipt_recovery.py`、`test_core.py`、`test_claim.py`、`test_control.py`、`test_github_task.py`、`test_git_workspace.py`、`test_gh_cli.py`、`test_hardening.py`、`test_packaging.py`、`test_codex_adapter.py`、`test_codex_probe.py`、`fixtures/mvp0_codex.py` |
| 前端源码与配置 | `web/app/client/*`（`main.tsx`、`LiveWorkbench.tsx`、`AppShell.tsx`、`DemoEntry.tsx`、`LoginPage.tsx`、`useWorkspace.ts`）、`web/app/api-client/{client,http,mock,types}.ts`、`web/app/api-client/{http,mock}.test.ts`、`web/app/features/{ModelsView,TaskViews,WorkspaceViews}.tsx`、`web/app/visual/LibraryModel.tsx`、`package.json`、`tsconfig.json`、`vite.config.ts`、`vitest.config.ts`、`playwright.config.ts`、`.nvmrc`、`index.html`（结构）、`tests/live-workbench.spec.ts`、`tests/harness-smoke.spec.ts`、`README.md`、`NOTICE.md` |
| 文档与脚本 | `README.md`、`AGENTS.md`、`.gitignore`、`.gitattributes`、`docs/{安装说明,用户使用手册,Chat协作手册,V2-MVP2,INTEGRATION,VALIDATION,环境排查}.md`、`docs/使用指南.html`、`scripts/check_docs.py`、`history/README.md`、`history/v2/README.md` |

### 未覆盖（明确披露）

- 未逐行阅读：`test_harness.py`、`test_ledger_migration.py`、`test_model_adapter_contract.py`、`test_remote_control.py`（仅按文件名与文档推断其意图）。
- 未逐行阅读 `history/` 下的历史实现：`history/v1/codex-github-local/**`（`bridge.py`、`verify.py`、`handoff_check.py`、`engine/runner.py`、`tests/upstream/**`）、`history/v2/docs/**`、`history/*.md`（除 README）、`history/frontend/*`、`history/exit-code-fix.patch`、`history/**/validation/*.json`、`history/PUBLICATION-20260928.json`。因此**不能对 V1 归档代码、其上游 vendored 代码的许可证与正确性作出结论**。
- 未逐行阅读前端样式与素材：`client/{styles.css,live.css,login.css}`、`primitives/Atoms.{tsx,module.css}`、`client/fixtures.ts`、`tests/{workspace,login}.spec.ts`、`playwright.dev.config.ts`、`playwright.harness.config.ts`、`package-lock.json`、`web/app/public/tisu/astral-library/**` 与 `visual` 素材 JS（第三方 TISU / Three.js 代码未做源码级审计，仅确认 `NOTICE.md` 有归属说明）。
- 未核对 `docs/VALIDATION.md`、`docs/使用指南.html` 中声明的测试数量与浏览器/构建结论（需实际运行，本次未执行）。
- 未验证外部依赖版本可解析性、`npm ci` 可复现性、GitHub 权限模型、真实第三方模型接口兼容性。

## 2. 行号说明

行号来自本次静态阅读，标注为 `≈`（误差约 ±10 行）；**函数/类符号名是权威定位**，行号仅用于快速跳转。

## 3. 问题清单

### A. 严重程度：高

**A1. 授权写路径不排除高危文件（CI 工作流、密钥文件），且两种执行模式规则不一致**

- 位置：`codex-github-local-v2/src/codex_github_local_v2/mvp0.py` `write_path()` ≈L68–L75；对比 `codex-github-local-v2/src/codex_github_local_v2/mvp2_runner.py` `FileTools.path()` ≈L133–L150。
- 事实：`write_path()` 只拒绝绝对路径、`//`、`..`、`.git`、`.codex`、通配符与控制字符。它**不**拒绝 `.github/workflows/`、`Dockerfile`、`package.json`、`.env*`、`auth.json`、`credentials*`。API 模式另有 `FileTools.path()` 的密钥文件 denylist（`.env*`、`auth.json`、`credentials*`），CLI（`gpt` / `gpt-led`）模式**没有**任何等价过滤，仅由 `Workspace.safe_path()`（`mvp0.py`）做越界/符号链接检查。
- 影响：同一 Issue 协议下，CLI 模式可以合法写 `.env` 或 `.github/workflows/*.yml`，随后被 `Publisher.publish()`（`mvp2.py` ≈L164–L215）提交并推送到目标仓库分支，再进入草稿 PR；同仓库分支 PR 的工作流可能不需人工批准即运行。也造成"文档说受路径约束、密钥文件被拦截"与 CLI 实际行为不符。
- 建议：把密钥/自动化文件规则下沉为共享的 `write_path()` 级检查（单一实现，两种模式共用）；对 `.github/workflows/`、`package.json` scripts、`Dockerfile`、`Makefile` 等高影响路径默认拒绝或要求显式二次确认（例如专用 `write_paths` 前缀 + 回执中标注"包含 CI/自动化文件"）；在 `docs/V2-MVP2.md`、`docs/使用指南.html`、`docs/Chat协作手册.md` 写明该默认姿态。

### B. 严重程度：中

**B1. `Publisher.publish` 不校验工作目录是否位于 `workspace_root` 之下**

- 位置：`mvp2.py` `Publisher.publish()` ≈L164–L215（`workspace = Path(row["cwd"])`；`Config(..., workspace, (workspace,), Path("/"), ...)`）。
- 事实：`Config` 是冻结 dataclass，直接构造会跳过 `Config.load()` 的全部校验；allowlist 被设为 `(workspace,)` 自身，因此 `Workspace.registered()` 只能校验"origin 与目标仓库一致"，无法校验目录归属。`state_dir` 也被写成 `Path("/")`。
- 影响：本地数据库 `cwd` 被篡改或迁移错误时，控制器可在 `workspace_root` 之外的任意同源克隆上 commit/push（仍需 origin 匹配，故非远程攻击，但违反"成果只在本机工作区"的边界声明）。
- 建议：显式断言 `Path(row["cwd"]).resolve() == (config.workspace_root / str(d["target_id"]) / row["request_id"]).resolve()`，并断言其在 `workspace_root.resolve()` 之内；`state_dir` 传入真实值而非 `Path("/")`。

**B2. 协作 API 为单线程 `HTTPServer`，长模型调用期间阻塞全部端点**

- 位置：`codex-github-local-v2/src/codex_github_local_v2/collaboration_api.py` `main()` ≈L160–L180（`HTTPServer(("127.0.0.1", args.port), handler(...))`），`do_POST` ≈L62–L95。
- 事实：`request_timeout` 可配置到 3600 秒，`do_POST` 内同步等待模型返回；单线程服务器在此期间无法响应 `GET /health` 或 `GET /v1/models`，无队列上限。
- 建议：改用 `ThreadingHTTPServer`（或显式单请求锁 + 明确 503），并在文档说明并发语义。

**B3. MCP stdio 桥接在超长行时静默退出**

- 位置：`collaboration_api.py` `serve_stdio()` ≈L120–L145（`line = stdin.readline(MAX_REQUEST + 1)`；`if len(line.encode()) > MAX_REQUEST: return`）。
- 影响：单行超过 64 KiB 时不返回 JSON-RPC 错误而是直接结束进程，Codex 侧只看到 MCP 断连，任务以间接错误失败，诊断信息丢失。
- 建议：改为返回 JSON-RPC 错误（`-32600`）并继续读下一行，或明确在文档/回执中给出可识别错误码。

**B4. 仓库缺少顶层许可证，而内含多份第三方代码与素材**

- 位置：仓库根（无 `LICENSE`）、`web/app/NOTICE.md`、`web/app/third-party/DEEPSEEK-LICENSE.txt`、`web/app/public/tisu/astral-library/vendor/THREE-LICENSE.txt`、`history/**` 内的历史来源。
- 事实：`README.md` 明确"项目整体许可证尚未另行指定"；`NOTICE.md` 只覆盖被引用的第三方部分。第三方 MIT 许可正文已保留（合规），但仓库自身的使用/再分发条款缺失。
- 建议：补 `LICENSE` 并说明覆盖范围（自有代码 vs `history/` 归档 vs 第三方），`README.md` / `NOTICE.md` 互相链接。

**B5. 文档中的可核实性声明未在本次审查中验证**

- 位置：`docs/VALIDATION.md`（"201 项后端测试"、"53 项 POSIX 回归"、"15 项前端单元测试"、"23 项浏览器测试"）、`docs/使用指南.html` 第 08 节统计块（`201 / 53 / 15 / 23`）、`README.md`（"执行端已验证 Linux / Ubuntu / WSL"）。
- 事实：这些是结论性计数，需要实际运行才能确认；本次未运行，无法判断是否与当前 main 一致（例如 `history/v1/codex-github-local/verify.py` 的 53 项与 `pyproject.toml` 只注册 4 个入口之间的对应关系只能靠文档）。
- 建议：在 `docs/VALIDATION.md` 记录生成这些数字的**具体命令与提交哈希**，并在 CI/发布流程中把文档数字与运行结果绑定，避免版本漂移。

### C. 严重程度：低

**C1. 测试夹具使用转义换行，掩盖"输出需以换行结束"的假设**

- 位置：`codex-github-local-v2/tests/test_codex_probe.py` ≈L16 与 ≈L26（`stdout='{"type":"turn.completed"}\\n'`、`stdout="unsupported model\\n"`，普通字符串中的 `\\n` 是字面反斜杠 + n）。
- 影响：探针只检查 `returncode`，当前不影响结论；但夹具与真实 JSONL 形态不同，后续若把探针改为解析 stdout 会得到误导性结果。
- 建议：改为原始字符串或真实换行。

**C2. 路径校验存在检查—使用时间窗（TOCTOU）**

- 位置：`mvp0.py` `Workspace.safe_path()` ≈L360–L372；`mvp2_runner.py` `FileTools.path()` ≈L133–L150 与 `write_file` 分支 ≈L170–L185（检查符号链接后 `path.parent.mkdir(parents=True, exist_ok=True)` 再写）。
- 影响：本地并发或恶意仓库内容可在校验与写入之间替换目录为符号链接；需要本地写入能力，故风险有限。
- 建议：写入改用 `os.open(..., O_NOFOLLOW|O_CREAT|O_EXCL)` 或 `dir_fd` 相对打开，写入后再次断言 `resolve()` 仍在工作区内。

**C3. 两套并行状态模型与大量"已退出安装入口"的模块并存**

- 位置：`state.py`（`RunState`，17 个状态，含 `claimed/preflight/executing/validating/reviewing/...`）与 `mvp0.py` `Store` 的 `CHECK(state IN ('queued','running','succeeded','failed','stale_base'))` 以及 `workbench.py`/`web/app/api-client/types.ts` 的 `RunState` 联合类型。
- 事实：`contract/controller/policy/routing/state/evidence/claim/control/gh_cli/git_workspace/github_protocol/harness/ledger_migration/model_adapter/remote_control/cli/codex_adapter` 仍被测试覆盖，但**不由任何已注册 console script 引用**（`pyproject.toml` 仅注册 4 个入口）。
- 影响：命名与语义混淆（同一"state"概念三处定义），新读者容易误判当前链路。
- 建议：在 `docs/INTEGRATION.md` 增加"当前入口可达 vs 仅回归保留"的显式模块清单（含行级引用），或为未接入模块加模块级注释标记。

**C4. `DesktopConfig.load` 借临时文件复用 `AccountConfig.load`**

- 位置：`codex-github-local-v2/src/codex_github_local_v2/mvp2_contract.py` `DesktopConfig.load()` ≈L85–L110（`tempfile.NamedTemporaryFile(..., delete=False)` + `finally: tmp_path.unlink()`）。
- 影响：多数情况下临时文件被删除（无 `.gitignore` 风险，因写入系统临时目录）；但崩溃/被杀时残留，且字段集合被"复制过滤"后再校验，两处字段白名单需同步维护，易漂移。
- 建议：抽出共享的字段校验函数直接校验字典，去掉临时文件中转。

**C5. 协作调用预算默认无上限**

- 位置：`model_api.py` `ModelRegistry.__init__` ≈L30–L45（`max_turns`/`max_calls` 允许 `null`）、`Collaboration.consult/respond` ≈L175–L215；示例 `examples/models.example.json` 与 `docs/使用指南.html` 的 models.json 片段均为 `null`。
- 影响：本机默认对模型轮数与协作调用次数不设上限，成本失控只受 `request_timeout` 与上下文 1 MiB 限制约束（`mvp2_runner.py` `ApiFileRunner`）。
- 建议：文档默认给出显式预算示例（非 `null`）并提示成本；或在注册表增加可选 `max_total_tokens`/`max_cost` 提示字段。

**C6. 前端轮询与错误分类的粗糙处**

- 位置：`web/app/client/LiveWorkbench.tsx` ≈L200–L230（每 3 秒 `setTimeout` 轮询，无 `document.hidden` 暂停）；`web/app/api-client/http.ts` `request()` ≈L30–L60（401 与 429/5xx 都映射为 `unavailable`）。
- 影响：隐藏标签页持续轮询本机服务（轻微无谓开销）；UI 无法区分"未授权/被拒绝"与"服务离线"，与 `useWorkspace` 里对 `forbidden` 的专门处理不一致。
- 建议：`visibilitychange` 时暂停/恢复轮询；401 单独映射（如 `unauthorized`）并在 UI 明示。

**C7. 文档/配置的小不一致与历史文件误用风险**

- 位置：`docs/安装说明.md`（Node.js 22.12+）vs `web/app/.nvmrc`（`24.21.0`）；`history/exit-code-fix.patch`（无头部"已包含、勿再应用"说明，而 `history/README.md` 才写了该结论）；`pyproject.toml` 缺 `license` / `classifiers` / `[project.urls]`。
- 建议：统一 Node 版本表述（或注明 `.nvmrc` 为推荐值）；在历史补丁与旧 CI 快照文件头加废弃标注；补齐 `pyproject.toml` 元数据。

**C8. `FileTools.path` 的密钥过滤过宽**

- 位置：`mvp2_runner.py` `FileTools.path()` ≈L136（`any(p.startswith(".env") or p.lower() in {"auth.json","credentials","credentials.json"} ...)`）。
- 影响：`.env.example`、`.environment.md` 之类的合法文件被拒，模型会收到 `secret_file_not_allowed` 而无法完成文档类任务；且该过滤与 CLI 模式不一致（见 A1）。
- 建议：改为精确匹配 `.env`、`.env.*` 中的密钥命名惯例（如排除 `.env.example`）并与 A1 的共享检查合并。

**C9. 工作台静态资源请求不做同源/Host 校验**

- 位置：`codex-github-local-v2/src/codex_github_local_v2/workbench.py` `create_server().do_GET` ≈L195–L235（仅 `/api/**` 分支校验 `Host`/`Origin`/`X-Chat-Codex-Local`，其余路径直接交给 `SimpleHTTPRequestHandler`）。
- 影响：仅影响静态文件（浏览器同源策略阻止读取响应体），风险低；但若将来在静态目录放敏感产物，缺少统一防护。
- 建议：对静态响应也加 `Host` 校验（或明确文档说明只暴露构建产物）。

**C10. `Harness` 的 GET 请求带副作用**

- 位置：`codex-github-local-v2/src/codex_github_local_v2/harness.py` `Harness.get()` 的 `/api/v2/controls/<request_id>` 分支（调用 `self.advance()`，即执行一次 `ControlProcessor.tick()`）；`create_server().do_GET`。
- 影响：仅本地 smoke 用途（`?harness=local-smoke`），但 GET 触发状态写入不符合只读语义，可能被预取/重试意外重复触发。
- 建议：改为 POST 或明确命名/文档说明；测试夹具 `tests/harness-smoke.spec.ts` 也依赖该行为，需同步。

## 4. 静态阅读确认的既有防护（未运行，仅代码事实）

以下性质在源码与测试源码中可直接读到，值得在后续变更中保留：

- 授权一次性：Issue 标题前缀 `[codex-v2-mvp2]`、评论首行 `/codex-v2-mvp2 run`、唯一且未编辑的评论（`mvp0.parse_task`、`mvp2_contract.parse_desktop_task`），并拒绝重复 JSON 键与非有限数字（`mvp0.read_json`）。
- 路由与身份：`host_id` 精确匹配（含大小写），目标仓库 owner 校验，Issue 只允许来自目标仓库或 `hub_repo`（`mvp2_contract.parse_desktop_task`）；仓库 owner/id/archived/disabled/has_issues/default_branch 校验（`mvp1.AccountGitHub._repository`）。
- 领取串行与去重：SQLite `BEGIN IMMEDIATE` + `UNIQUE(repository_id, issue_id)` + `one_active_task` 唯一索引 + `unfinished_task_requires_manual_inspection`（`mvp0.Store`、`mvp2.DesktopStore.claim_desktop`）。
- 执行前后基线：`stale_base` 在克隆前、执行后、发布前各校验一次（`mvp1.AccountGitHub.check_base`、`mvp0.Workspace.baseline`、`mvp2.Publisher.publish`）。
- 发布安全：不 force push；远端已存在不同 SHA 的分支即拒绝；PR 复用前校验 head SHA 与 base 分支（`mvp2.Publisher.publish`）；提交时禁用 git hooks（`core.hooksPath=/dev/null`）。
- 回执幂等：只信任本账号（`writer_id`）且正文完全一致的评论，丢失响应不会重复执行模型（`mvp0.GitHub.post_receipt`）。
- 会话绑定：会话绑定目标仓库 ID、host_id、后端；CLI 会话必须存在于 `CODEX_HOME` 且原 origin 与目标仓库一致，不使用 `--last`（`mvp2.DesktopPoller.check_session`、`mvp2_runner.validate_cli_session`、`SessionCodexRunner.prepare_task`）。
- 只读工作台：SQLite 以 `mode=ro` + `query_only=ON` 打开，schema 与 owner/host/workspace 绑定校验，事件与日志投影只保留白名单字段并做密钥脱敏（`workbench.Reader`、`clean`、`activity`、`progress`）。
- 本机 API：仅绑定 `127.0.0.1`，需 Bearer 令牌（≥32 ASCII），拒绝带 `Origin` 的请求，禁止重定向以免转发 `Authorization`（`collaboration_api.Handler.allowed`、`model_api.NoRedirect`）。
- 本机状态：`poller.lock` + `workspace_root/.mvp1.lock` 双重排他锁；`os.umask(0o077)`；状态文件 0600 + 原子替换（`exclusive_lock`、`listener_status.ListenerStatus.update`）。

## 5. 建议的处理顺序

1. A1（写路径策略统一 + 高危路径默认拒绝）——影响默认安全姿态与文档一致性。
2. B1（发布前断言工作目录归属）、B3（MCP 桥接错误可见）、B2（协作 API 并发）。
3. B4 / B5（许可证与文档可核实性）。
4. C 组为维护性与体验项，可随相关功能变更一并处理。

## 6. 结论

- 本次审查覆盖当前执行端全部 Python 源码、全部文档入口、前端主要源码与 18 个后端测试文件；**未覆盖** `history/` 历史实现、前端样式与第三方素材、4 个后端测试文件，且**未执行任何测试或网络调用**。
- 当前实现的核心防护（串行领取、一次性授权、host 路由、基线校验、不 force push、回执幂等、只读工作台、本机 AK 鉴权）在静态阅读层面是自洽的，并能与仓库内测试相互印证。
- 需要优先处理的实体问题是：**A1 写路径策略在 CLI 与 API 两种模式间不一致且不拦截 CI/密钥文件**，其次是 **B1 发布路径归属断言缺失**与 **B2/B3 本机服务可用性/错误可见性**。
- 本报告不代表任何测试已通过；`docs/VALIDATION.md` 与 `docs/使用指南.html` 中的计数需要在实际运行后单独复核。
