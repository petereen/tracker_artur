import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { localeSplit } from './vite-plugins/localeSplit.ts'

// Vite runs on the host during local development, while Compose publishes
// the backend on localhost:8010. Containerized callers can override this.
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://localhost:8010'
const callProxyTarget = process.env.VITE_CALL_PROXY_TARGET || 'http://localhost:8020'

export default defineConfig({
  plugins: [react(), localeSplit()],
  build: {
    manifest: true,
    cssMinify: 'lightningcss',
    // Keep shared dependencies together so a route transition does not fan
    // out into dozens of tiny browser requests. This is especially important
    // for lucide-react, whose tree-shaken icon modules otherwise become one
    // request per icon in Vite 8/Rolldown output.
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name: 'react-core',
              test: /node_modules[\\/](?:react|react-dom|react-router|react-router-dom)[\\/]/,
              priority: 40,
            },
            {
              name: 'data-core',
              test: /node_modules[\\/](?:@tanstack|axios|zustand|i18next|react-i18next)[\\/]/,
              priority: 35,
            },
            {
              name: 'motion',
              test: /node_modules[\\/](?:motion|framer-motion|motion-dom|motion-utils)[\\/]/,
              priority: 34,
            },
            {
              name: 'sentry',
              test: /node_modules[\\/]@sentry[\\/]/,
              priority: 33,
            },
            {
              name: 'charts',
              test: /node_modules[\\/]recharts[\\/]/,
              priority: 32,
            },
            {
              name: 'editor',
              test: /node_modules[\\/](?:@tiptap|prosemirror)[\\/]/,
              priority: 31,
            },
            // The catch-all `vendor` chunk is loaded on first paint (it holds
            // Astryx), so anything that lands in it is downloaded even when only
            // a lazy page needs it. Keep these page-specific libraries in their
            // own chunks so they load with the page that imports them.
            {
              name: 'markdown',
              test: /node_modules[\\/](?:react-markdown|remark-[^\\/]+|micromark[^\\/]*|mdast-[^\\/]+|hast-[^\\/]+|unified|vfile[^\\/]*|unist-[^\\/]+|property-information|decode-named-character-reference|character-entities[^\\/]*|space-separated-tokens|comma-separated-tokens|html-url-attributes|devlop|bail|trough|is-plain-obj|estree-util-[^\\/]+|zwitch|longest-streak|ccount|markdown-table|trim-lines|style-to-[^\\/]+|inline-style-parser|@ungap)[\\/]/,
              priority: 30,
            },
            {
              name: 'realtime',
              test: /node_modules[\\/](?:socket\.io-[^\\/]+|engine\.io-[^\\/]+|@socket\.io)[\\/]/,
              priority: 30,
            },
            {
              name: 'qr',
              test: /node_modules[\\/]qrcode\.react[\\/]/,
              priority: 30,
            },
            {
              name: 'dnd',
              test: /node_modules[\\/]@dnd-kit[\\/]/,
              priority: 30,
            },
            {
              name: 'lucide',
              test: /node_modules[\\/]lucide-react[\\/]/,
              priority: 20,
            },
            {
              name: 'vendor',
              test: /node_modules[\\/]/,
              minShareCount: 2,
              minSize: 20 * 1024,
              priority: 10,
            },
          ],
        },
      },
    },
  },
  server: {
    host: true,
    port: 5173,
    strictPort: true,
    proxy: {
      '/socket.io': {
        target: callProxyTarget,
        changeOrigin: true,
        ws: true,
      },
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true,
        ws: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
