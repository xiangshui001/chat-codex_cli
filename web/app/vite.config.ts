import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: './',
  server: {
    proxy: { '/api/mvp1': { target: 'http://127.0.0.1:8791', changeOrigin: true } },
  },
});
