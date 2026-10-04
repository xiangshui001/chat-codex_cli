import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: { include: ['api-client/**/*.test.ts'], environment: 'node' },
});
