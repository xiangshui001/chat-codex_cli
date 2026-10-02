import { describe, expect, it } from 'vitest';
import { createMockClient } from './mock';
import { demoRepository } from './fixtures';
import type { ControlRequest, EvidenceName, RequestFor } from './types';

function modelRequest(id = 'request-1', model = 'gpt-6-luna'): RequestFor<'set-default-model'> {
  return {
    request_id: id,
    repository: demoRepository,
    intent: { action: 'set-default-model', role: 'executor', model, effort: 'medium' },
  };
}
const instant = () => createMockClient({ latency: 0, controlDelay: 0 });

describe('MockClient API semantics', () => {
  it('returns pending without changing confirmed defaults before a receipt', async () => {
    let now = 0;
    const { client } = createMockClient({ latency: 0, controlDelay: 1000, now: () => now });
    const initial = await client.getRuntimeStatus();
    expect(await client.setDefaultModel(modelRequest())).toMatchObject({
      outcome: 'pending',
      settings: null,
      control_id: null,
    });
    expect(await client.getRuntimeStatus()).toEqual(initial);
    expect((await client.getControlReceipt('request-1')).outcome).toBe('pending');
    now = 1000;
    expect(await client.getControlReceipt('request-1')).toMatchObject({
      outcome: 'applied',
      settings: { revision: 18, executor: { model: 'gpt-6-luna' } },
    });
  });
  it('preserves defaults and revision when preflight fails', async () => {
    const { client } = instant();
    const initial = await client.getRuntimeStatus();
    await client.setDefaultModel(modelRequest('failed', 'unavailable-demo'));
    expect((await client.getControlReceipt('failed')).outcome).toBe('model_unavailable');
    expect(await client.getRuntimeStatus()).toEqual(initial);
  });
  it('does not change claimed snapshots, explicit choices or unclaimed contracts', async () => {
    const { client } = instant();
    const before = await Promise.all(['GH-42', 'GH-44', 'GH-43'].map((id) => client.getTask(id)));
    await client.setDefaultModel(modelRequest());
    await client.getControlReceipt('request-1');
    const after = await Promise.all(['GH-42', 'GH-44', 'GH-43'].map((id) => client.getTask(id)));
    expect(after).toEqual(before);
    expect(after[0].resolved?.model_policy.executor.primary.name).toBe('gpt-6.1-sol');
    expect(after[1].resolved?.model_policy.executor.primary.name).toBe('gpt-6-sol');
    expect(after[2].resolved).toBeNull();
  });
  it('applies an unknown command only once and confirms the same request later', async () => {
    const { client, demo } = instant();
    demo.setNextOutcome('unknown');
    await client.setDefaultModel(modelRequest('uncertain'));
    expect(await client.getControlReceipt('uncertain')).toMatchObject({
      request_id: 'uncertain',
      outcome: 'unknown',
      settings: null,
    });
    expect(await client.getControlReceipt('uncertain')).toMatchObject({
      request_id: 'uncertain',
      outcome: 'applied',
      settings: { revision: 18 },
    });
    expect((await client.getRuntimeStatus()).settings.revision).toBe(18);
  });
  it('returns the original receipt on replay and rejects reuse for a different intent', async () => {
    const { client } = instant();
    const request = modelRequest();
    await client.setDefaultModel(request);
    const first = await client.getControlReceipt(request.request_id);
    expect(await client.setDefaultModel(request)).toEqual(first);
    await expect(
      client.setDefaultModel(modelRequest('request-1', 'other-model')),
    ).rejects.toMatchObject({ code: 'conflict' });
    expect((await client.getRuntimeStatus()).settings.revision).toBe(18);
  });
  it('enforces read-only capabilities inside the mock API, including direct writes', async () => {
    const { client, demo } = instant();
    for (const role of ['reviewer', 'viewer'] as const) {
      demo.setRole(role);
      expect((await client.getSession()).capabilities).not.toContain('control:write');
      await expect(client.setDefaultModel(modelRequest())).rejects.toMatchObject({
        code: 'forbidden',
      });
      await expect(
        client.pauseQueue({
          request_id: 'pause',
          repository: demoRepository,
          intent: { action: 'pause' },
        }),
      ).rejects.toMatchObject({ code: 'forbidden' });
    }
    demo.setRole('operator');
    expect((await client.getSession()).capabilities).toContain('control:write');
  });
  it('keeps the current task running when the queue pauses and resumes', async () => {
    const { client } = instant();
    await client.pauseQueue({
      request_id: 'pause',
      repository: demoRepository,
      intent: { action: 'pause' },
    });
    await client.getControlReceipt('pause');
    expect((await client.getRuntimeStatus()).settings.paused).toBe(true);
    expect((await client.getTask('GH-42')).state).toBe('executing');
    await client.resumeQueue({
      request_id: 'resume',
      repository: demoRepository,
      intent: { action: 'resume' },
    });
    await client.getControlReceipt('resume');
    expect((await client.getRuntimeStatus()).settings.paused).toBe(false);
  });
  it('exposes flat snapshots, marks missing/withheld artifacts, and rejects unknown files', async () => {
    const { client } = instant();
    const raw = JSON.parse((await client.getEvidence('GH-42', 'task.raw.json')).text!);
    expect(raw).toMatchObject({ version: 2, task_id: 'GH-42' });
    expect(raw.task).toBeUndefined();
    expect(await client.getEvidence('GH-43', 'task.resolved.json')).toMatchObject({
      availability: 'missing',
      text: null,
    });
    expect(await client.getEvidence('GH-41', 'reviewer-result.json')).toMatchObject({
      availability: 'withheld',
      text: null,
    });
    expect((await client.getTask('GH-39')).checks.status).toBe('unavailable');
    await expect(client.getEvidence('GH-42', '../auth.json' as EvidenceName)).rejects.toMatchObject(
      { code: 'not_found' },
    );
    const event = JSON.parse((await client.getEvidence('GH-42', 'events.jsonl')).text!);
    expect(event.event).toBe('claimed');
    expect(event.state).toBeUndefined();
  });
  it('does not mutate runtime revision for status or rejected commands', async () => {
    const { client, demo } = instant();
    await client.requestStatus({
      request_id: 'status',
      repository: demoRepository,
      intent: { action: 'status' },
    });
    expect((await client.getControlReceipt('status')).outcome).toBe('applied');
    demo.setNextOutcome('rejected');
    await client.setDefaultModel(modelRequest());
    expect((await client.getControlReceipt('request-1')).outcome).toBe('rejected');
    expect((await client.getRuntimeStatus()).settings.revision).toBe(17);
  });
  it('keeps consumers from mutating the mock state via returned objects', async () => {
    const { client } = instant();
    const runtime = await client.getRuntimeStatus();
    runtime.settings.executor.model = 'mutated';
    const detail = await client.getTask('GH-42');
    detail.raw.title = 'mutated';
    expect((await client.getRuntimeStatus()).settings.executor.model).toBe('gpt-6.1-sol');
    expect((await client.getTask('GH-42')).raw.title).not.toBe('mutated');
  });
  it('reports read failures, missing IDs and mismatched repositories without fallback', async () => {
    const { client, demo } = instant();
    demo.failNextRead();
    await expect(client.getRuntimeStatus()).rejects.toMatchObject({ code: 'unavailable' });
    expect((await client.getRuntimeStatus()).data_origin).toBe('mock');
    await expect(client.getTask('GH-999')).rejects.toMatchObject({ code: 'not_found' });
    await expect(client.getControlReceipt('nonexistent')).rejects.toMatchObject({
      code: 'not_found',
    });
    const wrong = { ...modelRequest(), repository: 'someone/else' } as ControlRequest;
    await expect(
      client.setDefaultModel(wrong as RequestFor<'set-default-model'>),
    ).rejects.toMatchObject({ code: 'forbidden' });
  });
});
