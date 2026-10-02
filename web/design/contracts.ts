/** Design contract only. These HTTP endpoints are not implemented by v2 yet. */
export type Effort = 'low' | 'medium' | 'high' | 'xhigh';
export type Role = 'owner' | 'operator' | 'reviewer' | 'viewer';
export type ModelRole = 'executor' | 'reviewer';
export type RunState =
  | 'queued' | 'claimed' | 'preflight' | 'executing' | 'validating'
  | 'reviewing' | 'manual_review_required' | 'publish_ready' | 'pr_open'
  | 'accepted' | 'policy_blocked' | 'model_unavailable' | 'execution_failed'
  | 'validation_incomplete' | 'review_rejected' | 'publication_failed' | 'cancelled';

/** control.RuntimeSettings.to_dict(): preserve these names at the API boundary. */
export interface RuntimeSettings {
  paused: boolean;
  executor: { model: string; effort: Effort };
  reviewer: { model: string; effort: Effort };
  revision: number;
  last_control_id: string | null;
}

/** contract.ModelChoice and the flattened dataclass saved by freeze_claim(). */
export interface ModelChoice { name: string; effort: Effort }
export interface RoleModelPolicy { primary: ModelChoice; fallbacks: ModelChoice[] }
export interface FrozenTask {
  version: 2;
  repository: string;
  base_sha: string;
  task_id: string;
  task_type: 'audit-readonly' | 'code-change' | 'bugfix' | 'ui-prototype' | 'refactor' | 'data-check' | 'documentation';
  title: string;
  goal: string;
  context: string;
  read_scope: string[];
  write_scope: string[];
  checks: string[];
  acceptance: string[];
  model_policy: { executor: RoleModelPolicy; reviewer: RoleModelPolicy };
  budget: { max_rounds: number; max_minutes: number; review_rounds: number };
  network: 'deny' | 'allowlist' | 'allow';
  production: 'deny';
  publication: { mode: 'pr' | 'draft_pr' | 'none'; draft_on_incomplete_validation: boolean };
}

export interface TaskView {
  task_id: string;
  title: string;
  state: RunState; // Preserve the exact backend state; group labels are presentation only.
  requested_models: FrozenTask['model_policy'];
  resolved_models: FrozenTask['model_policy'] | null; // null before claim, never inferred from new defaults.
  claimed_runtime_revision: number | null;
  started_at: string | null;
  updated_at: string | null;
  pr: { number: number; url: string; draft: boolean; state: 'open' | 'closed' | 'merged' } | null;
}
export interface TaskDetail extends TaskView {
  raw: FrozenTask;
  resolved: FrozenTask | null;
  runtime_snapshot: RuntimeSettings | null;
  state_events: { state: RunState; at: string; detail: string }[];
  state_events_complete: boolean;
  checks: { status: 'pass' | 'fail' | 'unavailable' | 'pending'; summary: string };
  review: { verdict: 'pass' | 'reject' | 'pending'; summary: string };
}

/** The browser sends intent. The server owns the GH-N identity and authorization. */
export type ControlIntent =
  | { action: 'set-default-model'; role: ModelRole | 'both'; model: string; effort: Effort; reason?: string }
  | { action: 'pause'; reason?: string }
  | { action: 'resume'; reason?: string }
  | { action: 'status'; reason?: string };
export interface ControlRequest {
  request_id: string; // Opaque, stable for a retry; distinct from control.id.
  repository: string;
  intent: ControlIntent;
}
export type RequestFor<Action extends ControlIntent['action']> =
  ControlRequest & { intent: Extract<ControlIntent, { action: Action }> };
export interface GitHubControlEnvelope {
  version: 2;
  repository: string;
  control: ControlIntent & { id: `GH-${number}` };
}
export interface ControlReceipt {
  request_id: string;
  control_id: string | null;
  issue_url: string | null;
  outcome: 'pending' | 'applying' | 'applied' | 'model_unavailable' | 'rejected' | 'unknown';
  settings: RuntimeSettings | null; // Only authoritative, confirmed settings.
  message: string;
}
export interface RuntimeStatus {
  settings: RuntimeSettings;
  controller_state: 'online' | 'offline' | 'unknown';
  current_task_id: string | null;
  current_host_id: string | null;
  observed_at: string | null;
  data_origin: 'mock' | 'live';
}
export interface HostView {
  id: string;
  name: string;
  state: 'online' | 'offline' | 'busy' | 'unknown';
  codex_version: string | null;
  current_task_id: string | null;
  current_model: ModelChoice | null;
  last_heartbeat: string | null;
}
export type EvidenceName = 'task.raw.json' | 'task.resolved.json'
  | 'runtime-settings.snapshot.json' | 'events.jsonl'
  | 'checks-1.json' | 'reviewer-result.json';
export interface EvidenceView {
  name: EvidenceName;
  availability: 'available' | 'missing' | 'withheld';
  content_type: 'application/json' | 'application/x-ndjson';
  text: string | null;
  redacted: boolean;
  note: string;
}
export type Capability = 'runtime:read' | 'tasks:read' | 'hosts:read'
  | 'evidence:read' | 'control:write' | 'members:read';

/** One client injected into one app-level query entry. No page-specific services. */
export interface ChatCodexClient {
  getSession(): Promise<{ role: Role; capabilities: Capability[]; data_origin: 'mock' | 'live' }>;
  getRuntimeStatus(): Promise<RuntimeStatus>;
  listTasks(): Promise<TaskView[]>;
  getTask(taskId: string): Promise<TaskDetail>;
  listHosts(): Promise<HostView[]>;
  getEvidence(taskId: string, name: EvidenceName): Promise<EvidenceView>;
  setDefaultModel(request: RequestFor<'set-default-model'>): Promise<ControlReceipt>;
  pauseQueue(request: RequestFor<'pause'>): Promise<ControlReceipt>;
  resumeQueue(request: RequestFor<'resume'>): Promise<ControlReceipt>;
  requestStatus(request: RequestFor<'status'>): Promise<ControlReceipt>;
  getControlReceipt(requestId: string): Promise<ControlReceipt>;
}
