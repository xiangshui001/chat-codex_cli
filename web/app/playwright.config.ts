import { defineConfig } from '@playwright/test';

// Standard Playwright Chromium by default; an existing local browser is optional.
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  timeout: 30_000,
  use: {
    baseURL: 'http://127.0.0.1:4173',
    browserName: 'chromium',
    viewport: { width: 1440, height: 1080 },
    launchOptions: executablePath
      ? { executablePath, args: ['--no-sandbox', '--disable-dev-shm-usage'] }
      : {},
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'npm run preview -- --port 4173 --strictPort',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: !process.env.CI,
  },
});
