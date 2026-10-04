# 本机工作台前端

当前默认页面读取 MVP-1 真实任务。安装和运行后端见 [工作台说明](../../docs/MVP1-WORKBENCH.md)。

```bash
npm ci
npm run build
```

将 dist 交给 `codex-github-local-v2-workbench` 服务，浏览器打开 http://127.0.0.1:8791/ 。开发时运行 `npm run dev`，访问 http://127.0.0.1:5173/ ，`/api/mvp1` 代理到 8791。

| 模式 | 地址参数 | 用途 |
|---|---|---|
| 默认 / live | 无参数或 `?view=live` | 本机真实任务，只读；失败不回退演示 |
| 演示 | `?view=demo` | 早期界面原型，模拟数据，按需加载 |
| Harness | `?harness=local-smoke` | 显式确定性测试，独立测试服务 |

```bash
npm run build
npm test
npm run test:e2e
```

浏览器测试默认使用 Playwright Chromium，也可设置 `PLAYWRIGHT_CHROMIUM_EXECUTABLE` 指向本机 Chrome。`npm run test:harness` 为独立 Harness 测试，环境要求见[历史 Harness 说明](../../history/HARNESS_VALIDATION-20261002.md)。

保留原型供未来设计参考，不能把它的模型控制、审批等界面当作真实 MVP-1 功能。旧交接见 [HANDOFF](../../history/frontend/HANDOFF.md) 与 [LIBRARY_HANDOFF](../../history/frontend/LIBRARY_HANDOFF.md)。第三方资源归属见 [NOTICE](NOTICE.md)。
