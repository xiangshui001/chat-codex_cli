# 星穹图书馆入口交接

本文记录 PR #7 的历史交付与验证。integration 中薄 wrapper 位于
`visual/LibraryModel.tsx`；来源原件保持逐字节一致。2026-10-02 本机没有
Node/npm，目录整理后的 build/unit/浏览器检查待 Node 环境验证。

## 基线和范围

- 需求：[Issue #6](https://github.com/xiangshui001/chat-codex_cli/issues/6)。
- 基于 [Draft PR #5](https://github.com/xiangshui001/chat-codex_cli/pull/5) 的分支
  `feature/GH-3-react-frontend`，提交 `7697b29e19b4b53a20af7e436c3adccecacbd1c9`。
- 本次使用独立分支 `feature/GH-6-library-login`，PR #5 和 HTML 设计稿保持原状。
- TISU 来源固定到 `7297fcbcc7663f4b51bd41b19ef43e63e1b8aea8`。
- 变更仅在 `web/app/`，不改动 v2 core、控制协议或 0.1.0。

## 行为

默认入口和 `/#/login` 显示未登录演示页。桌面两列约 41% / 59%，左侧入口和
产品说明、右侧外景模型。900px 以下改为上下布局，手机入口在首屏，模型为次要
展示。点击「进入演示工作区」进入现有 Mock Dashboard，工作区演示面板可返回入口。
原有任务、证据、模型等 deep link 保留，不用演示登录状态冒充认证系统。

`LibraryModel` 只包装 TISU 裸场景 API。动态导入使用 Vite 的 BASE_URL，Three.js
和模型资源由应用同源提供。完整上游组件目录保留，文件逐一核对与固定来源一致；
入口不执行上游 Web Component 或 full-page demo UI。

外景没有交互或动画。挂载后立即 pause；尺寸变化或页面重新可见时 resume/pause
绘制一帧，因此隐藏或滚出视口后也没有持续 RAF。手机/窄屏关闭阴影、DPR 上限 1；
桌面上限 1.25。画布禁用 pointer events、Tab 焦点与触控拦截，不占用滚轮或键盘。

卸载和断点切换会断开 ResizeObserver、移除可见性/上下文监听，调用上游 dispose
释放几何、材质、纹理、阴影、渲染器与 WebGL 上下文。延迟导入后会先检查 effect
是否取消，避免离开页面或 StrictMode 清理后晚到的模型挂载。模块/初始化失败和
运行中 context loss 都显示静态占位图，入口按钮仍可使用。

## 验证

- 严格 TypeScript 和 Vite build 通过。
- MockClient 11 项通过，已有 API 边界未改。
- Chromium 浏览器 19 项通过：保留原有 12 项工作区回归，增加 7 项模型/入口检查。
- 模型检查包含真实 WebGL2 渲染、空闲 RAF 为零、上下文释放、ResizeObserver 清理、
  多次进入退出、断点切换、延迟导入后提前退出、初始化失败、模块失败、运行中上下文
  丢失、键盘入口、手机滚动与 reduced motion。
- 1440×1080 桌面、390×844 手机和 320px 宽度检查；新入口三张截图已实拍并目视核对。
- 现有 v2 测试 48/48；Linux `python3 codex-github-local/verify.py` 53/53，0 skipped。
- TISU 的 12 个文件与固定提交源文件逐字节一致，包括 Three.js MIT 许可。
- Vite dev + React StrictMode 额外运行生命周期/延迟导入 2 项，两项均通过。

命令和截图入口见 README；机器摘要、资源哈希见 `screenshots/login-verification.json`。
本次使用 Chromium 153 + SwiftShader 软件 WebGL，模型未由模拟渲染器替代。离线 core
回归采用模型/GitHub 替身，不证明生产控制链可用。

## 后续边界

未接真实认证、OAuth、HTTP API、Codex Host 或模型 preflight；未部署或合并。真实
台式机 GPU、Android/iOS 浏览器和移动设备加载性能仍需现场确认。本次静态展示
不提供镜头进入、路线播放、自由行走、视角/昼夜/剖视菜单或模型选择。

之后接认证时由统一客户端返回会话和 capabilities，再替换演示入口行为；不得将
hash 或「进入演示工作区」按钮当安全边界。模型展示和工作区数据接口保持独立。
