import { useEffect, useState } from 'react';
import { Layers3, LockKeyhole } from 'lucide-react';
import { Button, Input, Pill } from '../primitives/Atoms';
import type { Workspace } from '../client/useWorkspace';
import type { Effort, ModelOption, ModelRole, RuntimeSettings } from '../api-client/types';
import { Empty, Heading, Panel } from './WorkspaceViews';

function ModelForm({
  role,
  confirmed,
  models,
  disabled,
  onApply,
}: {
  role: ModelRole;
  confirmed: RuntimeSettings[ModelRole];
  models: ModelOption[];
  disabled: boolean;
  onApply: (role: ModelRole, model: string, effort: Effort) => Promise<void>;
}) {
  const [model, setModel] = useState(confirmed.model);
  const [effort, setEffort] = useState(confirmed.effort);
  useEffect(() => {
    setModel(confirmed.model);
    setEffort(confirmed.effort);
  }, [confirmed.model, confirmed.effort]);
  const dirty = model !== confirmed.model || effort !== confirmed.effort;
  const label = role === 'executor' ? 'Executor' : 'Reviewer';
  return (
    <Panel
      title={label}
      extra={
        <Pill tone={role === 'executor' ? 'blue' : 'amber'}>
          {role === 'executor' ? '实现候选' : '独立审阅'}
        </Pill>
      }
    >
      <form
        className="model-form"
        onSubmit={(event) => {
          event.preventDefault();
          void onApply(role, model.trim(), effort);
        }}
      >
        <label htmlFor={`${role}-model`}>模型 ID</label>
        <Input
          id={`${role}-model`}
          value={model}
          onChange={(event) => setModel(event.target.value)}
          list="model-options"
          required
          disabled={disabled}
          autoComplete="off"
        />
        <label htmlFor={`${role}-effort`}>推理强度</label>
        <select
          id={`${role}-effort`}
          value={effort}
          onChange={(event) => setEffort(event.target.value as Effort)}
          disabled={disabled}
        >
          {(['low', 'medium', 'high', 'xhigh'] as const).map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
        <p className="field-help">
          {models.find((item) => item.id === model)?.note ??
            '输入实际 Host 支持的模型 ID；最终以 preflight 为准。'}
        </p>
        <div className="row between model-apply">
          <span className="small muted">{dirty ? '未应用的更改' : '与已确认值一致'}</span>
          <Button variant="primary" type="submit" disabled={disabled || !model.trim() || !dirty}>
            应用 {label}
          </Button>
        </div>
      </form>
      <div className="confirmed-model">
        <span>已确认默认值</span>
        <strong className="mono" data-testid={`${role}-confirmed-model`}>
          {confirmed.model}
        </strong>
        <Pill>{confirmed.effort}</Pill>
      </div>
    </Panel>
  );
}
export function ModelsView({ workspace }: { workspace: Workspace }) {
  const data = workspace.data!;
  const runtime = data.runtime;
  return (
    <>
      <Heading eyebrow="MODELS / RUNTIME DEFAULTS" title="模型与推理配置">
        分别应用 Executor 与 Reviewer。服务端确认 applied 后，默认值才会更新。
      </Heading>
      {runtime ? (
        <>
          <div className="runtime-strip">
            <div className="row">
              <Layers3 size={15} />
              <span>
                Runtime revision{' '}
                <strong className="mono" data-testid="runtime-revision">
                  {runtime.settings.revision}
                </strong>
              </span>
            </div>
            <Pill tone={runtime.settings.paused ? 'amber' : 'green'}>
              {runtime.settings.paused ? '新任务领取已暂停' : '新任务可领取'}
            </Pill>
          </div>
          {!workspace.canControl && (
            <div className="alert amber">
              <LockKeyhole size={17} />
              <span>当前会话只读，或数据尚未确认；不能修改模型与队列。</span>
            </div>
          )}
          <div className="two-col model-grid">
            {(['executor', 'reviewer'] as const).map((role) => (
              <ModelForm
                key={role}
                role={role}
                confirmed={runtime.settings[role]}
                models={data.models}
                disabled={!workspace.canControl || workspace.controlLocked}
                onApply={workspace.setDefaultModel}
              />
            ))}
          </div>
          <datalist id="model-options">
            {data.models.map((model) => (
              <option key={model.id} value={model.id}>
                {model.label}
              </option>
            ))}
          </datalist>
          <div className="alert">
            <LockKeyhole size={17} />
            <span>
              默认值只影响未来领取的 runtime-default 项。已领取任务与显式指定模型保持原快照。
            </span>
          </div>
          <Panel title="队列控制">
            <div className="panel-pad row between queue-panel">
              <div>
                <h3>{runtime.settings.paused ? '新任务领取已暂停' : '队列正在等待新任务'}</h3>
                <p className="small secondary">暂停只阻止下一次领取，当前任务继续执行。</p>
              </div>
              <Button
                variant="outline"
                disabled={!workspace.canControl || workspace.controlLocked}
                onClick={() => void workspace.toggleQueue()}
              >
                {runtime.settings.paused ? '恢复领取' : '暂停新任务'}
              </Button>
            </div>
          </Panel>
        </>
      ) : (
        <Empty title="没有 Runtime 读取能力" />
      )}
    </>
  );
}
