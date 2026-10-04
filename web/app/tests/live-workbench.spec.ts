import { test, expect } from '@playwright/test';

const id = '10000000-0000-4000-8000-000000000001';
const task = {
  request_id: id,
  repo: 'example/test',
  issue_number: 8,
  issue_url: 'https://github.com/example/test/issues/8',
  state: 'running',
  prompt: 'Create docs/check.txt',
  summary: '',
  error: '',
  created_at: '2026-10-04T10:00:00Z',
  started_at: '2026-10-04T10:00:01Z',
  finished_at: null,
  cli_version: 'test-cli',
  exit_code: null,
  receipt_comment_id: null,
  diff_nonempty: null,
};
const detail = {
  ...task,
  cwd: '/work/test',
  write_paths: ['docs/check.txt'],
  files: [],
  files_error: null,
  events: [
    { kind: 'claimed', at: task.created_at },
    { kind: 'process_started', at: task.started_at },
  ],
  stderr: '',
  stderr_truncated: false,
  progress: {
    items: [
      {
        id: 'item-1',
        kind: 'command_execution',
        status: 'in_progress',
        title: 'create document',
        text: '',
        exit_code: 1,
      },
    ],
    truncated: false,
    partial_lines: 0,
  },
};

const monitor = {
  phase: 'idle',
  last_poll_started_at: '2026-10-04T10:00:00Z',
  last_poll_finished_at: '2026-10-04T10:00:10Z',
  next_poll_at: '2026-10-04T10:01:10Z',
  repository_count: 3,
  checked_repositories: 3,
  error_count: 0,
  last_error: null,
  rejections_truncated: false,
  rejected: [
    {
      repo: 'example/test',
      issue_number: 9,
      issue_url: 'https://github.com/example/test/issues/9',
      reason: 'model_not_allowed',
      model: 'Example-Model',
      effort: 'max',
      suggested_model: 'example-model',
      allowed_efforts: ['none', 'low', 'medium', 'high'],
    },
  ],
};

test('unclaimed issues explain idle status and invalid model choices', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route('**/api/mvp1/overview', (route) =>
    route.fulfill({
      json: {
        source: 'local-mvp2',
        observed_at: task.created_at,
        host_id: 'desktop',
        owner: 'example',
        listener: 'running',
        counts: {},
        tasks: [],
        limit: 100,
        monitor,
      },
    }),
  );
  await page.goto('/?view=live');
  const status = page.getByRole('region', { name: '当前运行状态' });
  await expect(status).toContainText('没有任务在执行，有 Issue 未通过领取检查');
  await expect(status).toContainText('上次完成 GitHub 检查');
  await expect(status).toContainText('名称和大小写必须与本机配置一致');
  await expect(status).toContainText('登记的模型名：example-model');
  await expect(status).toContainText('登记的思考强度：none、low、medium、high');
  await expect(status.getByRole('link')).toHaveAttribute('href', monitor.rejected[0].issue_url);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
});

test('current task remains visible while historical detail is selected and updates model round', async ({
  page,
}) => {
  let round = 1;
  const oldId = '10000000-0000-4000-8000-000000000002';
  const historical = { ...task, request_id: oldId, issue_number: 7, state: 'failed' };
  await page.route('**/api/mvp1/**', (route) => {
    const current = {
      ...task,
      model: 'example-model',
      activity: {
        kind: 'api_model_request',
        at: task.started_at,
        label: `正在等待模型回复（第 ${round}/40 轮）`,
      },
    };
    return route.fulfill({
      json: route.request().url().endsWith('overview')
        ? {
            source: 'local-mvp2',
            observed_at: task.created_at,
            host_id: 'desktop',
            owner: 'example',
            listener: 'running',
            counts: { running: 1, failed: 1 },
            tasks: [current, historical],
            limit: 100,
            monitor: { ...monitor, phase: 'executing', rejected: [] },
          }
        : { ...detail, ...(route.request().url().endsWith(oldId) ? historical : current) },
    });
  });
  await page.goto('/?view=live#task/' + oldId);
  await expect(page.getByRole('heading', { name: 'Issue #7' })).toBeVisible();
  const status = page.getByRole('region', { name: '当前运行状态' });
  await expect(status).toContainText('Issue #8');
  await expect(status).toContainText('正在等待模型回复（第 1/40 轮）');
  round = 2;
  await expect(status).toContainText('正在等待模型回复（第 2/40 轮）', { timeout: 10000 });
  await status.getByRole('button', { name: '查看当前任务' }).click();
  await expect(page.getByRole('heading', { name: 'Issue #8' })).toBeVisible();
});

test('MVP-2 shows conversation, chosen model, hub receipt and target PR', async ({ page }) => {
  const session = '20000000-0000-4000-8000-000000000002';
  const current = {
    ...task,
    state: 'succeeded',
    summary: '已创建成果 PR',
    finished_at: task.started_at,
    issue_url: 'https://github.com/example/codex-cli/issues/8',
    session_id: session,
    mode: 'gpt-led',
    model: 'gpt-6.1-sol',
    effort: 'high',
    pr_url: 'https://github.com/example/test/pull/12',
    receipt_comment_id: 42,
  };
  await page.route('**/api/mvp1/**', async (route) => {
    expect(route.request().method()).toBe('GET');
    const value = route.request().url().endsWith('overview')
      ? {
          source: 'local-mvp2',
          observed_at: task.created_at,
          host_id: 'desktop',
          owner: 'example',
          listener: 'running',
          counts: { succeeded: 1 },
          tasks: [current],
          limit: 100,
        }
      : { ...detail, ...current };
    await route.fulfill({ json: value });
  });
  await page.goto('/');
  await expect(page.getByText(session, { exact: true })).toBeVisible();
  await expect(page.getByText('模式：gpt-led · 模型：gpt-6.1-sol · 思考强度：high')).toBeVisible();
  await expect(page.getByRole('link', { name: '审查成果 PR' })).toHaveAttribute(
    'href',
    current.pr_url,
  );
  await expect(page.getByRole('link', { name: '查看 GitHub 回执' })).toHaveAttribute(
    'href',
    current.issue_url + '#issuecomment-42',
  );
});

test('real-mode page refreshes execution and receipt without control writes', async ({ page }) => {
  let complete = false;
  const methods: string[] = [];
  await page.route('**/api/mvp1/**', async (route) => {
    methods.push(route.request().method());
    const current = complete
      ? {
          ...task,
          state: 'succeeded',
          summary: 'Task completed',
          finished_at: '2026-10-04T10:00:03Z',
          exit_code: 0,
          receipt_comment_id: 42,
        }
      : task;
    const value = route.request().url().endsWith('overview')
      ? {
          source: 'local-mvp1',
          observed_at: task.created_at,
          host_id: 'test-host',
          owner: 'example',
          listener: 'running',
          counts: { [current.state]: 1 },
          tasks: [current],
          limit: 100,
        }
      : { ...detail, ...current, files: complete ? ['docs/check.txt'] : [] };
    await route.fulfill({ json: value });
  });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Issue #8' })).toBeVisible();
  await expect(page.getByText('create document')).toBeVisible();
  await expect(page.locator('.live-command-failed')).toHaveText('exit 1');
  complete = true;
  await expect(page.getByText('Task completed')).toBeVisible({ timeout: 10000 });
  await expect(page.getByRole('link', { name: '查看 GitHub 回执' })).toHaveAttribute(
    'href',
    task.issue_url + '#issuecomment-42',
  );
  expect(methods.every((method) => method === 'GET')).toBe(true);
  await expect(page.getByText('Mock 演示场景', { exact: true })).toHaveCount(0);
});

test('disconnect keeps last record and displays stale warning', async ({ page }) => {
  let disconnected = false;
  await page.route('**/api/mvp1/**', async (route) => {
    if (disconnected) return route.fulfill({ status: 503, json: { error: 'offline' } });
    await route.fulfill({
      json: route.request().url().endsWith('overview')
        ? {
            source: 'local-mvp1',
            observed_at: task.created_at,
            host_id: 'test-host',
            listener: 'stopped',
            counts: { running: 1 },
            tasks: [task],
            limit: 100,
          }
        : detail,
    });
  });
  await page.goto('/?view=live');
  await expect(page.getByRole('heading', { name: 'Issue #8' })).toBeVisible();
  disconnected = true;
  await expect(page.getByRole('alert')).toContainText('数据可能已过期', { timeout: 10000 });
  await expect(page.getByRole('heading', { name: 'Issue #8' })).toBeVisible();
  await expect(page.getByText('监听已停止。', { exact: false })).toBeVisible();
});

test('mobile output is escaped and does not overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route('**/api/mvp1/**', async (route) => {
    await route.fulfill({
      json: route.request().url().endsWith('overview')
        ? {
            source: 'local-mvp1',
            observed_at: task.created_at,
            host_id: 'test-host',
            listener: 'running',
            counts: { running: 1 },
            tasks: [task],
            limit: 100,
          }
        : {
            ...detail,
            progress: {
              items: [
                {
                  id: 'one',
                  kind: 'agent_message',
                  status: 'completed',
                  title: 'Codex 回复',
                  text: '<script>window.injected=true</script>' + 'x'.repeat(300),
                },
              ],
              truncated: false,
              partial_lines: 0,
            },
          },
    });
  });
  await page.goto('/?view=live');
  await expect(page.getByRole('heading', { name: 'Issue #8' })).toBeVisible();
  await expect(page.locator('.live-output pre')).toContainText('<script>');
  expect(await page.evaluate(() => 'injected' in window)).toBe(false);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
});
