import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const contractDir = fileURLToPath(new URL('../../contract', import.meta.url))
const srcDir = fileURLToPath(new URL('./src', import.meta.url))

export default defineConfig({
  plugins: [react(), tailwindcss()],
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
})
