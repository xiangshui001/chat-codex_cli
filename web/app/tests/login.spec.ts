import { expect as baseExpect, test, type Page } from '@playwright/test';
import { mkdir } from 'node:fs/promises';

// Software WebGL context creation/disposal can take longer than a DOM-only page.
const expect = baseExpect.configure({ timeout: 10_000 });

declare global {
  interface Window {
    libraryProbe: {
      frames: Map<number, string>;
      contexts: WebGL2RenderingContext[];
      observers: Set<ResizeObserver>;
    };
  }
}

let errors: string[];
let external: string[];
test.beforeEach(async ({ page, baseURL }) => {
  errors = [];
  external = [];
  const origin = new URL(baseURL!).origin;
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (request) => {
    const url = request.url();
    if (/^https?:/.test(url) && new URL(url).origin !== origin) external.push(url);
  });
});
test.afterEach(() => {
  expect(errors).toEqual([]);
  expect(external).toEqual([]);
});

async function instrument(page: Page) {
  // These probes run only in tests. The real scene still uses the real WebGL renderer.
  await page.addInitScript(() => {
    const frames = new Map<number, string>();
    const contexts: WebGL2RenderingContext[] = [];
    const observers = new Set<ResizeObserver>();
    window.libraryProbe = { frames, contexts, observers };
    const request = window.requestAnimationFrame.bind(window);
    const cancel = window.cancelAnimationFrame.bind(window);
    window.requestAnimationFrame = (callback) => {
      const id = request((time) => {
        frames.delete(id);
        callback(time);
      });
      frames.set(id, `${callback.name}\n${new Error().stack}`);
      return id;
    };
    window.cancelAnimationFrame = (id) => {
      frames.delete(id);
      cancel(id);
    };
    const getContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, ...args) {
      const context = Reflect.apply(getContext, this, args);
      if (
        args[0] === 'webgl2' &&
        context instanceof WebGL2RenderingContext &&
        !contexts.includes(context)
      )
        contexts.push(context);
      return context;
    } as typeof getContext;
    const Observer = window.ResizeObserver;
    window.ResizeObserver = class extends Observer {
      observe(target: Element, options?: ResizeObserverOptions) {
        observers.add(this);
        super.observe(target, options);
      }
      disconnect() {
        observers.delete(this);
        super.disconnect();
      }
    };
  });
}
async function ready(page: Page) {
  await expect(page.getByTestId('library-model')).toHaveAttribute('data-status', 'ready', {
    timeout: 30_000,
  });
  await expect(page.locator('.library-scene canvas')).toHaveCount(1);
}
async function still(page: Page) {
  await expect
    .poll(() => page.evaluate(() => [...window.libraryProbe.frames.values()]), { timeout: 10_000 })
    .toEqual([]);
}
async function released(page: Page) {
  await expect(page.locator('.library-scene canvas')).toHaveCount(0);
  await expect
    .poll(() => page.evaluate(() => window.libraryProbe.contexts.every((gl) => gl.isContextLost())))
    .toBe(true);
  await expect.poll(() => page.evaluate(() => window.libraryProbe.observers.size)).toBe(0);
  await still(page);
}
async function capture(page: Page, name: string) {
  if (process.env.UPDATE_LOGIN_SCREENSHOTS !== '1') return;
  await mkdir('screenshots', { recursive: true });
  await page.screenshot({ path: `screenshots/login-${name}.png`, fullPage: true });
}

test('desktop outside model renders without a toolbar, motion or focus trap', async ({ page }) => {
  await instrument(page);
  const consoleErrors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  await page.goto('/');
  await expect(page.getByRole('button', { name: '进入演示工作区' })).toBeEnabled();
  await ready(page);
  await still(page);
  expect(await page.locator('.library-scene canvas').getAttribute('tabindex')).toBe('-1');
  expect(await page.locator('tisu-library').count()).toBe(0);
  await expect(page.getByRole('button')).toHaveCount(1);
  const bounds = await page.locator('.login-copy, .login-visual').evaluateAll((elements) =>
    elements.map((element) => {
      const { x, width } = element.getBoundingClientRect();
      return { x, width };
    }),
  );
  expect(bounds[0].x).toBeLessThan(bounds[1].x);
  expect(bounds[0].width / (bounds[0].width + bounds[1].width)).toBeGreaterThan(0.35);
  expect(bounds[0].width / (bounds[0].width + bounds[1].width)).toBeLessThan(0.45);
  await page.keyboard.press('Tab');
  await page.keyboard.press('Tab');
  await expect(page.getByRole('button', { name: '进入演示工作区' })).toBeFocused();
  await capture(page, 'desktop');
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: '工作区概览', exact: true })).toBeVisible();
  await released(page);
  expect(consoleErrors).toEqual([]);
});

test('repeated page entry and breakpoint changes dispose every scene', async ({ page }) => {
  await instrument(page);
  await page.goto('/#/login');
  await ready(page);
  const firstCount = await page.evaluate(() => window.libraryProbe.contexts.length);
  await page.setViewportSize({ width: 390, height: 844 });
  await ready(page);
  await expect
    .poll(() =>
      page.evaluate(() => window.libraryProbe.contexts.filter((gl) => !gl.isContextLost()).length),
    )
    .toBe(1);
  expect(await page.evaluate(() => window.libraryProbe.contexts.length)).toBeGreaterThan(
    firstCount,
  );
  expect(
    await page.locator('canvas').evaluate((canvas) => (canvas as HTMLCanvasElement).width),
  ).toBeLessThanOrEqual(390);
  await page.getByRole('button', { name: '进入演示工作区' }).click();
  await expect(page.getByRole('heading', { name: '工作区概览', exact: true })).toBeVisible();
  await released(page);
  for (let i = 0; i < 3; i++) {
    await page.locator('.demo-tools summary').click();
    await page.getByRole('button', { name: '查看未登录页' }).click();
    await ready(page);
    await still(page);
    await page.getByRole('button', { name: '进入演示工作区' }).click();
    await expect(page.getByRole('heading', { name: '工作区概览', exact: true })).toBeVisible();
    await released(page);
  }
});

test('leaving during lazy import cannot mount a late scene', async ({ page }) => {
  await instrument(page);
  let release!: () => void;
  const delayed = new Promise<void>((resolve) => {
    release = resolve;
  });
  let requested!: () => void;
  const started = new Promise<void>((resolve) => {
    requested = resolve;
  });
  await page.route('**/tisu/astral-library/library.js', async (route) => {
    requested();
    await delayed;
    await route.continue();
  });
  await page.goto('/');
  await started;
  await expect(page.getByTestId('library-model')).toHaveAttribute('data-status', 'loading');
  await page.getByRole('button', { name: '进入演示工作区' }).click();
  await expect(page.getByRole('heading', { name: '工作区概览', exact: true })).toBeVisible();
  release();
  // Import the same URL to wait for the queued import and its effect continuation.
  await page.evaluate(async () => {
    const url = '/tisu/astral-library/library.js';
    await import(url);
  });
  await released(page);
  expect(await page.evaluate(() => window.libraryProbe.contexts.length)).toBe(0);
});

test('failed WebGL keeps the entry button and keyboard usable', async ({ page }) => {
  await page.addInitScript(() => {
    const getContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, ...args) {
      if (args[0] === 'webgl2') return null;
      return Reflect.apply(getContext, this, args);
    } as typeof getContext;
  });
  await page.goto('/');
  await expect(page.getByTestId('library-model')).toHaveAttribute('data-status', 'fallback');
  await expect(page.getByText('模型暂不可用，你仍可进入工作区')).toBeVisible();
  await expect(page.locator('canvas')).toHaveCount(0);
  await capture(page, 'fallback');
  await page.keyboard.press('Tab');
  await page.keyboard.press('Tab');
  await expect(page.getByRole('button', { name: '进入演示工作区' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: '工作区概览', exact: true })).toBeVisible();
});

test('failed module load falls back without blocking entry', async ({ page }) => {
  await page.route('**/tisu/astral-library/library.js', (route) => route.abort());
  await page.goto('/');
  await expect(page.getByTestId('library-model')).toHaveAttribute('data-status', 'fallback');
  await page.getByRole('button', { name: '进入演示工作区' }).click();
  await expect(page.getByRole('heading', { name: '工作区概览', exact: true })).toBeVisible();
});

test('unexpected context loss releases the scene and shows fallback', async ({ page }) => {
  await instrument(page);
  await page.goto('/');
  await ready(page);
  await page.evaluate(() => {
    window.libraryProbe.contexts.at(-1)!.getExtension('WEBGL_lose_context')!.loseContext();
  });
  await expect(page.getByTestId('library-model')).toHaveAttribute('data-status', 'fallback');
  await released(page);
  await page.getByRole('button', { name: '进入演示工作区' }).click();
  await expect(page.getByRole('heading', { name: '工作区概览', exact: true })).toBeVisible();
});

test('mobile keeps entry first, allows scrolling, and respects reduced motion', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await instrument(page);
  await page.goto('/');
  await ready(page);
  await still(page);
  await expect(page.getByRole('button', { name: '进入演示工作区' })).toBeInViewport();
  const bounds = await page.locator('.login-copy, .login-visual').evaluateAll((elements) =>
    elements.map((element) => {
      const { y, height } = element.getBoundingClientRect();
      return { y, height };
    }),
  );
  expect(bounds[1].y).toBeGreaterThan(bounds[0].y + bounds[0].height);
  await capture(page, 'mobile');
  await page.locator('.library-model').hover();
  await page.mouse.wheel(0, 220);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
  await still(page);
  await page.setViewportSize({ width: 320, height: 740 });
  await ready(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.getByRole('button', { name: '进入演示工作区' }).click();
  await expect(page.getByRole('heading', { name: '工作区概览', exact: true })).toBeVisible();
  await released(page);
});
