# chat-codex v2 React 前端

React + TypeScript + Vite 管理界面，参考 [Draft PR #4](https://github.com/xiangshui001/chat-codex_cli/pull/4)
的视觉和交互规格。当前只接内存 MockClient，可长期迭代正式前端结构；真实 HTTP API、
Codex Host 和登录尚未接入。

## 运行

需要 Node.js 22.12+（本轮使用 24.19.0）和 npm。

```bash
cd web/app
npm ci
npm run dev
```

打开 `http://127.0.0.1:5173`，默认显示未登录页演示，点击「进入演示工作区」打开
Dashboard。`/#/login` 可直接访问该入口，原有 `/#/models`、任务和证据 deep link
仍然可用。工作区的「Mock 演示场景」内有「查看未登录页」按钮。

构建与静态预览：

```bash
npm run build
npm run preview
```

与离线 HTML 设计稿不同，这个 React 应用需要通过 HTTP 服务打开。
状态存在 MockClient 内存里，刷新页面重置；亮/暗主题偏好单独保存在浏览器。

## 已实现

- 未登录页演示：桌面左侧工作区入口、右侧 TISU 星穹图书馆外景；手机入口优先、模型置后。
- Dashboard：Controller、当前任务/主机、默认模型、队列统计和异常。
- Tasks：搜索、分组筛选、具体状态、领取模型、更新时间和 PR；详情包含读写范围、预算、轨迹、检查与审阅。
- Models：Executor / Reviewer 独立表单、四档 effort、等待/成功/失败回执、暂停/恢复新任务领取。
- Hosts：演示状态、CLI 版本、当前任务与模型、最后心跳。
- Evidence：平铺的 raw/resolved 合同、runtime snapshot、审计 JSONL；missing / withheld 明确显示。
- PR Review：只读候选汇总，链接到任务证据。
- Capabilities：权限边界说明与路由守卫，未实现成员编辑或认证。
- 手机抽屉导航、键盘焦点约束、Escape、Ctrl/Cmd+K 搜索和亮/暗主题。

所有任务、PR、模型目录、Host、心跳和回执都是虚构演示数据，使用
`demo/codex-workbench`；它们不对应本仓库的真实 Issue/PR/执行记录。

未登录页只有演示状态切换。按钮可以进入现有 Mock 工作区；没有真实账号、
认证会话或 OAuth，该页面也不是安全访问控制。图书馆模型采用本地资源懒加载，
静态外景只在初次显示、尺寸变化和页面重新可见时重绘，不保留动画循环。
不接入参观路径、自由移动、视角菜单或 TISU demo 的控件。加载、WebGL 初始化
或上下文失效时显示占位图，工作区入口保持可用。

## 演示异常

展开页面顶部的「Mock 演示场景」：

1. 切换 Viewer / Reviewer：表单只读，成员入口隐藏；直接访问成员路由也会受限。
2. 设置下一次控制为「模型不可用」或输入 `unavailable-demo`：失败后保留确认默认值、revision 和输入草稿。
3. 设置「结果待确认」：页面锁定新提交；点击「查询同一请求」确认原 request_id，不重发命令。
4. 设置「请求被拒绝」：确认默认值不改变。
5. 点击「演示读取失败」：显示上次成功读取的数据，禁用写操作，支持重试读取。
6. Evidence 选择 GH-43：未领取任务没有 resolved/runtime snapshot；GH-41 的原始 reviewer result 为 withheld；GH-39 保留验证缺口。

下一次控制结果只消费一次。角色切换改变 MockClient 返回的会话，不具有认证、邀请或授权效果。

## 结构与边界

| 文件                                 | 职责                                                         |
| ------------------------------------ | ------------------------------------------------------------ |
| `client/main.tsx`                    | 唯一组合入口，创建 MockClient；切换入口演示页与 AppShell     |
| `client/LoginPage.tsx` / `login.css` | 未登录演示入口和响应式布局                                   |
| `features/LibraryModel.tsx`          | 装饰模型的懒加载、单帧绘制、降级和卸载清理                   |
| `client/AppShell.tsx`                | 导航、hash 路由、主题、capabilities 守卫；可选 Mock 演示面板 |
| `client/useWorkspace.ts`             | 唯一应用数据/控制入口；加载、错误、过期响应保护和回执查询    |
| `features/`                          | 页面展示、搜索/筛选和表单草稿，不导入 transport 或 fixture   |
| `api-client/client.ts`               | ChatCodexClient 接口与统一错误类型                           |
| `api-client/types.ts`                | DTO、状态、控制意图、回执和证据白名单名称                    |
| `api-client/mock.ts` / `fixtures.ts` | 内存 transport、演示场景和固定虚构数据                       |
| `primitives/`                        | 选择性改写的 DSH Button/Input/Pill                           |

数据按 React 页面 → useWorkspace → ChatCodexClient → MockClient 流动。
模拟控制效果集中在 MockClient；页面不会自行改变任务、RuntimeSettings 或证据。
没有 HTTP 实现，也没有请求失败时自动切换 transport 的机制。

保持 v2 语义：提交成功不等于 applied；request_id 是不透明的请求标识，
`control_id/issue_url` 在 mock 中为 null；RuntimeSettings 使用 `model`，合同
ModelChoice 使用 `name`；已领取快照保持冻结；暂停不终止当前任务；状态轨迹与
审计 JSONL 分开；默认值失败时不更新 revision。

DSH / TISU 复用清单、来源版本与版权处理见 [NOTICE.md](NOTICE.md)。AppShell 与模型
表单用普通 React 重写，没有引入 DSH 后端依赖，也没有复制 PR #4 的单文件 JS。

## 检查

```bash
npm run build
npm test
npx playwright install chromium
npm run test:e2e
npx playwright test --config playwright.dev.config.ts -g 'repeated page entry|leaving during lazy import'
```

浏览器检查运行 build 产物，所以先 build。Playwright 使用自己的 Chromium；
已有本地 Chromium 时可指定 `PLAYWRIGHT_CHROMIUM_EXECUTABLE`。
只有设置 `UPDATE_SCREENSHOTS=1` 才重写工作区实拍图片；入口实拍使用
`UPDATE_LOGIN_SCREENSHOTS=1`。无 GPU 的验证机器可显式设置
`PLAYWRIGHT_SWIFTSHADER=1`，仅让测试浏览器使用软件 WebGL。

本轮实际验证：严格类型检查与 Vite build 通过；11 项 MockClient 测试与
19 项 Chromium 浏览器测试通过（原有 12 项 + 7 项入口/模型检查）。浏览器包括
1440×1080 桌面、390×844 手机，
并检查 320px 宽度无页面横向溢出；表格和 JSON 在各自容器滚动。无页面/console
错误或外部资源请求；故意阻断模块和 WebGL 初始化的场景允许浏览器报告该失败。
亮/暗/手机工作区与入口桌面/手机/失败回退截图已经视觉检查。

图书馆检查使用实际 Three.js 和 Chromium WebGL2，渲染后空闲 RAF 为零；重复进入、
退出和桌面/手机切换后旧上下文丢失，ResizeObserver 被清理。另验证延迟导入后
提前退出、WebGL 失败、运行中上下文丢失、键盘入口、reduced motion 与手机滚动。
本机采用 SwiftShader 软件渲染，未验证用户台式机 GPU、真实手机性能或帧率。
Vite 开发模式下另外跑过上述两项生命周期/延迟导入检查，React StrictMode 的
额外 setup/cleanup 也通过；开发模式检查使用独立的 4174 端口。

同一 v2 基线上运行现有回归：v2 48/48；0.1.0 Linux verify 53/53，0 skipped。
这两组使用离线替身，不证明真实模型或 GitHub 控制链可用。

截图：[桌面概览](screenshots/desktop-light.png)、
[暗色模型配置](screenshots/desktop-dark-models.png)、
[手机任务详情](screenshots/mobile-task.png)。实际检查摘要见
[verification.json](screenshots/verification.json)。

本次入口截图：[桌面](screenshots/login-desktop.png)、
[手机](screenshots/login-mobile.png)、[回退](screenshots/login-fallback.png)。
新增检查记录与 TISU 来源哈希见 [login-verification.json](screenshots/login-verification.json)。

## 下一步

PR #5 的前端交接见 [HANDOFF.md](HANDOFF.md)，Issue #6 的模型交接见
[LIBRARY_HANDOFF.md](LIBRARY_HANDOFF.md)。先补很薄的 HTTP adapter 并保留现有 v2 权威控制路径，
再现场验证 setDefaultModel → GitHub Control Issue → watcher → preflight →
runtime-settings.json → applied。真实写接口首次开放时就需要单一 Owner 身份校验；
多人登录/OAuth/仓库权限系统后续再做。本轮未部署或合并任何 PR。
