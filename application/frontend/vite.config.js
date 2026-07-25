import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    // host: true binds 0.0.0.0 so other devices on the LAN (e.g. your phone) can reach it.
    host: true,
    port: 5173,
    // The front end fetches relative `/api/…`; in dev this proxies to the local uvicorn so
    // it's same-origin (no CORS). The deployed cross-origin story is Session 6.
    proxy: { '/api': 'http://localhost:8000' },
  },
});
