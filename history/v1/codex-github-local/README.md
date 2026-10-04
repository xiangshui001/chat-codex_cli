> 历史 V1：已退出当前安装入口。[当前版本](../../../README.md)。

# codex-github-local 0.1.0

运行组件：bridge.py、engine/runner.py、handoff_check.py。Ubuntu / Linux 运行；Python 只使用标准库，外部需要 Git、GitHub CLI 和已登录的 Codex CLI。

完整入口见 [V1 用户使用手册](../docs/用户使用手册.md) 和 [V1 Chat 协作手册](../docs/Chat协作手册.md)。

```bash
python3 verify.py
```

复制 `profiles/example.json` 到自己的本地配置文件，填写真实 repository 与 authorized_users，检查允许路径和检查项后执行：

```bash
python3 setup.py --profile /实际路径/项目配置.json
```

默认 profile 只有 OWNER/REPO 和 YOUR_GITHUB_LOGIN 占位符，不能直接用于真实仓库。示例只开放 docs/、tasks/，固定检查为候选提交空白格式和 handoff 结构，不能证明功能正确。

安装会保留已登记配置；更新 profile 后重跑 setup 不会覆盖现有生效配置。当前 0.1.0 安装器也不会覆盖不同字节的已安装运行组件。这个公开版的核心运行组件与历史验证版相同；不是对现有业务环境的自动升级。

支持 main、GitHub HTTPS、单机串行、人工合并。自动程序不会合并 PR，不部署、不自动重放 blocked。记录位于 ~/.local/state/codex-github-local；只在启动时枚举仓库，新登记后需重启 watch。

原生 CLI 交互在独立克隆进行。自动任务的候选不可直接由另一会话修改；手动任务无自动程序的检查或 accepted 保证。
