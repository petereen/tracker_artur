import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { localeSplit } from './vite-plugins/localeSplit.ts'

export default defineConfig({
  plugins: [react(), localeSplit()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    exclude: ['e2e/**', 'node_modules/**', 'dist/**'],
  },
})
