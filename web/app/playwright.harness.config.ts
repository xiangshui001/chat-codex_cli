import { defineConfig } from '@playwright/test';
import config from './playwright.config';

// Each test starts a real Python CLI harness in an isolated temporary state dir.
export default defineConfig({
  ...config,
  testMatch: '**/harness-smoke.spec.ts',
  testIgnore: [],
  timeout: 90_000,
  webServer: undefined,
});
