import { defineConfig } from '@playwright/test';
import config from './playwright.config';

// The Vite dev build enables React StrictMode's extra effect setup/cleanup.
export default defineConfig({
  ...config,
  testMatch: 'login.spec.ts',
  use: { ...config.use, baseURL: 'http://127.0.0.1:4174' },
  webServer: {
    command: 'npm run dev -- --port 4174 --strictPort',
    url: 'http://127.0.0.1:4174',
    reuseExistingServer: false,
  },
});
