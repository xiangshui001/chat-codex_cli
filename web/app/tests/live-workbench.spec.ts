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
