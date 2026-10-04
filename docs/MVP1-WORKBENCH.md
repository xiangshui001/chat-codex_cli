# MVP-1 本机真实任务工作台

前端通过只读 HTTP 服务读取 MVP-1 的 SQLite、Codex JSONL 与工作目录，不使用 Mock 数据，不写 GitHub、不启动 Codex、不修改队列或配置。现役 V1 保持不变。

## 打开

在源码 `web/app` 目录安装依赖并构建：

```text
npm ci
npm run build
```

Ubuntu / WSL 内，把含 V2 0.0.6 的源码安装到独立虚拟环境，运行：

```bash
/ABS/VENV/bin/pip install /ABS/SOURCE/codex-github-local-v2
/ABS/VENV/bin/codex-github-local-v2-workbench --config /ABS/PRIVATE/mvp1-config.json --dist /ABS/SOURCE/web/app/dist --port 8791
```

Windows 浏览器打开 **http://127.0.0.1:8791/**，会进入 `?view=live`。配置沿用执行端的 MVP-1 配置，只读服务不会替你启动监听。保持两个进程运行。未安装开机自启，台式机 WSL 仍需独立验证。

开发模式 `npm run dev` 的 `http://127.0.0.1:5173/?view=live` 会把真实 API 代理到 8791。原默认演示页面保留，并增加真实工作台入口。`?harness=local-smoke` 仍是独立的确定性测试环境，不代表真实执行。

## 能看到什么

- 最近 100 条已领取任务，支持仓库 / Issue / 文本搜索，所有状态的总计来自数据库。
- 已领取、工作区准备、Codex 启动、结束、Issue 回写的真实时间线。
- Codex 执行命令、已输出的结果、文件修改事件和最终回复；stdout 写出后每约 3 秒刷新。长命令可能只有开始信息，结束后才出现完整输出。
- CLI 版本、退出码、失败原因、允许路径、Git 可见变化（含未跟踪文件）、本机工作目录和 Issue 回执链接。
- 监听进程是否占有执行锁。它不表示网络畅通，也不是远端心跳；进程异常后遗留的 running 记录不会被伪装成正在运行的进程。
- 连接失败保留最近一次成功读取，并提示数据可能过期，自动重连，不回退到模拟数据。

尚未被 poller 领取的 GitHub Issue 不在本地 SQLite 中，暂不显示。显示状态仍为 queued / running / succeeded / failed / stale_base；没有独立 reviewer、自动 PR、远程模型控制或手动重跑按钮。

## 本机数据边界

服务仅绑定 `127.0.0.1`，校验 Host / Origin 和 API 请求标记，拒绝写请求；仅服务构建产物，不把状态目录暴露为静态文件。SQLite 使用 `mode=ro` 与 `query_only`，核对账号 / Host / 根目录绑定。文件变化查询不写 Git 索引，不读取任意远程传入路径。

日志只投影已知事件字段，不展示 reasoning 或未知工具原始载荷；命令与可见输出按文本渲染。读取尾部最多 512 KiB / 150 项，单项输出最多 8000 字符，stderr 最多 8 KiB，并明确提示截断。未完整写出的 JSON 行在下一轮重新读取。常见 token / password 格式会被遮盖，但这不是通用秘密识别器；页面只供本机本人查看，不要把它暴露到公网或上传截图中的业务信息。

不上传原始日志、数据库和真实配置。完整数据仍保存在执行端原目录，工作台退出不影响已运行的 poller。浏览器中的进程输出顺序不伪造为真实事件时间。

## 本轮验证

本电脑 Ubuntu 后端 162 项测试、V1 53 项回归通过；前端构建和 15 项单元测试通过。浏览器新增 3 项真实模式界面测试，并回归旧页面；真实 GitHub → 本机 Codex → 前端全过程另用安全任务验证，不以模拟测试代替。

详细环境、真实任务和浏览器观察记录保存在 [codex-cli 验证记录](https://github.com/xiangshui001/codex-cli/blob/workbench-records-20261004/docs/WORKBENCH_SMOKE_2026-10-04.md)。本电脑验证不代表台式机 WSL 通过。
