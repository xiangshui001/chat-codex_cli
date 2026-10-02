import { useEffect, useRef, useState } from 'react';
import {
  Activity,
  ChevronRight,
  Code2,
  FileJson,
  FlaskConical,
  GitPullRequest,
  LayoutDashboard,
  ListTodo,
  Menu,
  Moon,
  Pause,
  Play,
  RefreshCw,
  Search,
  Server,
  Settings2,
  ShieldCheck,
  Sun,
  Users,
  X,
} from 'lucide-react';
import { Button, Pill } from '../primitives/Atoms';
import type { ChatCodexClient } from '../api-client/client';
import type { MockDemo, MockOutcome } from '../api-client/mock';
import { evidenceNames } from '../api-client/types';
import type { Capability, Role } from '../api-client/types';
import { useWorkspace, type Workspace, type WorkspaceRoute } from './useWorkspace';
import {
  DashboardView,
  Empty,
  HostsView,
  MembersView,
  ReviewsView,
  TasksView,
} from '../features/WorkspaceViews';
import { EvidenceView, TaskDetailView } from '../features/TaskViews';
import { ModelsView } from '../features/ModelsView';
import './styles.css';

const navigation = [
  {
    view: 'dashboard',
    title: '工作区概览',
    en: 'Dashboard',
    icon: LayoutDashboard,
    capability: 'runtime:read',
  },
  { view: 'tasks', title: '任务队列', en: 'Tasks', icon: ListTodo, capability: 'tasks:read' },
  { view: 'models', title: '模型配置', en: 'Models', icon: Settings2, capability: 'runtime:read' },
  { view: 'hosts', title: '执行主机', en: 'Hosts', icon: Server, capability: 'hosts:read' },
  {
    view: 'evidence',
    title: '任务证据',
    en: 'Evidence',
    icon: FileJson,
    capability: 'evidence:read',
  },
  {
    view: 'reviews',
    title: 'PR 审阅',
    en: 'PR Review',
    icon: GitPullRequest,
    capability: 'tasks:read',
  },
  {
    view: 'members',
    title: '协作权限',
    en: 'Capabilities',
    icon: Users,
    capability: 'members:read',
  },
] as const;
export function routeHref(route: WorkspaceRoute): string {
  if (route.view === 'task') return `#/tasks/${encodeURIComponent(route.taskId)}`;
  if (route.view === 'evidence')
    return `#/evidence${route.taskId ? `/${encodeURIComponent(route.taskId)}/${route.name}` : ''}`;
  return `#/${route.view}`;
}
export function readRoute(hash: string): WorkspaceRoute {
  try {
    const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent);
    const [view = 'dashboard', id, name] = parts;
    if (view === 'tasks' && id && parts.length === 2) return { view: 'task', taskId: id };
    if (
      view === 'evidence' &&
      parts.length <= 3 &&
      (!name || evidenceNames.includes(name as (typeof evidenceNames)[number]))
    ) {
      return {
        view: 'evidence',
        taskId: id,
        name: (name as (typeof evidenceNames)[number]) ?? 'task.resolved.json',
      };
    }
    if (
      parts.length <= 1 &&
      navigation.some((item) => item.view === view && item.view !== 'evidence')
    ) {
      return { view: view as Exclude<WorkspaceRoute['view'], 'task' | 'evidence'> };
    }
  } catch {
    /* Invalid URL encoding has a visible not-found state. */
  }
  return { view: 'not-found' };
}
function ControlNotice({ workspace }: { workspace: Workspace }) {
  const command = workspace.control;
  if (!command) return null;
  const outcome = command.receipt?.outcome ?? 'pending';
  const labels = {
    pending: '等待生效',
    applying: '正在应用',
    applied: '已生效',
    model_unavailable: '模型不可用',
    rejected: '请求被拒绝',
    unknown: '结果待确认',
  };
  const tone =
    outcome === 'applied'
      ? 'green'
      : ['model_unavailable', 'rejected'].includes(outcome)
        ? 'red'
        : outcome === 'unknown'
          ? 'amber'
          : 'blue';
  return (
    <div
      className={`control-notice alert ${tone}`}
      role="status"
      aria-live="polite"
      data-testid="control-receipt"
    >
      <Activity size={18} />
      <div className="grow">
        <strong>
          {labels[outcome]} <span className="small mono">{outcome}</span>
        </strong>
        <p>{command.receipt?.message ?? '正在提交控制意图；当前默认值保持不变。'}</p>
        <code className="small request-id">request_id · {command.request.request_id}</code>
        {command.error && <p>{command.error}</p>}
      </div>
      {outcome === 'unknown' && (
        <Button
          size="sm"
          variant="outline"
          disabled={command.busy}
          onClick={() => void workspace.recheckControl()}
        >
          {command.busy ? '查询中…' : '查询同一请求'}
        </Button>
      )}
    </div>
  );
}

export function AppShell({ client, demo }: { client: ChatCodexClient; demo?: MockDemo }) {
  const [route, setRoute] = useState(() => readRoute(window.location.hash));
  const [menuOpen, setMenuOpen] = useState(false);
  const [mobile, setMobile] = useState(() => window.matchMedia('(max-width: 1024px)').matches);
  const [focusSearch, setFocusSearch] = useState(0);
  const [scenario, setScenario] = useState<MockOutcome>('applied');
  const [dark, setDark] = useState(() => {
    try {
      return localStorage.getItem('chat-codex-theme') === 'dark';
    } catch {
      return false;
    }
  });
  const sidebar = useRef<HTMLElement>(null);
  const menuButton = useRef<HTMLButtonElement>(null);
  const workspace = useWorkspace(client, route);
  const data = workspace.data;
  const routeKey = route.view === 'task' ? 'tasks' : route.view;
  const currentNavigation = navigation.find((item) => item.view === routeKey);
  const title = route.view === 'task' ? '任务详情' : (currentNavigation?.title ?? '页面不存在');
  const can = (capability: Capability) => data?.session.capabilities.includes(capability) ?? false;
  const navigate = (next: WorkspaceRoute) => {
    setMenuOpen(false);
    window.location.hash = routeHref(next);
  };
  useEffect(() => {
    const changed = () => {
      setRoute(readRoute(window.location.hash));
      setMenuOpen(false);
      window.scrollTo(0, 0);
    };
    window.addEventListener('hashchange', changed);
    return () => window.removeEventListener('hashchange', changed);
  }, []);
  useEffect(() => {
    document.title = `${title} · chat-codex v2`;
  }, [title]);
  useEffect(() => {
    const media = window.matchMedia('(max-width: 1024px)');
    const changed = () => {
      setMobile(media.matches);
      if (!media.matches) setMenuOpen(false);
    };
    media.addEventListener('change', changed);
    return () => media.removeEventListener('change', changed);
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    try {
      localStorage.setItem('chat-codex-theme', dark ? 'dark' : 'light');
    } catch {
      /* Optional preference persistence. */
    }
  }, [dark]);
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        navigate({ view: 'tasks' });
        setFocusSearch((value) => value + 1);
      }
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, []);
  useEffect(() => {
    if (!menuOpen) return;
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const focusable = () =>
      Array.from(
        sidebar.current?.querySelectorAll<HTMLElement>(
          'a[href], button:not(:disabled), select:not(:disabled)',
        ) ?? [],
      );
    focusable()[0]?.focus();
    const trap = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setMenuOpen(false);
      }
      if (event.key !== 'Tab') return;
      const items = focusable();
      const first = items[0],
        last = items.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      }
      if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    window.addEventListener('keydown', trap);
    return () => {
      document.body.style.overflow = oldOverflow;
      window.removeEventListener('keydown', trap);
      menuButton.current?.focus();
    };
  }, [menuOpen]);
  useEffect(() => {
    if (workspace.control?.request.request_id) setScenario('applied');
  }, [workspace.control?.request.request_id]);
  const queuePaused = data?.runtime?.settings.paused;
  const navSection = (items: (typeof navigation)[number][]) => (
    <nav>
      {items
        .filter((item) => can(item.capability))
        .map((item) => (
          <a
            href={item.view === 'evidence' ? '#/evidence' : `#/${item.view}`}
            className={`navitem ${routeKey === item.view ? 'active' : ''}`}
            key={item.view}
            aria-current={routeKey === item.view ? 'page' : undefined}
            onClick={() => setMenuOpen(false)}
          >
            <item.icon size={18} />
            <span>{item.title}</span>
            {item.view === 'tasks' && (
              <span className="navcount">{data?.tasks.length.toString().padStart(2, '0')}</span>
            )}
          </a>
        ))}
    </nav>
  );
  const views = {
    dashboard: () => <DashboardView workspace={workspace} navigate={navigate} />,
    tasks: () => <TasksView workspace={workspace} navigate={navigate} focusSearch={focusSearch} />,
    task: () => <TaskDetailView workspace={workspace} navigate={navigate} />,
    models: () => <ModelsView workspace={workspace} />,
    hosts: () => <HostsView workspace={workspace} navigate={navigate} />,
    evidence: () => (
      <EvidenceView
        workspace={workspace}
        navigate={navigate}
        route={route as Extract<WorkspaceRoute, { view: 'evidence' }>}
      />
    ),
    reviews: () => <ReviewsView workspace={workspace} navigate={navigate} />,
    members: () => <MembersView />,
    'not-found': () => <Empty title="页面不存在">使用左侧导航返回工作区。</Empty>,
  };
  return (
    <div className={`shell ${menuOpen ? 'menu-open' : ''}`}>
      {menuOpen && (
        <button
          className="scrim"
          tabIndex={-1}
          onClick={() => setMenuOpen(false)}
          aria-label="关闭导航遮罩"
        />
      )}
      <aside
        className="sidebar"
        ref={sidebar}
        inert={(mobile && !menuOpen) || undefined}
        aria-hidden={(mobile && !menuOpen) || undefined}
        role={menuOpen ? 'dialog' : undefined}
        aria-modal={menuOpen || undefined}
        aria-label="工作区导航"
      >
        <div className="brand">
          <span className="brandmark">
            <Code2 size={19} />
          </span>
          <strong>
            chat-codex <small>v2</small>
          </strong>
          <Button
            size="sm"
            className="mobile-close"
            aria-label="关闭导航"
            onClick={() => setMenuOpen(false)}
          >
            <X size={17} />
          </Button>
        </div>
        <div className="project">
          <span className="eyebrow">PROJECT / {data?.session.data_origin ?? 'MOCK'}</span>
          <strong>{data?.session.repository ?? '读取工作区…'}</strong>
          <span className="small muted">Codex 执行与证据工作区</span>
        </div>
        <div className="navlabel">工作区</div>
        {navSection(navigation.slice(0, 5))}
        <div className="navlabel collaboration-label">协作</div>
        {navSection(navigation.slice(5))}
        <div className="sidebar-bottom">
          <div className="sidebar-control">
            <div className="row between">
              <span className="small secondary">新任务领取</span>
              <Pill tone={queuePaused ? 'amber' : 'green'}>
                <span className="dot" />
                {queuePaused ? '暂停' : '可领取'}
              </Pill>
            </div>
            <Button
              variant="outline"
              disabled={!workspace.canControl || workspace.controlLocked || !data?.runtime}
              onClick={() => void workspace.toggleQueue()}
              icon={queuePaused ? <Play size={14} /> : <Pause size={14} />}
            >
              {queuePaused ? '恢复领取' : '暂停新任务'}
            </Button>
            <p className="small muted">当前任务继续执行</p>
          </div>
          <div className="sidebar-foot">
            <div className="row between">
              <span className="small secondary">界面外观</span>
              <Button
                size="sm"
                aria-label="切换亮暗主题"
                onClick={() => setDark((value) => !value)}
              >
                {dark ? <Moon size={16} /> : <Sun size={16} />}
              </Button>
            </div>
            <span className="small muted">DSH UI adaptation · React</span>
          </div>
        </div>
      </aside>
      <div className="main" inert={menuOpen || undefined}>
        <header className="topbar">
          <Button
            ref={menuButton}
            className="mobile-toggle"
            aria-label="打开导航"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen(true)}
          >
            <Menu size={19} />
          </Button>
          <div className="breadcrumb">
            <span className="desktop">Workspace</span>
            <ChevronRight className="desktop" size={13} />
            <strong>{title}</strong>
          </div>
          <div className="topright">
            <Button
              size="sm"
              className="global-search"
              aria-label="打开任务搜索"
              onClick={() => {
                navigate({ view: 'tasks' });
                setFocusSearch((value) => value + 1);
              }}
            >
              <Search size={15} />
              <span>搜索任务</span>
              <kbd>⌘ K</kbd>
            </Button>
            <Pill tone="blue">
              {data?.session.execution_mode === 'local-smoke'
                ? '本地确定性验证'
                : data?.session.data_origin === 'live'
                  ? 'Live API'
                  : 'Mock API'}
            </Pill>
            <Button
              size="sm"
              aria-label="刷新工作区"
              disabled={workspace.loading}
              onClick={() => void workspace.refresh()}
            >
              <RefreshCw size={15} className={workspace.loading ? 'spin' : ''} />
            </Button>
            <span className="avatar" title={data?.session.role}>
              {data?.session.role.slice(0, 1).toUpperCase() ?? 'O'}
            </span>
          </div>
        </header>
        <main className="content" id="main-content">
          {demo && data?.session.data_origin === 'mock' && (
            <details className="demo-tools">
              <summary>
                <FlaskConical size={14} />
                <span>Mock 演示场景</span>
                <span className="small muted">未连接 GitHub / Codex Host</span>
              </summary>
              <div className="demo-controls">
                <label>
                  演示身份
                  <select
                    aria-label="演示身份"
                    value={data.session.role}
                    disabled={workspace.loading || workspace.controlLocked}
                    onChange={(event) => {
                      demo.setRole(event.target.value as Role);
                      void workspace.refresh();
                    }}
                  >
                    {(['owner', 'operator', 'reviewer', 'viewer'] as const).map((role) => (
                      <option value={role} key={role}>
                        {role}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  下一次控制（仅一次）
                  <select
                    aria-label="下一次控制结果"
                    value={scenario}
                    disabled={workspace.controlLocked}
                    onChange={(event) => {
                      const value = event.target.value as MockOutcome;
                      setScenario(value);
                      demo.setNextOutcome(value);
                    }}
                  >
                    <option value="applied">成功 applied</option>
                    <option value="model_unavailable">模型不可用</option>
                    <option value="unknown">结果待确认</option>
                    <option value="rejected">请求被拒绝</option>
                  </select>
                </label>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={workspace.loading}
                  onClick={() => {
                    demo.failNextRead();
                    void workspace.refresh();
                  }}
                >
                  演示读取失败
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={workspace.controlLocked}
                  onClick={() => {
                    window.location.hash = '#/login';
                  }}
                >
                  查看未登录页
                </Button>
                <p className="small muted">角色切换无认证效果；刷新页面重置模拟运行状态。</p>
              </div>
            </details>
          )}
          {workspace.error && (
            <div className="alert red" role="alert">
              <Activity size={17} />
              <div className="grow">
                <strong>工作区读取失败</strong>
                <p>
                  {workspace.error}
                  {data ? ' 当前显示上次成功读取的数据，写操作已禁用。' : ''}
                </p>
              </div>
              <Button size="sm" variant="outline" onClick={() => void workspace.refresh()}>
                重试读取
              </Button>
            </div>
          )}
          <ControlNotice workspace={workspace} />
          {!data ? (
            <Empty title={workspace.loading ? '正在读取工作区…' : '暂时无法读取工作区'}>
              数据通过统一 ChatCodexClient 加载。
            </Empty>
          ) : currentNavigation && !can(currentNavigation.capability) ? (
            <Empty title="权限受限" icon={<ShieldCheck size={25} />}>
              当前会话没有 {currentNavigation.capability} 能力。
            </Empty>
          ) : (
            views[route.view]()
          )}
          <footer className="footer">
            <span>
              {data?.session.data_origin === 'live'
                ? '服务端权威状态'
                : '全部为模拟数据 · 刷新重置 · 未连接真实后端'}
            </span>
            <span>chat-codex v2 · React workspace</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
