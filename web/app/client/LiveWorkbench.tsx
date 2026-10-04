import { useEffect, useRef, useState } from 'react';
import {
  Activity,
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  FileText,
  Radio,
  Terminal,
  WifiOff,
} from 'lucide-react';
import './styles.css';
import './live.css';

type State = 'queued' | 'running' | 'succeeded' | 'failed' | 'stale_base';
type Task = {
  request_id: string;
  repo: string;
  issue_number: number;
  issue_url: string;
  state: State;
  prompt: string;
  summary: string;
  error: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  cli_version: string | null;
  exit_code: number | null;
  receipt_comment_id: number | null;
  diff_nonempty: number | null;
};
type Overview = {
  source: 'local-mvp1';
  observed_at: string;
  host_id: string;
  owner: string;
  listener: 'running' | 'stopped' | 'unknown';
  counts: Partial<Record<State, number>>;
  tasks: Task[];
  limit: number;
};
type Detail = Task & {
  cwd: string | null;
  write_paths: string[];
  files: string[];
  files_error: string | null;
  events: { kind: string; at: string }[];
  stderr: string;
  stderr_truncated: boolean;
  progress: {
    truncated: boolean;
    partial_lines: number;
    items: {
      id: string;
      kind: string;
      status: string;
      title: string;
      text: string;
      exit_code?: number | null;
    }[];
  };
};
const labels: Record<State, string> = {
  queued: '准备执行',
  running: '执行中',
  succeeded: '已完成',
  failed: '失败',
  stale_base: '基线已变化',
};
const stages: Record<string, string> = {
  claimed: '已领取 GitHub 指令',
  workspace_preparing: '准备独立工作目录',
  workspace_prepared: '工作目录已就绪',
  started: '已记录执行信息',
  process_started: 'Codex 已启动',
  finished: '本机执行已结束',
  receipt_sent: '已回写 Issue',
  cleanup_failed: '进程清理需要检查',
  interrupted_cleanup_unknown: '中断后需要人工检查',
};
const time = (value: string | null) =>
  value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '尚未发生';
async function request<T>(path: string): Promise<T> {
  const response = await fetch('/api/mvp1/' + path, {
    headers: { 'X-Chat-Codex-Local': '1' },
    cache: 'no-store',
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok) throw new Error(`本机服务暂不可用（${response.status}）`);
  return response.json() as Promise<T>;
}
function Badge({ state }: { state: State }) {
  return <span className={'live-badge ' + state}>{labels[state]}</span>;
}

export function LiveWorkbench() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [selected, setSelected] = useState(() =>
    window.location.hash.startsWith('#task/') ? window.location.hash.slice(6) : '',
  );
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [follow, setFollow] = useState(false);
  const output = useRef<HTMLDivElement>(null);
  useEffect(() => {
    document.title = '真实任务 · chat-codex';
  }, []);
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    setDetail(null);
    async function refresh() {
      try {
        const snapshot = await request<Overview>('overview');
        if (snapshot.source !== 'local-mvp1' || !Array.isArray(snapshot.tasks))
          throw new Error('服务返回了不匹配的数据来源');
        if (stopped) return;
        setOverview(snapshot);
        const id = selected || snapshot.tasks[0]?.request_id;
        if (!selected && id) {
          setSelected(id);
          return;
        }
        if (id) {
          const task = await request<Detail>('tasks/' + encodeURIComponent(id));
          if (stopped) return;
          setDetail(task);
        }
        setError('');
      } catch (err) {
        if (!stopped) setError(err instanceof Error ? err.message : '连接失败');
      } finally {
        if (!stopped) timer = setTimeout(refresh, 3000);
      }
    }
    void refresh();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [selected]);
  useEffect(() => {
    if (follow && output.current) output.current.scrollTop = output.current.scrollHeight;
  }, [detail, follow]);
  const tasks = (overview?.tasks ?? []).filter((task) =>
    `${task.repo} ${task.issue_number} ${task.prompt} ${task.request_id}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  function select(id: string) {
    setSelected(id);
    window.history.replaceState(null, '', '#task/' + id);
  }
  const counts = overview?.counts ?? {};
  return (
    <div className="live-workbench">
      <header className="live-top">
        <a className="live-brand" href="?view=live">
          <span>
            <Terminal size={20} />
          </span>
          chat-codex <small>本机工作台</small>
        </a>
        <span className="live-source">
          <Radio size={14} /> 真实执行记录 · 只读
        </span>
      </header>
      <main className="live-layout">
        <section className="live-heading">
          <div>
            <p className="live-eyebrow">FROM ISSUE TO LOCAL CODEX</p>
            <h1>每一步执行，都看得见。</h1>
            <p>Chat 发布任务后，在这里查看本机 Codex 的进度与成果。</p>
          </div>
          <div className="live-host">
            <Activity size={18} />
            <div>
              <strong>{overview?.host_id ?? '正在连接本机'}</strong>
              <span>
                {overview
                  ? overview.listener === 'running'
                    ? '监听进程运行中'
                    : overview.listener === 'stopped'
                      ? '监听进程已停止'
                      : '监听状态未知'
                  : '读取本机记录…'}
              </span>
              <small>最近读取：{overview ? time(overview.observed_at) : '等待连接'}</small>
            </div>
          </div>
        </section>
        {error && (
          <div className="live-error" role="alert">
            <WifiOff size={18} />
            <div>
              <strong>连接中断，当前显示的数据可能已过期</strong>
              <p>{error}。正在自动重连，不会显示模拟数据。</p>
            </div>
          </div>
        )}
        {overview?.listener === 'stopped' && (
          <div className="live-notice">
            监听已停止。历史记录仍可查看，新 Issue 暂时不会被领取。任务状态是最后保存的记录。
          </div>
        )}
        <section className="live-stats" aria-label="任务统计">
          <div>
            <Clock3 />
            <span>准备执行</span>
            <strong>{counts.queued ?? 0}</strong>
          </div>
          <div>
            <Activity />
            <span>正在执行</span>
            <strong>{counts.running ?? 0}</strong>
          </div>
          <div>
            <CheckCircle2 />
            <span>已完成</span>
            <strong>{counts.succeeded ?? 0}</strong>
          </div>
          <div>
            <FileText />
            <span>需要查看</span>
            <strong>{(counts.failed ?? 0) + (counts.stale_base ?? 0)}</strong>
          </div>
        </section>
        <div className="live-columns">
          <aside className="live-task-panel">
            <div className="live-section-title">
              <h2>任务记录</h2>
              <small>最近 {overview?.limit ?? 100} 条</small>
            </div>
            <input
              aria-label="搜索真实任务"
              placeholder="搜索仓库、Issue 或任务…"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <div className="live-task-list">
              {tasks.map((task) => (
                <button
                  key={task.request_id}
                  className={'live-task ' + (selected === task.request_id ? 'selected' : '')}
                  onClick={() => select(task.request_id)}
                >
                  <div>
                    <strong>
                      #{task.issue_number} · {task.repo.split('/')[1]}
                    </strong>
                    <Badge state={task.state} />
                  </div>
                  <p>{task.prompt}</p>
                  <small>{time(task.created_at)}</small>
                </button>
              ))}
              {!tasks.length && (
                <p className="live-empty">
                  {overview ? '暂无匹配任务。Issue 被本机领取后会出现在这里。' : '正在读取任务…'}
                </p>
              )}
            </div>
          </aside>
          <section className="live-detail" aria-label="真实任务详情">
            {!detail ? (
              <div className="live-empty">
                {selected ? '正在读取执行记录…' : '选择任务查看执行过程'}
              </div>
            ) : (
              <>
                <div className="live-detail-head">
                  <div>
                    <p className="live-eyebrow">{detail.repo}</p>
                    <h2>
                      Issue #{detail.issue_number} <Badge state={detail.state} />
                    </h2>
                  </div>
                  <a className="live-link" href={detail.issue_url} target="_blank" rel="noreferrer">
                    <FileText size={16} /> 打开 Issue <ArrowUpRight size={14} />
                  </a>
                </div>
                <div className="live-request">
                  <strong>这次要做什么</strong>
                  <p>{detail.prompt}</p>
                  <div className="live-scopes">
                    {detail.write_paths.map((path) => (
                      <code key={path}>{path}</code>
                    ))}
                  </div>
                </div>
                <div className="live-result">
                  <strong>
                    {detail.summary ||
                      (detail.state === 'running'
                        ? 'Codex 正在执行，过程自动刷新。'
                        : '等待执行结果。')}
                  </strong>
                  {detail.error && <p className="live-failure">{detail.error}</p>}
                  <span>
                    CLI：{detail.cli_version ?? '尚未启动'} · 退出码：
                    {detail.exit_code ?? '尚未结束'}
                  </span>
                  {detail.receipt_comment_id ? (
                    <a
                      className="live-link"
                      href={`${detail.issue_url}#issuecomment-${detail.receipt_comment_id}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      查看 GitHub 回执 <ArrowUpRight size={14} />
                    </a>
                  ) : (
                    <span>GitHub 回执：{detail.finished_at ? '等待回写' : '执行结束后回写'}</span>
                  )}
                </div>
                <div className="live-process-grid">
                  <section>
                    <h3>执行阶段</h3>
                    <ol className="live-timeline">
                      {detail.events.map((event, index) => (
                        <li key={`${index}-${event.kind}`}>
                          <span className="live-step-dot" />
                          <strong>{stages[event.kind] ?? event.kind}</strong>
                          <time>{time(event.at)}</time>
                        </li>
                      ))}
                    </ol>
                  </section>
                  <section>
                    <h3>
                      文件变化 <small>{detail.files.length} 项</small>
                    </h3>
                    {detail.files_error ? (
                      <p>{detail.files_error}</p>
                    ) : detail.files.length ? (
                      <ul className="live-files">
                        {detail.files.map((path) => (
                          <li key={path}>
                            <FileText size={15} />
                            <code>{path}</code>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="live-muted">暂未检测到 Git 可见文件变化。</p>
                    )}
                    <p className="live-muted">包括未跟踪文件。成果留在本机，由你检查和决定提交。</p>
                    <details>
                      <summary>工作目录与任务编号</summary>
                      <code className="live-path">{detail.cwd ?? '准备中'}</code>
                      <code className="live-path">{detail.request_id}</code>
                    </details>
                  </section>
                </div>
                <section className="live-output-section">
                  <div className="live-section-title">
                    <h3>
                      <Terminal size={17} /> Codex 执行过程
                    </h3>
                    <label>
                      <input
                        type="checkbox"
                        checked={follow}
                        onChange={(event) => setFollow(event.target.checked)}
                      />{' '}
                      跟随最新
                    </label>
                  </div>
                  <p className="live-muted">
                    显示命令、可见输出、文件修改与回复；按日志顺序展示，不展示内部推理。
                  </p>
                  {detail.progress.truncated && (
                    <p className="live-notice">仅显示最近一段输出，完整记录保留在本机。</p>
                  )}
                  <div className="live-output" ref={output}>
                    {detail.progress.items.map((item) => (
                      <article key={item.id} className={'live-output-item ' + item.kind}>
                        <header>
                          <strong>{item.title}</strong>
                          <small
                            className={
                              item.exit_code != null && item.exit_code !== 0
                                ? 'live-command-failed'
                                : undefined
                            }
                          >
                            {item.exit_code != null
                              ? `exit ${item.exit_code}`
                              : item.status === 'in_progress'
                                ? '进行中'
                                : ''}
                          </small>
                        </header>
                        {item.text && <pre>{item.text}</pre>}
                      </article>
                    ))}
                    {!detail.progress.items.length && (
                      <p className="live-empty">尚无 Codex 输出，领取和准备过程见上方时间线。</p>
                    )}
                  </div>
                  {detail.progress.partial_lines > 0 && (
                    <small className="live-muted">
                      部分日志行尚未完整或无法解析，下次刷新会重新读取。
                    </small>
                  )}
                  {detail.stderr && (
                    <details className="live-stderr">
                      <summary>
                        运行诊断（stderr）{detail.stderr_truncated ? ' · 已截断' : ''}
                      </summary>
                      <pre>{detail.stderr}</pre>
                    </details>
                  )}
                </section>
              </>
            )}
          </section>
        </div>
        <footer className="live-footer">
          本机只读查看 · 每 3 秒自动刷新 · 数据来自 MVP-1 SQLite 与本机 Codex JSONL ·
          只显示已领取任务
        </footer>
      </main>
    </div>
  );
}
