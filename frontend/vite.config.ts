import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Vite runs on the host during local development, while Compose publishes
// the backend on localhost:8010. Containerized callers can override this.
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://localhost:8010'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true,
        ws: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
