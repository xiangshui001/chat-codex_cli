import { ArrowLeft, ChevronRight, FileJson } from 'lucide-react';
import { Button, Pill } from '../primitives/Atoms';
import type { Workspace, WorkspaceRoute } from '../client/useWorkspace';
import type { TaskDetail } from '../api-client/types';
import { Empty, Heading, Panel, TaskState, formatTime, stateMeta } from './WorkspaceViews';
type Navigate = (route: WorkspaceRoute) => void;

function ContractPanel({ task }: { task: TaskDetail }) {
  return (
    <Panel title="任务合同">
      <div className="section">
        <h3>目标</h3>
        <p>{task.raw.goal}</p>
      </div>
      <div className="section">
        <h3>
          Read scope <span className="small muted">允许读取</span>
        </h3>
        <div className="scope">
          {task.raw.read_scope.map((path) => (
            <code key={path}>{path}</code>
          ))}
        </div>
        <h3 className="space-top">
          Write scope <span className="small muted">允许候选 diff</span>
        </h3>
        <div className="scope write">
          {task.raw.write_scope.map((path) => (
            <code key={path}>{path}</code>
          ))}
        </div>
      </div>
      <div className="section two-col">
        <div>
          <h3>预算</h3>
          <p>
            {task.raw.budget.max_rounds} 轮 / {task.raw.budget.max_minutes} 分钟
          </p>
          <p className="small muted">独立审阅最多 {task.raw.budget.review_rounds} 轮</p>
        </div>
        <div>
          <h3>发布策略</h3>
          <p className="mono">{task.raw.publication.mode}</p>
          <p className="small muted">生产权限：{task.raw.production}</p>
        </div>
      </div>
      <div className="section">
        <h3>验收条件</h3>
        <ul className="acceptance">
          {task.raw.acceptance.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </div>
    </Panel>
  );
}
export function TaskDetailView({
  workspace,
  navigate,
}: {
  workspace: Workspace;
  navigate: Navigate;
}) {
  const query = workspace.task;
  return (
    <>
      <Button
        size="sm"
        className="back-button"
        icon={<ArrowLeft size={14} />}
        onClick={() => navigate({ view: 'tasks' })}
      >
        返回任务队列
      </Button>
      {query.loading ? (
        <Empty title="正在读取任务…" />
      ) : query.error ? (
        <Empty title="任务读取失败">{query.error}</Empty>
      ) : query.data ? (
        <>
          <Heading
            eyebrow={`${query.data.task_id} / TASK DETAIL`}
            title={query.data.title}
            action={<TaskState state={query.data.state} />}
          >
            {query.data.resolved
              ? `领取快照 revision ${query.data.claimed_runtime_revision} · 当前运行模型只读`
              : '尚未领取 · resolved 合同与 runtime snapshot 暂不可用'}
          </Heading>
          <div className="detail-columns">
            <div className="stack">
              <ContractPanel task={query.data} />
              <Panel title="检查与独立审阅">
                <div className="section">
                  <div className="row between">
                    <h3>Validation</h3>
                    <Pill tone={query.data.checks.status === 'pass' ? 'green' : 'amber'}>
                      {query.data.checks.status}
                    </Pill>
                  </div>
                  <p>{query.data.checks.summary}</p>
                </div>
                <div className="section">
                  <div className="row between">
                    <h3>Reviewer</h3>
                    <Pill tone={query.data.review.verdict === 'pass' ? 'green' : 'neutral'}>
                      {query.data.review.verdict}
                    </Pill>
                  </div>
                  <p>{query.data.review.summary}</p>
                </div>
              </Panel>
              <Panel title="冻结的模型策略">
                <div className="section">
                  {(['executor', 'reviewer'] as const).map((role) => (
                    <div className="kv" key={role}>
                      <span className="secondary">{role}</span>
                      <code data-testid={`${role}-frozen-model`}>
                        {query.data!.resolved?.model_policy[role].primary.name ?? '尚未领取'}
                      </code>
                    </div>
                  ))}
                  <p className="small muted">
                    显式指定模型继续按合同执行，runtime-default 在领取时解析。
                  </p>
                </div>
              </Panel>
            </div>
            <div className="stack">
              <Panel
                title="状态轨迹"
                extra={<Pill>{query.data.state_events_complete ? '完整' : '不完整'}</Pill>}
              >
                <div className="timeline">
                  {query.data.state_events.map((event, index) => (
                    <div className="event" key={`${event.at}-${index}`}>
                      <div className="row between">
                        <strong>{stateMeta[event.state].label}</strong>
                        <span className="small muted mono">{formatTime(event.at)}</span>
                      </div>
                      <p>{event.detail}</p>
                      <code className="small muted">{event.state}</code>
                    </div>
                  ))}
                </div>
                <div className="subnote">API 标记为不完整；审计 JSONL 单独提供。</div>
              </Panel>
              <Panel title="Evidence files" extra={<FileJson size={16} className="muted" />}>
                <div className="file-list">
                  {query.data.evidence.map((file) => (
                    <button
                      className="file-row"
                      key={file.name}
                      onClick={() =>
                        navigate({ view: 'evidence', taskId: query.data!.task_id, name: file.name })
                      }
                    >
                      <FileJson size={16} />
                      <div>
                        <span className="mono">{file.name}</span>
                        <span className="small muted">{file.note}</span>
                      </div>
                      <Pill tone={file.availability === 'available' ? 'green' : 'neutral'}>
                        {file.availability}
                      </Pill>
                    </button>
                  ))}
                </div>
              </Panel>
            </div>
          </div>
        </>
      ) : (
        <Empty title="没有可读取的任务" />
      )}
    </>
  );
}

export function EvidenceView({
  workspace,
  route,
  navigate,
}: {
  workspace: Workspace;
  route: Extract<WorkspaceRoute, { view: 'evidence' }>;
  navigate: Navigate;
}) {
  const detail = workspace.task.data;
  const query = workspace.evidence;
  return (
    <>
      <Heading eyebrow="EVIDENCE / AUDITABLE ARTIFACTS" title="任务证据">
        读取允许公开的合同、快照和摘要。缺失或未开放的证据会明确标记。
      </Heading>
      <div className="toolbar">
        <label htmlFor="evidence-task" className="small secondary">
          选择任务
        </label>
        <select
          id="evidence-task"
          value={workspace.selectedTaskId ?? ''}
          onChange={(event) =>
            navigate({ view: 'evidence', taskId: event.target.value, name: route.name })
          }
        >
          {workspace.data!.tasks.map((task) => (
            <option value={task.task_id} key={task.task_id}>
              {task.task_id} · {task.title}
            </option>
          ))}
        </select>
        <span className="spacer" />
        <Button
          size="sm"
          variant="outline"
          disabled={!workspace.selectedTaskId}
          onClick={() => navigate({ view: 'task', taskId: workspace.selectedTaskId! })}
        >
          任务详情 <ChevronRight size={14} />
        </Button>
      </div>
      <div className="evidence-layout">
        <Panel title="Evidence files" extra={<Pill>MOCK</Pill>}>
          {workspace.task.loading ? (
            <Empty title="正在读取文件列表…" />
          ) : workspace.task.error ? (
            <Empty title="文件列表读取失败">{workspace.task.error}</Empty>
          ) : (
            <div className="file-list">
              {detail?.evidence.map((file) => (
                <button
                  className={`file-row ${route.name === file.name ? 'selected' : ''}`}
                  key={file.name}
                  aria-pressed={route.name === file.name}
                  onClick={() =>
                    navigate({
                      view: 'evidence',
                      taskId: workspace.selectedTaskId,
                      name: file.name,
                    })
                  }
                >
                  <FileJson size={16} />
                  <div>
                    <span className="mono">{file.name}</span>
                    <span className="small muted">{file.availability}</span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </Panel>
        <Panel
          title={route.name}
          extra={<Pill>{workspace.selectedTaskId ?? '无任务'}</Pill>}
          className="evidence-content"
        >
          {query.loading ? (
            <Empty title="正在读取证据…" />
          ) : query.error ? (
            <Empty title="证据读取失败">{query.error}</Empty>
          ) : query.data?.availability === 'available' ? (
            <>
              <pre className="json" data-testid="evidence-text">
                {query.data.text}
              </pre>
              <div className="subnote">
                {query.data.content_type} · {query.data.redacted ? '公开投影' : '原始内容'} ·{' '}
                {query.data.note}
              </div>
            </>
          ) : (
            <Empty
              title={query.data?.availability === 'withheld' ? '此证据未开放' : '证据尚未生成'}
              icon={<FileJson size={26} />}
            >
              {query.data?.note ?? '请选择一个可读取的任务。'}
            </Empty>
          )}
        </Panel>
      </div>
    </>
  );
}
