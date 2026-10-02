import { evidenceNames } from './types';
import type {
  FrozenTask,
  HostView,
  ModelOption,
  RunState,
  RuntimeSettings,
  TaskDetail,
} from './types';

// Entirely fictional fixtures; these IDs do not refer to the user's repository.
export const demoRepository = 'demo/codex-workbench';
export const demoTime = '2026-10-02T03:40:00Z';
export const initialSettings: RuntimeSettings = {
  paused: false,
  executor: { model: 'gpt-6.1-sol', effort: 'high' },
  reviewer: { model: 'gpt-6-sol', effort: 'high' },
  revision: 17,
  last_control_id: null,
};

const definitions: {
  id: string;
  title: string;
  state: RunState;
  pinned?: boolean;
  incomplete?: boolean;
  pr?: number;
}[] = [
  { id: 'GH-42', title: '实现任务证据的只读投影', state: 'executing' },
  { id: 'GH-43', title: '补充队列暂停的使用说明', state: 'queued' },
  { id: 'GH-44', title: '检查 worktree 的路径边界', state: 'reviewing', pinned: true },
  { id: 'GH-41', title: '新增模型 preflight 摘要', state: 'pr_open', pr: 12 },
  { id: 'GH-40', title: '整理 v2 控制协议说明', state: 'accepted', pr: 11 },
  { id: 'GH-39', title: '浏览器布局验证与人工复核', state: 'pr_open', incomplete: true, pr: 10 },
  { id: 'GH-38', title: '核对备用模型的可用性', state: 'model_unavailable' },
];

function makeTask(definition: (typeof definitions)[number]): TaskDetail {
  const { id, title, state, pinned, incomplete, pr } = definition;
  const claimed = state !== 'queued';
  const raw: FrozenTask = {
    version: 2,
    repository: demoRepository,
    base_sha: 'a'.repeat(40),
    task_id: id,
    task_type: 'code-change',
    title,
    goal: `${title}，在授权范围内提交可复核的候选与检查摘要。`,
    context: '仅用于前端演示；未执行真实 Codex 或 GitHub 任务。',
    read_scope: ['src/**', 'tests/**', 'docs/**'],
    write_scope: ['src/evidence/**', 'tests/evidence/**', `tasks/${id}/`],
    checks: ['static-build', 'unit-tests', 'browser-check'],
    acceptance: ['证据按允许的文件名展示', '领取后的模型与配置快照保持只读'],
    model_policy: {
      executor: {
        primary: { name: pinned ? 'gpt-6-sol' : 'runtime-default', effort: 'medium' },
        fallbacks: [],
      },
      reviewer: { primary: { name: 'runtime-default', effort: 'high' }, fallbacks: [] },
    },
    budget: { max_rounds: 2, max_minutes: 45, review_rounds: 1 },
    network: 'deny',
    production: 'deny',
    publication: { mode: 'draft_pr', draft_on_incomplete_validation: true },
  };
  // Precomputed fixture snapshots, independent of every future control command.
  const resolved = claimed ? structuredClone(raw) : null;
  if (resolved) {
    resolved.model_policy.executor.primary = pinned
      ? { name: 'gpt-6-sol', effort: 'medium' }
      : { name: initialSettings.executor.model, effort: initialSettings.executor.effort };
    resolved.model_policy.reviewer.primary = {
      name: initialSettings.reviewer.model,
      effort: initialSettings.reviewer.effort,
    };
  }
  const checked = ['reviewing', 'pr_open', 'accepted'].includes(state);
  const reviewed = ['pr_open', 'accepted'].includes(state);
  return {
    task_id: id,
    title,
    state,
    requested_models: raw.model_policy,
    resolved_models: resolved?.model_policy ?? null,
    claimed_runtime_revision: claimed ? 17 : null,
    started_at: claimed ? '2026-10-02T03:12:00Z' : null,
    updated_at: demoTime,
    pr: pr
      ? {
          number: pr,
          url: null,
          draft: state !== 'accepted',
          state: state === 'accepted' ? 'merged' : 'open',
        }
      : null,
    raw,
    resolved,
    runtime_snapshot: claimed ? structuredClone(initialSettings) : null,
    state_events: claimed
      ? [
          { state: 'queued', at: '2026-10-02T03:10:00Z', detail: '模拟任务进入队列' },
          {
            state: 'claimed',
            at: '2026-10-02T03:12:00Z',
            detail: '冻结模型和 runtime revision 17',
          },
          {
            state,
            at: demoTime,
            detail: incomplete ? '验证存在缺口；模拟 Draft PR 等待人工复核' : '模拟状态投影',
          },
        ]
      : [{ state, at: demoTime, detail: '等待领取；尚无 resolved 合同' }],
    state_events_complete: false,
    checks: {
      status: incomplete ? 'unavailable' : checked ? 'pass' : 'pending',
      summary: incomplete
        ? '模拟静态构建通过，浏览器检查缺失，需人工补充。'
        : checked
          ? '模拟检查摘要通过。'
          : '尚无完整检查结果。',
    },
    review: {
      verdict: reviewed ? 'pass' : 'pending',
      summary: reviewed ? '模拟独立审阅通过。' : '等待独立审阅。',
    },
    evidence: evidenceNames.map((name) => ({
      name,
      availability:
        name === 'task.raw.json' ||
        (claimed && !['checks-1.json', 'reviewer-result.json'].includes(name))
          ? 'available'
          : name === 'checks-1.json' && checked
            ? 'available'
            : name === 'reviewer-result.json' && reviewed
              ? 'withheld'
              : 'missing',
      note:
        name === 'reviewer-result.json' && reviewed
          ? '仅提供审阅摘要；原始结果未授权公开。'
          : '模拟证据投影。',
    })),
  };
}

export const taskFixtures: TaskDetail[] = definitions.map(makeTask);
export const hostFixtures: HostView[] = [
  {
    id: 'host-01',
    name: 'Linux · primary',
    state: 'busy',
    codex_version: 'demo-version',
    current_task_id: 'GH-42',
    current_model: { name: 'gpt-6.1-sol', effort: 'high' },
    last_heartbeat: demoTime,
  },
  {
    id: 'host-02',
    name: 'WSL · secondary',
    state: 'online',
    codex_version: 'demo-version',
    current_task_id: null,
    current_model: null,
    last_heartbeat: '2026-10-02T03:39:52Z',
  },
  {
    id: 'host-03',
    name: 'Laptop · reserve',
    state: 'offline',
    codex_version: null,
    current_task_id: null,
    current_model: null,
    last_heartbeat: '2026-10-01T13:18:00Z',
  },
];
export const modelFixtures: ModelOption[] = [
  { id: 'gpt-6.1-sol', label: 'GPT-6.1 Sol', note: '演示候选，实际可用性由 Host preflight 确认' },
  { id: 'gpt-6-sol', label: 'GPT-6 Sol', note: '演示候选' },
  { id: 'gpt-6-luna', label: 'GPT-6 Luna', note: '演示候选' },
  { id: 'unavailable-demo', label: '模拟不可用模型', note: '用于验证失败时保留默认值' },
];
