import { useEffect, useRef, useState, type ReactNode } from 'react';
import {
  ArrowUpRight,
  ChevronRight,
  CircleAlert,
  Clock3,
  GitPullRequest,
  Layers3,
  LockKeyhole,
  Search,
  Server,
  ShieldCheck,
} from 'lucide-react';
import { Button, Input, Pill } from '../primitives/Atoms';
import type { Workspace, WorkspaceRoute } from '../client/useWorkspace';
import type { RunState, TaskView } from '../api-client/types';

type Navigate = (route: WorkspaceRoute) => void;
export const stateMeta: Record<
  RunState,
  { label: string; tone: 'neutral' | 'green' | 'amber' | 'red' | 'blue' }
> = {
  queued: { label: '等待领取', tone: 'neutral' },
  claimed: { label: '已领取', tone: 'blue' },
  preflight: { label: '模型探测', tone: 'blue' },
  executing: { label: '执行中', tone: 'blue' },
  validating: { label: '验证中', tone: 'blue' },
  reviewing: { label: '独立审阅', tone: 'amber' },
  manual_review_required: { label: '需人工复核', tone: 'amber' },
  publish_ready: { label: '待发布', tone: 'amber' },
  pr_open: { label: '等待人工决定', tone: 'amber' },
  accepted: { label: '已接纳', tone: 'green' },
  policy_blocked: { label: '策略阻止', tone: 'red' },
  model_unavailable: { label: '模型不可用', tone: 'red' },
  execution_failed: { label: '执行失败', tone: 'red' },
  validation_incomplete: { label: '验证不完整', tone: 'red' },
  review_rejected: { label: '审阅拒绝', tone: 'red' },
  publication_failed: { label: '发布失败', tone: 'red' },
  cancelled: { label: '已取消', tone: 'neutral' },
};
const groups: { id: string; label: string; states: RunState[]; tone: string }[] = [
  { id: 'queued', label: '等待领取', states: ['queued'], tone: 'neutral' },
  {
    id: 'running',
    label: '运行中',
    states: ['claimed', 'preflight', 'executing', 'validating'],
    tone: 'blue',
  },
  {
    id: 'reviewing',
    label: '审阅 / 待决定',
    states: ['reviewing', 'manual_review_required', 'publish_ready', 'pr_open'],
    tone: 'amber',
  },
  {
    id: 'failed',
    label: '异常',
    states: [
      'policy_blocked',
      'model_unavailable',
      'execution_failed',
      'validation_incomplete',
      'review_rejected',
      'publication_failed',
    ],
    tone: 'red',
  },
];
export function formatTime(value: string | null): string {
  return value
    ? new Intl.DateTimeFormat('zh-CN', {
        timeZone: 'Asia/Shanghai',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      }).format(new Date(value))
    : '尚无记录';
}
export function TaskState({ state }: { state: RunState }) {
  const meta = stateMeta[state];
  return (
    <div className="state-cell">
      <Pill tone={meta.tone}>{meta.label}</Pill>
      <code>{state}</code>
    </div>
  );
}
export function Heading({
  eyebrow,
  title,
  children,
  action,
}: {
  eyebrow: string;
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="heading">
      <div className="eyebrow">{eyebrow}</div>
      <div className="page-head">
        <h1>{title}</h1>
        {action}
      </div>
      <p>{children}</p>
    </div>
  );
}
export function Panel({
  title,
  children,
  extra,
  className = '',
}: {
  title: string;
  children: ReactNode;
  extra?: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-head">
        <h2>{title}</h2>
        {extra}
      </div>
      {children}
    </section>
  );
}
export function Empty({
  title,
  children,
  icon,
}: {
  title: string;
  children?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="empty">
      {icon ?? <Layers3 size={24} />}
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
function TaskTable({
  tasks,
  navigate,
  compact = false,
}: {
  tasks: TaskView[];
  navigate: Navigate;
  compact?: boolean;
}) {
  if (!tasks.length) return <Empty title="没有匹配的任务">调整搜索词或筛选条件后再试。</Empty>;
  return (
    <div className="table-scroll">
      <table className={compact ? 'task-table compact' : 'task-table'}>
        <thead>
          <tr>
            <th>任务</th>
            <th>状态</th>
            {!compact && (
              <>
                <th>领取模型</th>
                <th>开始 / 更新</th>
              </>
            )}
            <th>PR</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <tr key={task.task_id}>
              <td>
                <button
                  className="task-link"
                  onClick={() => navigate({ view: 'task', taskId: task.task_id })}
                >
                  <span className="mono task-id">{task.task_id}</span>
                  <strong>{task.title}</strong>
                </button>
              </td>
              <td>
                <TaskState state={task.state} />
              </td>
              {!compact && (
                <>
                  <td>
                    <div className="model-cell">
                      <code>
                        E ·{' '}
                        {task.resolved_models?.executor.primary.name ??
                          task.requested_models.executor.primary.name}
                      </code>
                      <code>
                        R ·{' '}
                        {task.resolved_models?.reviewer.primary.name ??
                          task.requested_models.reviewer.primary.name}
                      </code>
                      <span className="muted small">
                        {task.claimed_runtime_revision == null
                          ? '未领取 · 显示合同请求'
                          : `冻结 revision ${task.claimed_runtime_revision}`}
                      </span>
                    </div>
                  </td>
                  <td>
                    <div className="small secondary">{formatTime(task.started_at)}</div>
                    <div className="small muted">更新 {formatTime(task.updated_at)}</div>
                  </td>
                </>
              )}
              <td>
                {task.pr ? (
                  <div className="pr-cell">
                    <span className="row">
                      <GitPullRequest size={14} />#{task.pr.number}
                    </span>
                    <span className="small muted">
                      {task.pr.state === 'merged'
                        ? '已合并'
                        : task.pr.draft
                          ? 'Draft'
                          : task.pr.state}
                    </span>
                  </div>
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DashboardView({
  workspace,
  navigate,
}: {
  workspace: Workspace;
  navigate: Navigate;
}) {
  const data = workspace.data!;
  const runtime = data.runtime;
  const current = data.tasks.find((task) => task.task_id === runtime?.current_task_id);
  const host = data.hosts.find((item) => item.id === runtime?.current_host_id);
  const failures = data.tasks.filter((task) => groups[3].states.includes(task.state));
  return (
    <>
      <Heading
        eyebrow="DASHBOARD / WORKSPACE"
        title="工作区概览"
        action={
          <Button
            variant="outline"
            size="sm"
            onClick={() => void workspace.requestStatus()}
            disabled={!workspace.canControl || workspace.controlLocked}
          >
            查询控制状态
          </Button>
        }
      >
        从任务领取到人工决定，查看执行现场与可复核的证据。
      </Heading>
      <div className="stat-grid">
        {groups.map((group) => (
          <button
            key={group.id}
            className={`stat-card ${group.tone}`}
            onClick={() => navigate({ view: 'tasks' })}
          >
            <span>{group.label}</span>
            <strong>
              {data.tasks
                .filter((task) => group.states.includes(task.state))
                .length.toString()
                .padStart(2, '0')}
            </strong>
            <span className="small muted">
              查看任务 <ArrowUpRight size={12} />
            </span>
          </button>
        ))}
      </div>
      <div className="overview-columns">
        <div className="stack">
          <Panel
            title="当前执行"
            extra={
              <Pill tone={runtime?.controller_state === 'online' ? 'green' : 'neutral'}>
                <span className="dot" />
                Controller · {runtime?.controller_state ?? 'unknown'}
              </Pill>
            }
          >
            <div className="panel-pad current-task">
              <div className="row between">
                <span className="small muted mono">{current?.task_id ?? '暂无当前任务'}</span>
                <span className="small secondary">
                  <Server size={13} /> {host?.name ?? 'Host 未知'}
                </span>
              </div>
              <h3>{current?.title ?? '当前没有任务在执行'}</h3>
              {current && (
                <>
                  <TaskState state={current.state} />
                  <div className="runtime-models">
                    <div>
                      <span>Executor · 领取快照</span>
                      <code>{current.resolved_models?.executor.primary.name ?? '未知'}</code>
                    </div>
                    <div>
                      <span>Reviewer · 领取快照</span>
                      <code>{current.resolved_models?.reviewer.primary.name ?? '未知'}</code>
                    </div>
                  </div>
                  <div className="row between">
                    <span className="small muted">
                      <LockKeyhole size={13} /> 冻结 revision{' '}
                      {current.claimed_runtime_revision ?? '未知'}
                    </span>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => navigate({ view: 'task', taskId: current.task_id })}
                    >
                      任务详情 <ChevronRight size={14} />
                    </Button>
                  </div>
                </>
              )}
            </div>
            <div className="subnote">
              <Clock3 size={13} /> 状态观测于 {formatTime(runtime?.observed_at ?? null)} · 模拟心跳
            </div>
          </Panel>
          <Panel
            title="最近任务"
            extra={
              <Button size="sm" onClick={() => navigate({ view: 'tasks' })}>
                全部任务 <ChevronRight size={14} />
              </Button>
            }
          >
            <TaskTable tasks={data.tasks.slice(0, 4)} compact navigate={navigate} />
          </Panel>
        </div>
        <div className="stack">
          <Panel
            title="下一次领取的默认模型"
            extra={
              <Button size="sm" onClick={() => navigate({ view: 'models' })}>
                配置 <ChevronRight size={14} />
              </Button>
            }
          >
            {runtime ? (
              <>
                <div className="default-role">
                  <span>EXECUTOR</span>
                  <strong className="mono">{runtime.settings.executor.model}</strong>
                  <Pill>{runtime.settings.executor.effort}</Pill>
                </div>
                <div className="default-role">
                  <span>REVIEWER</span>
                  <strong className="mono">{runtime.settings.reviewer.model}</strong>
                  <Pill>{runtime.settings.reviewer.effort}</Pill>
                </div>
                <div className="subnote">仅影响未来领取的 runtime-default 项</div>
              </>
            ) : (
              <Empty title="Runtime 不可用" />
            )}
          </Panel>
          <Panel title="需要关注" extra={<CircleAlert size={16} className="muted" />}>
            {failures.length ? (
              failures.map((task) => (
                <button
                  className="attention-row"
                  key={task.task_id}
                  onClick={() => navigate({ view: 'task', taskId: task.task_id })}
                >
                  <span className="mono small muted">{task.task_id}</span>
                  <strong>{task.title}</strong>
                  <Pill tone="red">{stateMeta[task.state].label}</Pill>
                </button>
              ))
            ) : (
              <Empty title="暂无异常" />
            )}
            <div className="subnote">验证缺失也会保留在任务详情与 Draft PR 中。</div>
          </Panel>
          <div className="quiet-note">
            <ShieldCheck size={17} />
            <p>候选经独立审阅后提交 PR，最后由人决定合并。</p>
          </div>
        </div>
      </div>
    </>
  );
}

export function TasksView({
  workspace,
  navigate,
  focusSearch,
}: {
  workspace: Workspace;
  navigate: Navigate;
  focusSearch: number;
}) {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (focusSearch) input.current?.focus();
  }, [focusSearch]);
  const tasks = workspace.data!.tasks;
  const filtered = tasks.filter((task) => {
    const states = groups.find((group) => group.id === filter)?.states;
    return (
      (!states || states.includes(task.state)) &&
      `${task.task_id} ${task.title}`.toLowerCase().includes(query.toLowerCase())
    );
  });
  return (
    <>
      <Heading eyebrow="TASKS / FROZEN CONTRACTS" title="任务队列">
        保留每个任务的具体状态、领取模型和验证结果。
      </Heading>
      <div className="toolbar">
        <Input
          ref={input}
          icon={<Search size={16} />}
          aria-label="搜索任务"
          placeholder="搜索任务 ID 或标题…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className="task-search"
        />
        <div className="filter-pills">
          <Pill active={filter === 'all'} onClick={() => setFilter('all')}>
            全部 {tasks.length}
          </Pill>
          {groups.map((group) => (
            <Pill key={group.id} active={filter === group.id} onClick={() => setFilter(group.id)}>
              {group.label}
            </Pill>
          ))}
        </div>
      </div>
      <Panel
        title="任务列表"
        extra={<span className="small muted">{filtered.length} 个任务 · MOCK</span>}
      >
        <TaskTable tasks={filtered} navigate={navigate} />
      </Panel>
      <div className="quiet-note">
        <LockKeyhole size={16} />
        <p>已领取模型只读。修改默认配置不会热更新执行中的任务。</p>
      </div>
    </>
  );
}

export function HostsView({ workspace, navigate }: { workspace: Workspace; navigate: Navigate }) {
  return (
    <>
      <Heading eyebrow="HOSTS / EXECUTION SITES" title="执行主机">
        主机在线状态与队列暂停分别展示。这里的心跳和版本均为演示数据。
      </Heading>
      <div className="host-grid">
        {workspace.data!.hosts.map((host) => (
          <Panel
            key={host.id}
            title={host.name}
            extra={
              <Pill
                tone={
                  host.state === 'busy' ? 'blue' : host.state === 'online' ? 'green' : 'neutral'
                }
              >
                <span className="dot" />
                {host.state}
              </Pill>
            }
          >
            <div className="panel-pad">
              <div className="host-symbol">
                <Server size={24} />
              </div>
              <dl className="host-details">
                <div>
                  <dt>Host ID</dt>
                  <dd className="mono">{host.id}</dd>
                </div>
                <div>
                  <dt>Codex CLI</dt>
                  <dd>{host.codex_version ?? '未知'}</dd>
                </div>
                <div>
                  <dt>当前任务</dt>
                  <dd>
                    {host.current_task_id ? (
                      <button
                        className="inline-link mono"
                        onClick={() => navigate({ view: 'task', taskId: host.current_task_id! })}
                      >
                        {host.current_task_id} <ChevronRight size={12} />
                      </button>
                    ) : (
                      '无'
                    )}
                  </dd>
                </div>
                <div>
                  <dt>运行模型</dt>
                  <dd className="mono">{host.current_model?.name ?? '无'}</dd>
                </div>
                <div>
                  <dt>最近心跳</dt>
                  <dd>{formatTime(host.last_heartbeat)}</dd>
                </div>
              </dl>
            </div>
          </Panel>
        ))}
      </div>
      {!workspace.data!.hosts.length && <Empty title="没有主机记录" />}
      <div className="quiet-note">
        <CircleAlert size={17} />
        <p>真实 Host registry 尚未接入；离线主机保留最后一次观测信息。</p>
      </div>
    </>
  );
}

export function ReviewsView({ workspace, navigate }: { workspace: Workspace; navigate: Navigate }) {
  const tasks = workspace.data!.tasks.filter((task) => task.pr);
  return (
    <>
      <Heading eyebrow="PR REVIEW / HUMAN DECISION" title="PR 审阅">
        汇总候选 PR。检查与独立审阅证据在任务详情中，最后的合并由人完成。
      </Heading>
      <div className="review-grid">
        {tasks.map((task) => (
          <Panel
            key={task.task_id}
            title={`PR #${task.pr!.number}`}
            extra={
              <Pill tone={task.pr!.state === 'merged' ? 'green' : 'amber'}>
                {task.pr!.state === 'merged' ? '模拟已合并' : task.pr!.draft ? 'Draft' : 'Open'}
              </Pill>
            }
          >
            <div className="panel-pad">
              <span className="small muted mono">{task.task_id}</span>
              <h3 className="space-top">{task.title}</h3>
              <TaskState state={task.state} />
              <div className="space-top">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => navigate({ view: 'task', taskId: task.task_id })}
                >
                  查看检查与证据 <ChevronRight size={14} />
                </Button>
              </div>
            </div>
          </Panel>
        ))}
      </div>
      {!tasks.length && <Empty title="暂无 PR" />}
    </>
  );
}

export function MembersView() {
  return (
    <>
      <Heading eyebrow="CAPABILITIES / FUTURE COLLABORATION" title="协作权限边界">
        现在只保留 capabilities 和路由守卫。真实登录、OAuth 与成员管理留待后续接入。
      </Heading>
      <div className="alert">
        <ShieldCheck size={17} />
        <span>演示身份切换只改变 MockClient 会话，没有登录或权限授予效果。</span>
      </div>
      <Panel title="角色与能力">
        <div className="table-scroll">
          <table className="permission-table">
            <thead>
              <tr>
                <th>角色</th>
                <th>任务 / 主机 / 证据</th>
                <th>模型与队列</th>
                <th>成员入口</th>
              </tr>
            </thead>
            <tbody>
              {['Owner', 'Operator', 'Reviewer', 'Viewer'].map((role, index) => (
                <tr key={role}>
                  <td>
                    <strong>{role}</strong>
                  </td>
                  <td>按仓库授权读取</td>
                  <td>{index < 2 ? '可提交控制' : '只读'}</td>
                  <td>{index < 2 ? '可查看' : '无入口'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <div className="quiet-note">
        <LockKeyhole size={16} />
        <p>真实 API 必须逐次验证身份和仓库权限，不能信任浏览器提交的角色。</p>
      </div>
    </>
  );
}
