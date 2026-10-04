# Chat 协作手册：MVP-2

当前协议为 `[codex-v2-mvp2]`，完整示例见 [MVP-2](V2-MVP2.md)。账号、机器标识及模型根据执行端配置填写；不预设某个用户或某台电脑。

## 发布任务

1. 根据用户授权明确目标仓库、执行机 host_id、允许写路径、任务要求、新/旧对话、模型模式/型号/思考强度。`desktop` 只是机器标识示例，它不是模型名；每台电脑必须有唯一标识。
2. 读取目标默认分支当前完整 40 位 SHA。空仓库必须先有初始提交。为每次任务生成新的规范 UUID request_id。
3. Issue 发布在目标仓库，或执行机配置的 hub_repo（例如本人 codex-cli）。授权 JSON 的 repo 始终为实际工作目标。只向本人拥有且两端凭据均可访问的仓库派单。
4. 创建标题以 `[codex-v2-mvp2]` 开头的开放 Issue，添加唯一、未编辑的 owner 授权评论。第一行 `/codex-v2-mvp2 run`，后接 JSON，顶层仅含 request_id、host_id、repo、base_sha、session、models、task；task 仅含 prompt 和 write_paths。
5. 新对话 `session: {"mode":"new"}`；旧对话 `session: {"mode":"resume","id":"完整 UUID"}`。不能使用 last 或其它机器的会话。
6. models.mode 为 gpt / api / gpt-led；primary 必含 provider、model、effort。GPT primary 使用 codex；其它模式用本机登记的其它 provider；GPT 主导还需非空 collaborators，每项也含 provider/model/effort。API 模型和强度应从执行机 models.json 或已鉴权的 GET /v1/models 读取，精确复制标识，不能把展示名称或其它服务的强度直接当作登记值。
7. 给用户 Issue 链接。收到机器完成回执后，提供会话 ID、成果 PR 和本地工作目录，核对文件变化与实际任务要求。

接口地址、密钥、环境变量、任意 cwd 或 CLI 参数不能放入派单 JSON。write_paths 只能是明确相对路径或带 / 后缀的目录，拒绝绝对路径、父目录跳转、保留目录与通配符。

## 判断与恢复

状态为 queued / running / succeeded / failed / stale_base。running 可能正在执行，也可能已执行完成、等待补做 PR 发布；以工作台发布进度为准。succeeded 包含执行与检查成功、分支推送和草稿 PR 创建成功；没有文件变化时回执明确说明没有 PR。完成回执写回 Issue 原仓库，PR 发到目标仓库。

续接保留本机对话上下文，新任务仍使用独立克隆和本次默认分支基线；不会自动继承旧任务未合并的代码。需要旧成果时先按用户授权合并原 PR，或把必要文件纳入当前任务要求。

API 任务失败但已保存私有 context.json 时，只有用户明确要求继续，才按[API 恢复步骤](V2-MVP2.md#api-不完整回复与失败会话恢复)登记失败会话；取得 session_id 后发布新授权，原记录不修改，也不复用 request_id。运行中出现截断或空回复会自动保留上下文续写，不执行截断工具指令；不能把续写中途的部分文字当作完成成果。

失败或 stale_base 后先核对原因和已有文件。不要编辑旧授权、复用 request_id、删除数据库、force push 或自动重放。已完成执行的发布网络失败由控制器补做发布；中断执行/不确定 commit 需要人工核对。PR 最终由用户人工审查和合并，不能把创建 PR 当作验收完成。
