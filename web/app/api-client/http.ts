import { ClientError, type ChatCodexClient } from './client';
import type {
  ControlReceipt,
  ControlRequest,
  EvidenceName,
  EvidenceView,
  HostView,
  ModelOption,
  RequestFor,
  RuntimeStatus,
  Session,
  TaskDetail,
  TaskView,
} from './types';

/** Real HTTP transport; it never imports fixtures or falls back to MockClient. */
export class HttpClient implements ChatCodexClient {
  constructor(
    private readonly base = '/api/v2',
    private readonly fetcher: typeof fetch = globalThis.fetch.bind(globalThis),
  ) {}

  private async request<T>(path: string, body?: ControlRequest): Promise<T> {
    let response: Response;
    try {
      response = await this.fetcher(`${this.base}${path}`, {
        method: body ? 'POST' : 'GET',
        headers: {
          'X-Chat-Codex-Local': '1',
          ...(body ? { 'Content-Type': 'application/json' } : {}),
        },
        credentials: 'same-origin',
        cache: 'no-store',
        body: body ? JSON.stringify(body) : undefined,
        signal: AbortSignal.timeout(10_000),
      });
    } catch {
      throw new ClientError('Harness 连接失败，请查询或重连。', 'unavailable');
    }
    let value: unknown;
    try {
      value = await response.json();
    } catch {
      throw new ClientError('Harness 返回无效 JSON。', 'unavailable');
    }
    if (!response.ok) {
      const code =
        response.status === 403
          ? 'forbidden'
          : response.status === 404
            ? 'not_found'
            : response.status === 400 || response.status === 409
              ? 'conflict'
              : 'unavailable';
      throw new ClientError(`Harness 请求失败 (${response.status})。`, code);
    }
    return value as T;
  }

  getSession = () => this.request<Session>('/session');
  getRuntimeStatus = () => this.request<RuntimeStatus>('/runtime');
  listTasks = () => this.request<TaskView[]>('/tasks');
  getTask = (id: string) => this.request<TaskDetail>(`/tasks/${encodeURIComponent(id)}`);
  listHosts = () => this.request<HostView[]>('/hosts');
  getModelCatalog = () => this.request<ModelOption[]>('/models');
  getEvidence = (id: string, name: EvidenceName) =>
    this.request<EvidenceView>(
      `/tasks/${encodeURIComponent(id)}/evidence/${encodeURIComponent(name)}`,
    );
  private control = (request: ControlRequest) => this.request<ControlReceipt>('/controls', request);
  setDefaultModel = (request: RequestFor<'set-default-model'>) => this.control(request);
  pauseQueue = (request: RequestFor<'pause'>) => this.control(request);
  resumeQueue = (request: RequestFor<'resume'>) => this.control(request);
  requestStatus = (request: RequestFor<'status'>) => this.control(request);
  getControlReceipt = (id: string) =>
    this.request<ControlReceipt>(`/controls/${encodeURIComponent(id)}`);
}
