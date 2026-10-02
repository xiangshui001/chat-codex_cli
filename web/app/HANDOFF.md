# React 前端交接

## 任务与基线

- 用户授权：将 PR #4 设计参考实现成 React + TypeScript + Vite 前端，先接 MockClient，完成后上传独立 Draft PR。
- 需求参考：[Issue #3](https://github.com/xiangshui001/chat-codex_cli/issues/3)。
- 实现基线：`prototype/orchestrator-v2`，`fe4785840ee41f7df36c0bc3b186302c3d5dcaac`。
- 设计参考：PR #4，`184acd74da6c2f47a7037282d2a386249e8002f1`。不继承其单文件脚本；该 PR 保持 Draft。
- DSH 固定源码：`639ed015397290b3745d163aafe02ffee4aa3f84`，复用清单见 NOTICE。
- 候选提交 SHA 由本 PR 的实际 head 提供，文件内不写自引用 SHA。

## 修改

新增独立 `web/app/`。页面通过一个 useWorkspace 和 ChatCodexClient 读取数据、
提交控制。MockClient 覆盖等待、成功、模型不可用、拒绝、结果待确认、读取失败、
缺失/未开放证据与只读能力。没有改动 0.1.0、v2 core 或 HTML 设计参考。

## 检查

- `npm run build`：严格 TypeScript 和 Vite 静态构建通过。
- `npm test`：11/11；回执等待、失败保留、冻结模型、请求重放、直接调用权限、暂停语义、证据与读取错误。
- `npm run test:e2e`：12/12；七个路由、详情/deep link、模型应用/失败、unknown 原请求查询、两个角色独立操作、pause/resume、只读守卫、证据、键盘搜索、读取失败、404、主题与手机导航。
- 浏览器：Chromium 153.0.8010.0，本轮使用本地可执行文件；无 page/console error 或远程资产请求。截图为 React build 产物实拍，全部是 mock。
- 现有 v2 单元测试：48/48。
- `python3 codex-github-local/verify.py`：Linux 53/53，0 skipped，POSIX covered；模型和 GitHub 为离线替身。

## 接 HTTP 的最小改动

在 api-client 中实现同一个 ChatCodexClient，在 `client/main.tsx` 替换注入。
去掉 MockDemo 即可移除演示控件。页面展示和表单提交无需重写。

| 首批拟议路由                           | 方法                                                       |
| -------------------------------------- | ---------------------------------------------------------- |
| `GET /api/v2/runtime`                  | getRuntimeStatus                                           |
| `GET /api/v2/tasks`                    | listTasks                                                  |
| `GET /api/v2/tasks/:id`                | getTask                                                    |
| `GET /api/v2/tasks/:id/evidence/:name` | getEvidence                                                |
| `POST /api/v2/controls`                | setDefaultModel / pauseQueue / resumeQueue / requestStatus |
| `GET /api/v2/controls/:request_id`     | getControlReceipt                                          |

session、Host registry 与模型目录是额外 seam：首次接入可由经过认证的单一
Owner 会话返回 capabilities；尚无 Host/catalog 数据时返回空数组，未知观测
字段为 null/unknown。不要将 mock fixture 当真实后端回退数据。

HTTP adapter 调用 v2 已有控制/任务逻辑，不另造任务引擎或直接写 runtime。
优先走服务端 Control Issue 与授权评论 → 现有 watcher；服务端分配实际 GH-N，
维护 request_id 映射并返回权威 receipt。真实服务不得只依赖 UI role 下拉框。

请求超时先按同一 request_id 查询，不能自动创建第二条控制指令。服务端还需
明确仓库权限、发布证据白名单/脱敏投影、共享串行写入与请求幂等。runtime
revision 当前是快照版本，不应被前端当作已有 CAS 锁。

## 未运行、风险与部署

未运行真实 HTTP API、Codex 模型 preflight、台式机 Host、GitHub Control Issue
端到端链路、OAuth/多人认证；没有公网部署或 PR 合并。当前真实可用的边界是
可独立构建/运行的前端和模拟 transport，不是生产远程控制服务。

下一项应在真实 API 提交里验证成功/失败/unknown/幂等、已领取任务不变和单一
Owner 授权，再用现场链路确认 runtime-settings.json 与 applied 一致。
