import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// En desarrollo (npm run dev) las llamadas a la API se envían al backend de Python.
const API = process.env.FILEMIND_API || 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': API, '/health': API, '/reportes': API },
  },
  build: { outDir: 'dist', sourcemap: true },
});
