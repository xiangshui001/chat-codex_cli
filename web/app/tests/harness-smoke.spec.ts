import { expect, test } from '@playwright/test';
import { spawn, type ChildProcess } from 'node:child_process';
import { once } from 'node:events';
import { copyFile, mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createInterface } from 'node:readline';
import type { ControlRequest, RuntimeSettings } from '../api-client/types';

test('real React → HTTP → core, receipt recovery/reconnect and visual independence', async ({
  page,
}) => {
  const stateDir = await mkdtemp(join(tmpdir(), 'chat-codex-harness-smoke-'));
  const repositoryRoot = resolve('../..');
  let harnessProcess: ChildProcess | undefined;
  let port = 0;
  let origin = '';
  const posts: ControlRequest[] = [];
  const requests: { method: string; url: string }[] = [];
  const errors: string[] = [];
  const evidenceDir = globalThis.process.env.HARNESS_SMOKE_EVIDENCE_DIR;

  async function start(fault = false) {
    const child = spawn(
      'python3',
      [
        '-m',
        'codex_github_local_v2.harness',
        '--mode',
        'local-smoke',
        '--state-dir',
        stateDir,
        '--dist',
        resolve('dist'),
        '--port',
        String(port),
        ...(fault ? ['--fail-first-receipt'] : []),
      ],
      {
        env: {
          ...globalThis.process.env,
          PYTHONPATH: join(repositoryRoot, 'codex-github-local-v2/src'),
        },
        stdio: ['ignore', 'pipe', 'pipe'],
      },
    );
    harnessProcess = child;
    child.stderr?.on('data', (data: Buffer) => errors.push(data.toString()));
    const lines = createInterface({ input: child.stdout! });
    const ready = await Promise.race([
      once(lines, 'line').then(([line]) => JSON.parse(String(line)) as { url: string }),
      once(child, 'exit').then(([code]) => {
        throw new Error(`Harness exited ${code}: ${errors.join('')}`);
      }),
    ]);
    lines.close();
    origin = new URL(ready.url).origin;
    port = Number(new URL(ready.url).port);
  }

  async function stop() {
    if (!harnessProcess || harnessProcess.exitCode !== null) return;
    const ended = once(harnessProcess, 'exit');
    harnessProcess.kill('SIGINT');
    await ended;
    harnessProcess = undefined;
  }

  async function settings(): Promise<RuntimeSettings> {
    return JSON.parse(
      await readFile(join(stateDir, 'runtime-settings.json'), 'utf8'),
    ) as RuntimeSettings;
  }

  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (request) => {
    if (!request.url().includes('/api/v2/')) return;
    requests.push({ method: request.method(), url: request.url() });
    if (request.method() === 'POST') posts.push(request.postDataJSON() as ControlRequest);
  });

  try {
    await start(true);
    await page.goto(`${origin}/?harness=local-smoke#/models`);
    await expect(page.getByText('本地确定性验证', { exact: true })).toBeVisible();
    await expect(page.getByTestId('runtime-revision')).toHaveText('0');
    await expect(page.locator('.demo-tools')).toHaveCount(0);

    await page.locator('.queue-panel').getByRole('button', { name: '暂停新任务' }).click();
    await expect(page.getByTestId('control-receipt')).toContainText('unknown');
    expect(posts).toHaveLength(1);
    const originalRequest = posts[0];
    const before = await readFile(join(stateDir, 'runtime-settings.json'), 'utf8');
    expect(await settings()).toMatchObject({ paused: true, revision: 1 });

    await stop();
    await page.getByRole('button', { name: '刷新工作区' }).click();
    await expect(page.getByRole('alert')).toContainText('Harness 连接失败，请查询或重连。');
    await expect(page.locator('.queue-panel button')).toBeDisabled();
    await start();
    await page.reload();
    await expect(page.getByTestId('control-receipt')).toContainText('applied');
    await expect(page.getByTestId('control-receipt')).toContainText(originalRequest.request_id);
    await expect(page.getByTestId('runtime-revision')).toHaveText('1');
    expect(posts).toHaveLength(1); // Recovery queried the same request; no second POST.
    expect(await readFile(join(stateDir, 'runtime-settings.json'), 'utf8')).toBe(before);

    await page.locator('.queue-panel').getByRole('button', { name: '恢复领取' }).click();
    await expect(page.getByTestId('runtime-revision')).toHaveText('2');
    expect(await settings()).toMatchObject({ paused: false, revision: 2 });
    await page.locator('#executor-model').fill('deterministic-test');
    await page.getByRole('button', { name: '应用 Executor' }).click();
    await expect(page.getByTestId('executor-confirmed-model')).toHaveText('deterministic-test');
    await expect(page.getByTestId('runtime-revision')).toHaveText('3');
    expect(await settings()).toMatchObject({
      executor: { model: 'deterministic-test' },
      revision: 3,
    });

    // The original visual stays independent of transport and disposes on entry.
    await page.goto(`${origin}/?harness=local-smoke#/login`);
    await expect(page.getByTestId('library-model')).toHaveAttribute('data-status', 'ready', {
      timeout: 30_000,
    });
    await page.getByRole('button', { name: '进入本地验证工作区' }).click();
    await expect(page.locator('.library-scene canvas')).toHaveCount(0);
    await page.getByRole('link', { name: '模型配置' }).click();
    await expect(page.getByTestId('runtime-revision')).toHaveText('3');
    expect(posts).toHaveLength(3);
    expect(errors).toEqual([]);

    if (evidenceDir) {
      await mkdir(evidenceDir, { recursive: true });
      await page.screenshot({ path: join(evidenceDir, 'harness-models.png'), fullPage: true });
      await writeFile(
        join(evidenceDir, 'browser-flow.json'),
        JSON.stringify(
          {
            transport: 'real HTTP',
            core: 'real ControlProcessor/RuntimeControlService',
            model_backend: 'deterministic probe; no real model',
            github: 'durable local source substitute',
            original_request: originalRequest,
            posts,
            requests,
            errors,
            final_settings: await settings(),
            reconnect: true,
            receipt_recovered_without_reapplication: true,
          },
          null,
          2,
        ),
      );
    }
  } finally {
    await stop();
    if (evidenceDir) {
      await mkdir(evidenceDir, { recursive: true });
      for (const name of [
        'runtime-settings.json',
        'control-ledger.json',
        'local-controls.json',
        'harness-events.jsonl',
      ]) {
        try {
          await copyFile(join(stateDir, name), join(evidenceDir, name));
        } catch {
          /* Preserve whatever was produced if the test failed. */
        }
      }
    }
  }
});
