import { useCallback, useEffect, useRef, useState } from 'react';
import { ClientError } from '../api-client/client';
import type { ChatCodexClient } from '../api-client/client';
import type {
  Capability,
  ControlIntent,
  ControlReceipt,
  ControlRequest,
  Effort,
  EvidenceName,
  EvidenceView,
  HostView,
  ModelOption,
  ModelRole,
  RequestFor,
  RuntimeStatus,
  Session,
  TaskDetail,
  TaskView,
} from '../api-client/types';

export type WorkspaceRoute =
  | { view: 'dashboard' | 'tasks' | 'models' | 'hosts' | 'reviews' | 'members' | 'not-found' }
  | { view: 'task'; taskId: string }
  | { view: 'evidence'; taskId?: string; name: EvidenceName };
export interface WorkspaceData {
  session: Session;
  runtime: RuntimeStatus | null;
  tasks: TaskView[];
  hosts: HostView[];
  models: ModelOption[];
}
interface Query<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}
interface ControlState {
  request: ControlRequest;
  receipt: ControlReceipt | null;
  busy: boolean;
  error: string | null;
}
const emptyQuery = <T>(): Query<T> => ({ data: null, loading: false, error: null });
const messageOf = (error: unknown) =>
  error instanceof Error ? error.message : '读取失败，请重试。';
const waiting = (receipt: ControlReceipt) => ['pending', 'applying'].includes(receipt.outcome);
const unresolved = (receipt: ControlReceipt | null) =>
  receipt == null || waiting(receipt) || receipt.outcome === 'unknown';

/** One application query/control entry. Pages never import a transport or fixture. */
export function useWorkspace(client: ChatCodexClient, route: WorkspaceRoute) {
  const [workspace, setWorkspace] = useState<Query<WorkspaceData>>({
    ...emptyQuery(),
    loading: true,
  });
  const [task, setTask] = useState<Query<TaskDetail>>(emptyQuery);
  const [evidence, setEvidence] = useState<Query<EvidenceView>>(emptyQuery);
  const [control, setControl] = useState<ControlState | null>(null);
  const [epoch, setEpoch] = useState(0);
  const refreshSequence = useRef(0);
  const activeRequest = useRef<string | null>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      refreshSequence.current++;
    };
  }, []);

  const refresh = useCallback(async () => {
    const sequence = ++refreshSequence.current;
    setWorkspace((previous) => ({ ...previous, loading: true, error: null }));
    try {
      const session = await client.getSession();
      if (!alive.current || sequence !== refreshSequence.current) return;
      if (session.pending_control && !activeRequest.current) {
        // Recover server-owned command identity after reload/reconnect, never resubmit.
        const request = session.pending_control;
        activeRequest.current = request.request_id;
        let receipt: ControlReceipt;
        try {
          receipt = await client.getControlReceipt(request.request_id);
          if (waiting(receipt)) receipt = { ...receipt, outcome: 'unknown' };
        } catch {
          receipt = {
            request_id: request.request_id,
            control_id: null,
            issue_url: null,
            settings: null,
            outcome: 'unknown',
            message: '连接恢复后仍需查询原控制请求。',
          };
        }
        if (!alive.current || sequence !== refreshSequence.current) return;
        activeRequest.current = unresolved(receipt) ? request.request_id : null;
        setControl({ request, receipt, busy: false, error: null });
      }
      const has = (capability: Capability) => session.capabilities.includes(capability);
      const [runtime, tasks, hosts, models] = await Promise.all([
        has('runtime:read') ? client.getRuntimeStatus() : Promise.resolve(null),
        has('tasks:read') ? client.listTasks() : Promise.resolve([]),
        has('hosts:read') ? client.listHosts() : Promise.resolve([]),
        has('runtime:read') ? client.getModelCatalog() : Promise.resolve([]),
      ]);
      if (!alive.current || sequence !== refreshSequence.current) return;
      setWorkspace({
        data: { session, runtime, tasks, hosts, models },
        loading: false,
        error: null,
      });
      setEpoch((value) => value + 1);
    } catch (error) {
      if (!alive.current || sequence !== refreshSequence.current) return;
      setWorkspace((previous) => ({
        data: error instanceof ClientError && error.code === 'forbidden' ? null : previous.data,
        loading: false,
        error: messageOf(error),
      }));
    }
  }, [client]);
  useEffect(() => {
    void refresh();
  }, [refresh]);

  const selectedTaskId =
    route.view === 'task'
      ? route.taskId
      : route.view === 'evidence'
        ? (route.taskId ?? workspace.data?.tasks[0]?.task_id)
        : undefined;
  const evidenceName = route.view === 'evidence' ? route.name : undefined;
  const hasTaskRead = workspace.data?.session.capabilities.includes('tasks:read') ?? false;
  const hasEvidenceRead = workspace.data?.session.capabilities.includes('evidence:read') ?? false;
  useEffect(() => {
    let current = true;
    if (!selectedTaskId || !hasTaskRead) {
      setTask(emptyQuery());
      return;
    }
    setTask({ data: null, loading: true, error: null });
    client.getTask(selectedTaskId).then(
      (data) => {
        if (current) setTask({ data, loading: false, error: null });
      },
      (error) => {
        if (current) setTask({ data: null, loading: false, error: messageOf(error) });
      },
    );
    return () => {
      current = false;
    };
  }, [client, selectedTaskId, hasTaskRead, epoch]);
  useEffect(() => {
    let current = true;
    if (!selectedTaskId || !evidenceName || !hasEvidenceRead) {
      setEvidence(emptyQuery());
      return;
    }
    setEvidence({ data: null, loading: true, error: null });
    client.getEvidence(selectedTaskId, evidenceName).then(
      (data) => {
        if (current) setEvidence({ data, loading: false, error: null });
      },
      (error) => {
        if (current) setEvidence({ data: null, loading: false, error: messageOf(error) });
      },
    );
    return () => {
      current = false;
    };
  }, [client, selectedTaskId, evidenceName, hasEvidenceRead, epoch]);

  const revokeControl = () =>
    setWorkspace((previous) =>
      previous.data
        ? {
            ...previous,
            data: {
              ...previous.data,
              session: {
                ...previous.data.session,
                capabilities: previous.data.session.capabilities.filter(
                  (item) => item !== 'control:write',
                ),
              },
            },
          }
        : previous,
    );

  async function track(request: ControlRequest, first: ControlReceipt) {
    let receipt = first;
    const deadline = Date.now() + 12_000;
    try {
      while (waiting(receipt) && Date.now() < deadline && alive.current) {
        await new Promise((resolve) => setTimeout(resolve, 400));
        if (!alive.current) return;
        receipt = await client.getControlReceipt(request.request_id);
        if (alive.current) setControl({ request, receipt, busy: waiting(receipt), error: null });
      }
      if (!alive.current) return;
      if (waiting(receipt))
        receipt = {
          ...receipt,
          outcome: 'unknown',
          message: '等待超时，结果待确认。请查询同一 request_id。',
        };
      activeRequest.current = unresolved(receipt) ? request.request_id : null;
      setControl({ request, receipt, busy: false, error: null });
      if (!unresolved(receipt)) await refresh();
    } catch (error) {
      if (!alive.current) return;
      if (error instanceof ClientError && error.code === 'forbidden') revokeControl();
      setControl({
        request,
        receipt: { ...receipt, outcome: 'unknown', message: '回执查询失败，控制结果待确认。' },
        busy: false,
        error: messageOf(error),
      });
    }
  }

  async function submit(intent: ControlIntent) {
    const data = workspace.data;
    if (
      activeRequest.current ||
      workspace.loading ||
      workspace.error ||
      !data?.session.capabilities.includes('control:write')
    )
      return;
    const request: ControlRequest = {
      request_id: crypto.randomUUID(),
      repository: data.session.repository,
      intent,
    };
    activeRequest.current = request.request_id;
    setControl({ request, receipt: null, busy: true, error: null });
    const methods = {
      'set-default-model': (value: RequestFor<'set-default-model'>) =>
        client.setDefaultModel(value),
      pause: (value: RequestFor<'pause'>) => client.pauseQueue(value),
      resume: (value: RequestFor<'resume'>) => client.resumeQueue(value),
      status: (value: RequestFor<'status'>) => client.requestStatus(value),
    };
    try {
      const method = methods[intent.action] as (value: ControlRequest) => Promise<ControlReceipt>;
      const receipt = await method(request);
      if (!alive.current) return;
      setControl({ request, receipt, busy: waiting(receipt), error: null });
      await track(request, receipt);
    } catch (error) {
      if (!alive.current) return;
      const rejected =
        error instanceof ClientError && ['forbidden', 'conflict'].includes(error.code);
      if (error instanceof ClientError && error.code === 'forbidden') revokeControl();
      if (rejected) activeRequest.current = null;
      setControl({
        request,
        busy: false,
        error: messageOf(error),
        receipt: {
          request_id: request.request_id,
          control_id: null,
          issue_url: null,
          settings: null,
          outcome: rejected ? 'rejected' : 'unknown',
          message: rejected ? '控制请求被拒绝。' : '提交结果待确认。请查询同一 request_id。',
        },
      });
    }
  }
  async function recheckControl() {
    if (!control || control.busy) return;
    const { request } = control;
    setControl((previous) => (previous ? { ...previous, busy: true, error: null } : previous));
    try {
      const receipt = await client.getControlReceipt(request.request_id);
      if (alive.current) await track(request, receipt);
    } catch (error) {
      if (alive.current)
        setControl((previous) =>
          previous ? { ...previous, busy: false, error: messageOf(error) } : previous,
        );
    }
  }

  return {
    ...workspace,
    task,
    evidence,
    control,
    selectedTaskId,
    refresh,
    recheckControl,
    canControl:
      !workspace.loading &&
      !workspace.error &&
      (workspace.data?.session.capabilities.includes('control:write') ?? false),
    controlLocked: control != null && (control.busy || unresolved(control.receipt)),
    setDefaultModel: (role: ModelRole, model: string, effort: Effort) =>
      submit({ action: 'set-default-model', role, model, effort }),
    toggleQueue: () =>
      submit({ action: workspace.data?.runtime?.settings.paused ? 'resume' : 'pause' }),
    requestStatus: () => submit({ action: 'status' }),
  };
}
export type Workspace = ReturnType<typeof useWorkspace>;
