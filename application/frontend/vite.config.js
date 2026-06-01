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
  server: { port: 5173 },
});
