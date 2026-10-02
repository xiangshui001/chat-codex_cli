import { ClientError } from './client';
import type { ChatCodexClient } from './client';
import {
  demoRepository,
  demoTime,
  hostFixtures,
  initialSettings,
  modelFixtures,
  taskFixtures,
} from './fixtures';
import { evidenceNames } from './types';
import type {
  Capability,
  ControlIntent,
  ControlReceipt,
  ControlRequest,
  EvidenceName,
  EvidenceView,
  RequestFor,
  Role,
  RuntimeSettings,
  TaskDetail,
  TaskView,
} from './types';

export type MockOutcome = 'applied' | 'model_unavailable' | 'rejected' | 'unknown';
export interface MockDemo {
  setRole(role: Role): void;
  setNextOutcome(outcome: MockOutcome): void;
  failNextRead(): void;
}
interface PendingControl {
  request: ControlRequest;
  fingerprint: string;
  readyAt: number;
  mode: MockOutcome;
  unknownReported: boolean;
  confirmedReceipt?: ControlReceipt;
  receipt: ControlReceipt;
}
const readCapabilities: Capability[] = [
  'runtime:read',
  'tasks:read',
  'hosts:read',
  'evidence:read',
];
const capabilitiesByRole: Record<Role, Capability[]> = {
  owner: [...readCapabilities, 'control:write', 'members:read'],
  operator: [...readCapabilities, 'control:write', 'members:read'],
  reviewer: readCapabilities,
  viewer: readCapabilities,
};

/** A self-contained transport simulator. No GitHub calls, claim engine or file writes. */
export function createMockClient(
  options: { latency?: number; controlDelay?: number; now?: () => number } = {},
): {
  client: ChatCodexClient;
  demo: MockDemo;
} {
  const latency = options.latency ?? 120;
  const controlDelay = options.controlDelay ?? 1200;
  const now = options.now ?? Date.now;
  let role: Role = 'owner';
  let settings = structuredClone(initialSettings);
  let nextOutcome: MockOutcome = 'applied';
  let failRead = false;
  let lastReadyAt = 0;
  const requests = new Map<string, PendingControl>();
  const tasks = structuredClone(taskFixtures);
  const wait = () => new Promise<void>((resolve) => setTimeout(resolve, latency));
  const allowed = (capability: Capability) => {
    if (!capabilitiesByRole[role].includes(capability))
      throw new ClientError('当前演示会话没有此能力。', 'forbidden');
  };
  async function read<T>(capability: Capability, value: () => T): Promise<T> {
    await wait();
    allowed(capability);
    if (failRead) {
      failRead = false;
      throw new ClientError('模拟读取失败。请重试读取。', 'unavailable');
    }
    return structuredClone(value());
  }
  function task(id: string): TaskDetail {
    const found = tasks.find((item) => item.task_id === id);
    if (!found) throw new ClientError(`找不到任务 ${id}。`, 'not_found');
    return found;
  }
  function evidence(id: string, name: EvidenceName): EvidenceView {
    if (!evidenceNames.includes(name)) throw new ClientError('文件不在证据白名单中。', 'not_found');
    const detail = task(id);
    const summary = detail.evidence.find((item) => item.name === name)!;
    const sources: Record<EvidenceName, () => unknown> = {
      'task.raw.json': () => detail.raw,
      'task.resolved.json': () => detail.resolved,
      'runtime-settings.snapshot.json': () => detail.runtime_snapshot,
      'events.jsonl': () => ({
        at: detail.started_at,
        event: 'claimed',
        detail: { runtime_revision: detail.claimed_runtime_revision },
      }),
      'checks-1.json': () => detail.checks,
      'reviewer-result.json': () => null,
    };
    return {
      ...summary,
      content_type: name === 'events.jsonl' ? 'application/x-ndjson' : 'application/json',
      text:
        summary.availability === 'available'
          ? JSON.stringify(sources[name](), null, name === 'events.jsonl' ? undefined : 2)
          : null,
      redacted: true,
      note:
        summary.availability === 'missing'
          ? '尚无此证据。未领取任务没有 resolved 或 runtime snapshot。'
          : name === 'events.jsonl'
            ? '模拟审计事件；与状态轨迹是不同的数据。'
            : summary.note,
    };
  }
  const handlers = {
    'set-default-model': (
      intent: Extract<ControlIntent, { action: 'set-default-model' }>,
      draft: RuntimeSettings,
    ) => {
      for (const target of intent.role === 'both'
        ? (['executor', 'reviewer'] as const)
        : [intent.role]) {
        draft[target] = { model: intent.model, effort: intent.effort };
      }
      draft.revision++;
      return '模拟默认模型已生效；已领取任务保持原快照。';
    },
    pause: (_intent: Extract<ControlIntent, { action: 'pause' }>, draft: RuntimeSettings) => {
      draft.paused = true;
      draft.revision++;
      return '模拟队列已暂停新任务领取；当前任务继续执行。';
    },
    resume: (_intent: Extract<ControlIntent, { action: 'resume' }>, draft: RuntimeSettings) => {
      draft.paused = false;
      draft.revision++;
      return '模拟队列已恢复新任务领取。';
    },
    status: (_intent: Extract<ControlIntent, { action: 'status' }>, _draft: RuntimeSettings) =>
      '模拟状态已确认。',
  };
  function apply(entry: PendingControl) {
    const intent = entry.request.intent;
    const draft = structuredClone(settings);
    // This generic bridge pairs the discriminated action with its typed handler.
    const handle = handlers[intent.action] as (
      value: ControlIntent,
      state: RuntimeSettings,
    ) => string;
    const message = handle(intent, draft);
    settings = draft;
    entry.receipt = {
      ...entry.receipt,
      outcome: 'applied',
      settings: structuredClone(settings),
      message,
    };
  }
  function settle(entry: PendingControl) {
    if (
      !['pending', 'applying', 'unknown'].includes(entry.receipt.outcome) ||
      now() < entry.readyAt
    )
      return;
    if (entry.mode === 'unknown' && !entry.unknownReported) {
      entry.unknownReported = true;
      apply(entry);
      entry.confirmedReceipt = structuredClone(entry.receipt);
      entry.receipt = {
        ...entry.receipt,
        outcome: 'unknown',
        settings: null,
        message: '模拟回执暂时无法确认。请查询同一 request_id，不要重新提交。',
      };
      return;
    }
    if (entry.confirmedReceipt) {
      entry.receipt = entry.confirmedReceipt;
      return;
    }
    if (entry.mode === 'model_unavailable' || entry.mode === 'rejected') {
      entry.receipt = {
        ...entry.receipt,
        outcome: entry.mode,
        settings: structuredClone(settings),
        message:
          entry.mode === 'model_unavailable'
            ? '模拟 preflight 失败；默认值和 revision 保持不变。'
            : '模拟控制请求被拒绝；默认值保持不变。',
      };
      return;
    }
    apply(entry);
  }
  async function submit(request: ControlRequest): Promise<ControlReceipt> {
    await wait();
    allowed('control:write');
    if (request.repository !== demoRepository)
      throw new ClientError('请求仓库不匹配。', 'forbidden');
    const fingerprint = JSON.stringify([request.repository, request.intent]);
    const prior = requests.get(request.request_id);
    if (prior) {
      if (prior.fingerprint !== fingerprint)
        throw new ClientError('同一 request_id 不能用于不同命令。', 'conflict');
      return structuredClone(prior.receipt);
    }
    const mode =
      request.intent.action === 'set-default-model' && request.intent.model === 'unavailable-demo'
        ? 'model_unavailable'
        : nextOutcome;
    nextOutcome = 'applied';
    const receipt: ControlReceipt = {
      request_id: request.request_id,
      control_id: null,
      issue_url: null,
      outcome: 'pending',
      settings: null,
      message: '模拟请求已提交，等待控制回执。',
    };
    lastReadyAt = Math.max(now(), lastReadyAt) + controlDelay;
    requests.set(request.request_id, {
      request: structuredClone(request),
      fingerprint,
      readyAt: lastReadyAt,
      mode,
      unknownReported: false,
      receipt,
    });
    return structuredClone(receipt);
  }
  const client: ChatCodexClient = {
    getSession: async () => {
      await wait();
      return {
        repository: demoRepository,
        role,
        capabilities: [...capabilitiesByRole[role]],
        data_origin: 'mock',
      };
    },
    getRuntimeStatus: () =>
      read('runtime:read', () => ({
        settings,
        controller_state: 'online' as const,
        current_task_id: 'GH-42',
        current_host_id: 'host-01',
        observed_at: demoTime,
        data_origin: 'mock' as const,
      })),
    listTasks: () =>
      read('tasks:read', () =>
        tasks.map(
          ({
            raw: _raw,
            resolved: _resolved,
            runtime_snapshot: _snapshot,
            state_events: _events,
            state_events_complete: _complete,
            checks: _checks,
            review: _review,
            evidence: _evidence,
            ...summary
          }) => summary satisfies TaskView,
        ),
      ),
    getTask: (id) => read('tasks:read', () => task(id)),
    listHosts: () => read('hosts:read', () => hostFixtures),
    getModelCatalog: () => read('runtime:read', () => modelFixtures),
    getEvidence: (id, name) => read('evidence:read', () => evidence(id, name)),
    setDefaultModel: (request: RequestFor<'set-default-model'>) => submit(request),
    pauseQueue: (request: RequestFor<'pause'>) => submit(request),
    resumeQueue: (request: RequestFor<'resume'>) => submit(request),
    requestStatus: (request: RequestFor<'status'>) => submit(request),
    getControlReceipt: (id) =>
      read('runtime:read', () => {
        const entry = requests.get(id);
        if (!entry) throw new ClientError('没有这个控制请求的回执。', 'not_found');
        // Pending commands are considered in submission order, simulating one writer.
        for (const item of requests.values()) {
          settle(item);
          if (item === entry) break;
        }
        return entry.receipt;
      }),
  };
  return {
    client,
    demo: {
      setRole(value) {
        role = value;
      },
      setNextOutcome(value) {
        nextOutcome = value;
      },
      failNextRead() {
        failRead = true;
      },
    },
  };
}
