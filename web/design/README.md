# chat-codex v2 前端适配设计

这是 Issue #3 的**设计参考包**，包括源码研究、接口映射和可点击的离线页面。
本轮来自用户“读取修改版、查找 DSH、设计适配前端”的请求；不表示 Issue #3
指定的 GPT-6.1 Sol 正式实现任务已经完成，也不替代其模型要求。

- [可点击页面](index.html)：七个入口、任务详情、证据预览、模型设置、队列暂停/恢复、角色预览、亮/暗主题。
- [适配方案](DSH_ADAPTATION.md)：复用清单、v2 源码映射、拟议 API、协作边界及实现顺序。
- [类型草案](contracts.ts)：保留 v2 的状态、模型、快照和命令语义。
- [上游版权说明](NOTICE.md)。

直接用浏览器打开 `index.html`，无需安装依赖，也不需要网络。或者在仓库根目录运行：

```bash
python3 -m http.server 4173 --bind 127.0.0.1 --directory web/design
```

访问 http://127.0.0.1:4173 。`node check.mjs` 可检查内联 JS 语法和基础文件完整性。

页面中的主机、模型可用性、任务、PR、角色和控制回执**全部为模拟数据**。
模型操作只改变当前页面内存，刷新会重置；不产生 GitHub Issue，不调用 Codex，
也不读写本机配置。Models 中的 `unavailable-demo` 用于演示探测失败后的界面。

离线页面是一份便于讨论的设计稿；后续应按类型草案做 React + TypeScript 前端，
统一注入 mock / HTTP client。不要把本页的 mock handler 当成 v2 控制器实现。

验证记录与实现交接见 [适配方案末尾](DSH_ADAPTATION.md#验证和交接)。

已验证 27 组浏览器交互、接口类型、v2 的 48 项和旧版的 53 项离线回归。
截图：[桌面概览](screenshots/desktop-light.png) / [暗色模型设置](screenshots/desktop-dark-models.png) / [手机任务详情](screenshots/mobile-task.png)。
