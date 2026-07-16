import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// duckdb-wasm uses top-level await + workers; esnext target keeps Vite from choking.
export default defineConfig({
  plugins: [react()],
  optimizeDeps: {
    exclude: ['@duckdb/duckdb-wasm'],
    esbuildOptions: { target: 'esnext' },
  },
  build: { target: 'esnext' },
  // host: true binds 0.0.0.0 so other devices on the LAN (e.g. your phone) can reach it.
  server: { host: true, port: 5173 },
});
