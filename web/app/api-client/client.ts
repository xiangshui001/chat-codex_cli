import type {
  ControlReceipt,
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

/** The only data/control boundary consumed by useWorkspace and the React UI. */
export interface ChatCodexClient {
  getSession(): Promise<Session>;
  getRuntimeStatus(): Promise<RuntimeStatus>;
  listTasks(): Promise<TaskView[]>;
  getTask(taskId: string): Promise<TaskDetail>;
  listHosts(): Promise<HostView[]>;
  getModelCatalog(): Promise<ModelOption[]>;
  getEvidence(taskId: string, name: EvidenceName): Promise<EvidenceView>;
  setDefaultModel(request: RequestFor<'set-default-model'>): Promise<ControlReceipt>;
  pauseQueue(request: RequestFor<'pause'>): Promise<ControlReceipt>;
  resumeQueue(request: RequestFor<'resume'>): Promise<ControlReceipt>;
  requestStatus(request: RequestFor<'status'>): Promise<ControlReceipt>;
  getControlReceipt(requestId: string): Promise<ControlReceipt>;
}

export class ClientError extends Error {
  constructor(
    message: string,
    readonly code: 'forbidden' | 'not_found' | 'conflict' | 'unavailable',
  ) {
    super(message);
    this.name = 'ClientError';
  }
}
