# 仓库审查报告（Issue #20 整仓审查）

- 审查对象：main 最新工作区（当前工作区，非旧会话路径）
- 审查日期：2026-10（本轮执行时）
- 审查方式：静态代码审读（人工逐文件阅读），**未执行任何测试或运行程序**
- 结论摘要：核心执行链（MVP-0/1/2）整体设计严谨：串行领取、SQLite 原子声明、授权评论不可编辑校验、写路径/符号链接检查、发布阶段化恢复（committing 不确定即人工介入）、回执去重对账、密钥不入 Issue/快照/argv 等关键不变量均有实现且有对应测试。发现的问题以中低严重度为主，无发现可被未授权方直接利用的高危漏洞。

## 已审查范围

**逐行审读（源码全部 18 个模块）：**
`codex-github-local-v2/src/codex_github_local_v2/` 下：`mvp0.py`、`mvp0_runner.py`、`mvp1.py`、`mvp2.py`、`mvp2_contract.py`、`mvp2_runner.py`、`model_api.py`、`collaboration_api.py`、`workbench.py`、`listener_status.py`、`control.py`、`github_protocol.py`、`contract.py`、`ledger_migration.py`、`harness.py`、`codex_adapter.py`、`model_adapter.py`、`routing.py`、`claim.py`、`policy.py`、`evidence.py`、`git_workspace.py`、`locking.py`、`cli.py`、`remote_control.py`、`gh_cli.py`、`state.py`、`__init__.py`。

**配置/文档/测试：** `pyproject.toml`、`README.md`、`AGENTS.md`、`.gitignore`、`examples/mvp2-config.example.json`、`examples/models.example.json`、`docs/V2-MVP2.md`、`scripts/check_docs.py`、测试 `tests/test_mvp2.py`、`tests/test_receipt_recovery.py`；前端 `web/app/api-client/http.ts`、`web/app/client/useWorkspace.ts`。

**行号说明：** 下文行号为近似值（以函数/符号定位为准），不同 main 版本可能有 ±10 行偏移。

## 问题清单

### 中等（Medium）

**M-1 仓库缺少 LICENSE，许可证未定**
- 位置：仓库根目录（无 LICENSE 文件）；`README.md` 末段自述"项目整体许可证尚未另行指定"。
- 问题：任何第三方（含 PR 贡献者与使用者）的授权状态不明确；发布到 GitHub 后默认"保留所有权利"，与仓库公开工具属性矛盾。
- 建议：确定并添加 LICENSE（如 Apache-2.0 / MIT），在 README 与 NOTICE 中注明；第三方素材归属已在 `web/app/NOTICE.md` 处理，保持一致。

**M-2 无活跃 CI 流水线，回归测试依赖人工执行**
- 位置：仓库无 `.github/workflows/`（文件清单确认）；唯一 CI 快照在 `history/v1/ci/offline-tests.yml`，且 `AGENTS.md` 明确"旧 CI 不再作为活跃工作流"。
- 问题：`AGENTS.md` 要求的 `python3 -m unittest discover -s codex-github-local-v2/tests -v` 与历史回归没有任何自动化保障，回归风险完全依赖执行端自觉。
- 建议：为当前包添加最小离线 CI（unittest discover + `scripts/check_docs.py`），明确跳过需要 gh/codex 真实凭据的用例。

**M-3 `web/app/package.json` 含重复 JSON 键**
- 位置：`web/app/package.json`（本工具的严格 JSON 解析直接以 `duplicate_json_key` 拒绝读取该文件，可复现）。
- 问题：npm 对重复键"后者生效"，属未定义行为依赖；任何严格解析器（其它语言工具链、schema 校验）会失败，且难以确定哪个键生效。
- 建议：定位并合并重复键（通常为 scripts 或 dependencies 区块），用 `npm pkg get` 或 `node -e "JSON.parse(...)"` 验证。

**M-4 MVP-2 发布阶段非致命错误无重试上限，可能无限循环**
- 位置：`codex-github-local-v2/src/codex_github_local_v2/mvp2.py`，`DesktopPoller.finish_publication`（约 L216–240）与 `Publisher.publish`（约 L128–200）。
- 问题：`finish_publication` 只把固定的错误码集合（`stale_base`、`publication_branch_mismatch` 等）判为终态；其余 MvpError（如 `workspace_not_allowed`、`invalid_publication_update`、`invalid_pr_response`、`workspace_git_failed` 等确定性失败）走 `publication_pending` 分支，每轮轮询重复尝试 push/PR 查询，无退避、无重试计数、无告警升级。网络类错误重试合理，但逻辑性/确定性错误也永久重试，只会刷事件表且永远占住"未完成"状态。
- 建议：对错误分类（暂时性 vs 确定性），确定性失败进入需人工介入的终态；或至少加连续失败计数上限并写入 `listener-status.json`。

### 低（Low）

**L-1 `control.py` `_apply_model` 的 `changed` 标志恒为 True**
- 位置：`src/codex_github_local_v2/control.py`，`_apply_model`（约 L176–197）：`updated = replace(settings, **fields, revision=settings.revision + 1, ...)` 后 `ControlResult(updated, updated != settings, ...)`。
- 问题：`revision` 已自增，`updated != settings` 恒真；即使模型/effort 与原值相同，也报告"已变更"。影响仅限消息/事件语义，不影响状态正确性。
- 建议：先比较 `fields` 对应字段是否实际变化再自增 revision 或设置 changed。

**L-2 `DesktopConfig.load` 把配置内容写入系统 /tmp**
- 位置：`src/codex_github_local_v2/mvp2_contract.py`，`DesktopConfig.load`（约 L84–110）：用 `tempfile.NamedTemporaryFile` 中转给 `AccountConfig.load`。
- 问题：POSIX 下 mkstemp 权限为 0600，泄露风险低，但把 owner、本机绝对路径写入共享临时目录属不必要的暴露，且依赖系统 tmp 清理。
- 建议：改为直接调用 `AccountConfig` 的字段级校验逻辑（抽出纯校验函数），或使用 `state_dir` 下的临时文件并立即删除。

**L-3 `Workspace.baseline` 错误码误导**
- 位置：`src/codex_github_local_v2/mvp0.py`，`Workspace.baseline`（约 L440–447）：`git ls-remote --exit-code` 在分支缺失时返回码 2，被 `git()` 统一包装为 `workspace_git_failed` 而非 `stale_base`。
- 问题：回执/日志中的错误码无法区分"远端分支消失"与"本地 git 故障"。
- 建议：在 baseline 中显式处理 ls-remote 的返回码 2，映射为 `stale_base`。

**L-4 API 会话续接时 system 提示追加在历史末尾**
- 位置：`src/codex_github_local_v2/mvp2_runner.py`，`ApiFileRunner.run_task`（约 L185–200）：`history += [{role: system...}, {role: user...}]`，resume 时旧对话历史在前、新 system 在后。
- 问题：chat_completions 语义上 system 通常应居首；放在末尾部分 provider 可能降权处理，导致旧路径授权约束（"previous turns do not grant extra paths"）弱化。新增写路径授权仍由 `FileTools` 硬约束兜底，故仅为纵深防御问题。
- 建议：resume 时将新 system 消息插入历史最前，或合并为单条前缀 system。

**L-5 `check_session` 导入 CLI 会话时错误码不可区分**
- 位置：`src/codex_github_local_v2/mvp2.py`，`DesktopPoller.check_session`（约 L242–262）：`run_git(old, "remote", "get-url", "origin")` 在旧 cwd 不存在/非 git 时抛 `workspace_git_failed`，与真实 git 故障混同。
- 建议：先校验目录存在且是 git 仓库，失败映射为 `imported_session_repo_mismatch`。

**L-6 `harness.py` 状态标记文件解析失败未捕获**
- 位置：`src/codex_github_local_v2/harness.py`，`Harness.__init__`（约 L113–128）：`json.loads(marker.read_text())` 在标记文件损坏时抛 JSONDecodeError，直接崩溃而非给出"状态目录损坏"的可操作错误。
- 建议：捕获并抛出带指引的 `ControlError`/`ValueError`。

**L-7 `git_workspace.py` `commit_candidate` 不自行重验 scope**
- 位置：`src/codex_github_local_v2/git_workspace.py`，`commit_candidate`（约 L150–165）：`git add --all` 的 scope 约束完全依赖调用方先调用 `guard_changes`，两者之间无原子性；执行器在 guard 与 commit 之间再写文件则可绕过 scope（本地威胁模型下风险有限）。
- 建议：在 `commit_candidate` 内对 staged 文件清单重跑 policy 断言。

**L-8 `state.py` 原型状态机与 MVP-2 SQLite 状态并行存在**
- 位置：`src/codex_github_local_v2/state.py`（`RunState`/`_ALLOWED`）与 `mvp2.py` tasks 表的 `state` 字符串集合是两套不互通的状态模型；`state.py` 当前无运行时调用方（属 v2 原型）。
- 问题：维护者易混淆；两套状态无映射文档。
- 建议：在 `state.py` 或 `docs/INTEGRATION.md` 标注其原型/未来用途，或注明与 mvp2 状态无对应关系。

**L-9 workbench 对 HEAD 请求返回 405**
- 位置：`src/codex_github_local_v2/workbench.py`，`do_HEAD = do_POST`（create_server 内，约 L300 附近）。
- 问题：HEAD 与 GET 语义不一致（健康探测类工具可能误判服务不可用）；无安全影响。
- 建议：`do_HEAD` 委托 GET 的无正文路径。

### 信息级（Info）

- `mvp0.py` `read_json` 用 `object_pairs_hook` 拒绝重复 JSON 键、拒绝 NaN/Infinity——好实践；值得将同一严格解析推广到所有 JSON 入口（`harness.py` 的 `json.loads` 未用）。
- `mvp0_runner.py` 以 `start_new_session=True` + 进程组 SIGTERM/SIGKILL、stdout/stderr 直写文件避免管道死锁、剥离 GH/GITHUB token 环境变量——实现正确。
- `model_api.py` `NoRedirect` 禁止重定向防 Authorization 外泄；`base_url` 限制 http 仅限 loopback；reasoning_parameter 白名单字段——到位。
- `collaboration_api.py` 令牌用 `hmac.compare_digest`、拒绝 Origin/错误 Host、限制请求体大小——到位。
- `Publisher.publish` 不 force push、远端分支冲突即拒绝、PR 响应校验 URL 前缀与数字编号——到位，且有 `test_mvp2.py::PublisherTests` 覆盖对账路径。
- `.gitignore` 覆盖 `.env`、`auth.json`、`credentials*`、运行时目录——与 AGENTS.md 约定一致。
- 前端 `http.ts`/`useWorkspace.ts`：传输层不回退 mock、请求带 `X-Chat-Codex-Local`、控制请求幂等恢复（reload 后查询而非重提交）——与后端契约一致。

## 明确未覆盖范围（未审读）

- `web/app` 其余前端：`client/AppShell.tsx`、`DemoEntry.tsx`、`LiveWorkbench.tsx`、`LoginPage.tsx`、`features/*`、`primitives/*`、`visual/LibraryModel.tsx`、`public/tisu/astral-library/**`（第三方 three.js 素材）、`api-client/client.ts`、`mock.ts`、`fixtures.ts`、`types.ts`、各 `*.test.ts`、`vite/vitest/playwright` 配置、`index.html`。
- `web/app/package.json` 因 M-3 的重复键无法被本工具读取，其依赖清单与脚本未逐项核对（仅确认存在重复键问题）。
- `codex-github-local-v2/tests/` 其余测试文件（`test_core.py`、`test_control.py`、`test_harness.py`、`test_gh_cli.py`、`test_git_workspace.py`、`test_model_api.py`、`test_hardening.py`、`test_workbench.py` 等）未逐行审读，仅审读了 `test_mvp2.py` 与 `test_receipt_recovery.py`。
- `history/` 全部归档（v1/v2 源码与文档）、`docs/` 其余手册（安装说明、使用指南.html、VALIDATION、INTEGRATION、Chat协作手册、用户使用手册、环境排查）未逐字审读。
- 未执行任何测试、未运行 `python3 -m unittest discover`、未运行 `scripts/check_docs.py`；以上均为静态审读结论，测试通过与否不在本报告断言范围内。

## 优先级建议

1. 补 LICENSE（M-1）与最小离线 CI（M-2）——一次性低成本，长期收益最大。
2. 修复 `web/app/package.json` 重复键（M-3）。
3. 为 `finish_publication` 增加错误分类与重试上限（M-4）。
4. 低严重度项可随下一次触碰对应模块时顺带修复（L-1、L-3、L-4 优先）。
