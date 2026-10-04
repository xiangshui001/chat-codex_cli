import { expect, test, type Page } from '@playwright/test';
import { mkdir } from 'node:fs/promises';

let errors: string[];
let external: string[];
test.beforeEach(async ({ page }) => {
  errors = [];
  external = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });
  page.on('request', (request) => {
    const url = request.url();
    if (/^https?:/.test(url) && new URL(url).origin !== 'http://127.0.0.1:4173') external.push(url);
  });
  await page.goto('/?view=demo#/dashboard');
  await expect(page.getByRole('heading', { name: '工作区概览', exact: true })).toBeVisible();
});
test.afterEach(() => {
  expect(errors).toEqual([]);
  expect(external).toEqual([]);
});

async function navigate(page: Page, view: string) {
  if (await page.getByRole('button', { name: '打开导航', exact: true }).isVisible()) {
    await page.getByRole('button', { name: '打开导航', exact: true }).click();
  }
  await page.locator(`.sidebar a[href="#/${view}"]`).click();
}
async function openDemo(page: Page) {
  if (!(await page.locator('.demo-tools').evaluate((element) => element.hasAttribute('open')))) {
    await page.locator('.demo-tools summary').click();
  }
}
async function applied(page: Page) {
  await expect(page.getByTestId('control-receipt')).toContainText('applied');
  await expect(page.getByRole('button', { name: '刷新工作区' })).toBeEnabled();
}
async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
}

test('all seven routes, task details and direct links render', async ({ page }) => {
  const headings = {
    tasks: '任务队列',
    models: '模型与推理配置',
    hosts: '执行主机',
    evidence: '任务证据',
    reviews: 'PR 审阅',
    members: '协作权限边界',
    dashboard: '工作区概览',
  };
  for (const [view, heading] of Object.entries(headings)) {
    await navigate(page, view);
    await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
  }
  await navigate(page, 'tasks');
  await page.getByRole('button', { name: 'GH-42 实现任务证据的只读投影' }).click();
  await expect(page.getByTestId('executor-frozen-model')).toHaveText('gpt-6.1-sol');
  await expect(page.getByRole('heading', { name: '状态轨迹' })).toBeVisible();
  await page.reload();
  await expect(page.getByTestId('executor-frozen-model')).toHaveText('gpt-6.1-sol');
});

test('model submission waits for applied and preserves claimed snapshots', async ({ page }) => {
  await navigate(page, 'models');
  await page.getByLabel('模型 ID', { exact: true }).first().fill('gpt-6-luna');
  await page.locator('#executor-effort').selectOption('medium');
  await page.getByRole('button', { name: '应用 Executor' }).click();
  await expect(page.getByTestId('control-receipt')).toContainText('等待生效');
  await expect(page.getByTestId('executor-confirmed-model')).toHaveText('gpt-6.1-sol');
  await expect(page.getByTestId('runtime-revision')).toHaveText('17');
  await expect(page.getByRole('button', { name: '应用 Reviewer' })).toBeDisabled();
  await applied(page);
  await expect(page.getByTestId('executor-confirmed-model')).toHaveText('gpt-6-luna');
  await expect(page.getByTestId('runtime-revision')).toHaveText('18');
  await expect(page.getByTestId('reviewer-confirmed-model')).toHaveText('gpt-6-sol');
  await navigate(page, 'tasks');
  await page.getByRole('button', { name: 'GH-42 实现任务证据的只读投影' }).click();
  await expect(page.getByTestId('executor-frozen-model')).toHaveText('gpt-6.1-sol');
  await page.getByRole('button', { name: /runtime-settings.snapshot.json/ }).click();
  await expect(page.getByTestId('evidence-text')).toContainText('"revision": 17');
});

test('unavailable model preserves confirmed defaults, revision and form draft', async ({
  page,
}) => {
  await navigate(page, 'models');
  await page.locator('#executor-model').fill('unavailable-demo');
  await page.getByRole('button', { name: '应用 Executor' }).click();
  await expect(page.getByTestId('control-receipt')).toContainText('model_unavailable');
  await expect(page.getByTestId('executor-confirmed-model')).toHaveText('gpt-6.1-sol');
  await expect(page.getByTestId('runtime-revision')).toHaveText('17');
  await expect(page.locator('#executor-model')).toHaveValue('unavailable-demo');
  await expect(page.getByRole('button', { name: '应用 Executor' })).toBeEnabled();
});

test('unknown result is queried by the same request ID without another submission', async ({
  page,
}) => {
  await navigate(page, 'models');
  await openDemo(page);
  await page.getByLabel('下一次控制结果').selectOption('unknown');
  await page.locator('#executor-model').fill('gpt-6-luna');
  await page.getByRole('button', { name: '应用 Executor' }).click();
  await expect(page.getByTestId('control-receipt')).toContainText('结果待确认');
  const identity = await page.locator('.request-id').textContent();
  await expect(page.getByTestId('executor-confirmed-model')).toHaveText('gpt-6.1-sol');
  await expect(page.getByRole('button', { name: '应用 Executor' })).toBeDisabled();
  await page.getByRole('button', { name: '查询同一请求' }).click();
  await applied(page);
  await expect(page.locator('.request-id')).toHaveText(identity!);
  await expect(page.getByTestId('runtime-revision')).toHaveText('18');
});

test('roles apply independently and pause keeps the active task running', async ({ page }) => {
  await navigate(page, 'models');
  await page.locator('#reviewer-model').fill('gpt-6.1-sol');
  await page.locator('#reviewer-effort').selectOption('xhigh');
  await page.getByRole('button', { name: '应用 Reviewer' }).click();
  await applied(page);
  await expect(page.getByTestId('reviewer-confirmed-model')).toHaveText('gpt-6.1-sol');
  await expect(page.getByTestId('executor-confirmed-model')).toHaveText('gpt-6.1-sol');
  await expect(page.getByTestId('runtime-revision')).toHaveText('18');
  await page.locator('.sidebar').getByRole('button', { name: '暂停新任务' }).click();
  await expect(page.getByTestId('control-receipt')).toContainText('pending');
  await applied(page);
  await expect(page.locator('.sidebar').getByRole('button', { name: '恢复领取' })).toBeEnabled();
  await navigate(page, 'dashboard');
  await expect(page.locator('.current-task')).toContainText('executing');
  await page.locator('.sidebar').getByRole('button', { name: '恢复领取' }).click();
  await expect(page.getByTestId('control-receipt')).toContainText('pending');
  await applied(page);
  await expect(page.locator('.sidebar').getByRole('button', { name: '暂停新任务' })).toBeEnabled();
});

for (const role of ['viewer', 'reviewer'] as const) {
  test(`${role} has read-only controls and a capability route guard`, async ({ page }) => {
    await navigate(page, 'models');
    await openDemo(page);
    await page.getByLabel('演示身份').selectOption(role);
    await expect(page.locator('#executor-model')).toBeDisabled();
    await expect(page.locator('.sidebar a[href="#/members"]')).toHaveCount(0);
    await expect(
      page.locator('.sidebar').getByRole('button', { name: '暂停新任务' }),
    ).toBeDisabled();
    await page.evaluate(() => {
      window.location.hash = '#/members';
    });
    await expect(page.getByRole('heading', { name: '权限受限' })).toBeVisible();
    await page.getByLabel('演示身份').selectOption('operator');
    await expect(page.getByRole('heading', { name: '协作权限边界' })).toBeVisible();
    await navigate(page, 'models');
    await expect(page.locator('#executor-model')).toBeEnabled();
  });
}

test('evidence viewer shows flat contracts, missing and withheld files and audit JSONL', async ({
  page,
}) => {
  await navigate(page, 'evidence');
  await page
    .locator('.file-list')
    .getByRole('button', { name: /task.raw.json/ })
    .click();
  await expect(page.getByTestId('evidence-text')).toContainText('"task_id": "GH-42"');
  const raw = JSON.parse((await page.getByTestId('evidence-text').textContent())!);
  expect(raw.task).toBeUndefined();
  await page.getByLabel('选择任务').selectOption('GH-43');
  await page
    .locator('.file-list')
    .getByRole('button', { name: /task.resolved.json/ })
    .click();
  await expect(page.getByRole('heading', { name: '证据尚未生成' })).toBeVisible();
  await page.getByLabel('选择任务').selectOption('GH-41');
  await page
    .locator('.file-list')
    .getByRole('button', { name: /reviewer-result.json/ })
    .click();
  await expect(page.getByRole('heading', { name: '此证据未开放' })).toBeVisible();
  await page
    .locator('.file-list')
    .getByRole('button', { name: /events.jsonl/ })
    .click();
  await expect(page.getByTestId('evidence-text')).toContainText('"event":"claimed"');
  await page.getByLabel('选择任务').selectOption('GH-39');
  await page.getByRole('button', { name: '任务详情', exact: true }).click();
  await expect(page.locator('main')).toContainText('unavailable');
});

test('search, empty results, failure filter and keyboard focus work', async ({ page }) => {
  await navigate(page, 'models');
  await page.keyboard.press('Control+k');
  await expect(page.getByRole('textbox', { name: '搜索任务', exact: true })).toBeFocused();
  await page.getByRole('textbox', { name: '搜索任务', exact: true }).fill('no-such-task');
  await expect(page.getByRole('heading', { name: '没有匹配的任务' })).toBeVisible();
  await page.getByRole('textbox', { name: '搜索任务', exact: true }).fill('');
  await page.locator('.filter-pills').getByRole('button', { name: '异常', exact: true }).click();
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await expect(page.locator('tbody')).toContainText('model_unavailable');
});

test('read failure displays stale data, disables writes and supports retry', async ({ page }) => {
  await navigate(page, 'models');
  await openDemo(page);
  await page.getByRole('button', { name: '演示读取失败' }).click();
  await expect(page.getByRole('alert')).toContainText('工作区读取失败');
  await expect(page.getByTestId('executor-confirmed-model')).toHaveText('gpt-6.1-sol');
  await expect(page.locator('#executor-model')).toBeDisabled();
  await page.getByRole('button', { name: '重试读取' }).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.locator('#executor-model')).toBeEnabled();
});

test('unknown task and malformed route show explicit errors', async ({ page }) => {
  await page.goto('/?view=demo#/tasks/GH-999');
  await expect(page.getByRole('heading', { name: '任务读取失败' })).toBeVisible();
  await expect(page.locator('main')).toContainText('GH-999');
  await page.goto('/?view=demo#/evidence/GH-42/not-allowed.json');
  await expect(page.getByRole('heading', { name: '页面不存在' })).toBeVisible();
});

test('theme persists, desktop and mobile pages fit, and drawer handles keyboard focus', async ({
  page,
}) => {
  await noOverflow(page);
  if (process.env.UPDATE_SCREENSHOTS === '1') {
    await mkdir('screenshots', { recursive: true });
    await page.screenshot({ path: 'screenshots/desktop-light.png', fullPage: true });
  }
  await navigate(page, 'models');
  await page.getByRole('button', { name: '切换亮暗主题' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await expect(page.getByTestId('executor-confirmed-model')).toHaveText('gpt-6.1-sol');
  if (process.env.UPDATE_SCREENSHOTS === '1')
    await page.screenshot({ path: 'screenshots/desktop-dark-models.png', fullPage: true });
  await page.getByRole('button', { name: '切换亮暗主题' }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  for (const view of ['dashboard', 'tasks', 'models', 'hosts', 'evidence', 'reviews', 'members']) {
    await navigate(page, view);
    await expect(page.getByRole('button', { name: '打开导航', exact: true })).toBeVisible();
    await expect(page.getByRole('dialog', { name: '工作区导航' })).toHaveCount(0);
    await noOverflow(page);
  }
  await page.getByRole('button', { name: '打开导航', exact: true }).click();
  await expect(page.getByRole('button', { name: '关闭导航', exact: true })).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(page.getByRole('button', { name: '切换亮暗主题' })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: '打开导航', exact: true })).toBeFocused();
  await navigate(page, 'tasks');
  await page.getByRole('button', { name: 'GH-42 实现任务证据的只读投影' }).click();
  await expect(page.getByTestId('executor-frozen-model')).toBeVisible();
  await noOverflow(page);
  if (process.env.UPDATE_SCREENSHOTS === '1')
    await page.screenshot({ path: 'screenshots/mobile-task.png', fullPage: true });
  await page.setViewportSize({ width: 320, height: 740 });
  await noOverflow(page);
  await navigate(page, 'dashboard');
  await noOverflow(page);
});
