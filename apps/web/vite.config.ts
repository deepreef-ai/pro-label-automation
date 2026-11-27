import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const contractDir = fileURLToPath(new URL('../../contract', import.meta.url))
const srcDir = fileURLToPath(new URL('./src', import.meta.url))

// `vite --mode live` (npm run dev:live / build:live) talks to the FastAPI backend; any other mode keeps
// VITE_API_MODE from the environment / .env files (default mock).
export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss()],
  define: mode === 'live' ? { 'import.meta.env.VITE_API_MODE': JSON.stringify('live') } : {},
  resolve: {
    alias: {
      '@contract': contractDir,
      '@': srcDir,
    },
  },
  server: {
    port: 5173,
    fs: {
      allow: ['.', contractDir],
    },
  },
  preview: {
    port: 4173,
  },
}))
