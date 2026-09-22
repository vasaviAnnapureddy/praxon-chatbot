import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Two jobs:
//
// 1. DEV: React runs on :5173 and FastAPI on :8000. The proxy below makes
//    /api and /health look like they come from :5173, so the frontend code can
//    use plain relative URLs ("/api/chat") and never know which mode it is in.
//    That is what makes the SAME build work on localhost, on the Render URL and
//    on a future real domain, with no environment variable anywhere.
//
// 2. BUILD: everything is squeezed into frontend/dist, which the Dockerfile
//    copies next to the Python code and FastAPI then serves.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        // Server-Sent Events must not be buffered by the dev proxy, or the
        // typing effect turns into one sudden paragraph.
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            if (String(proxyRes.headers['content-type']).includes('text/event-stream')) {
              proxyRes.headers['cache-control'] = 'no-cache, no-transform'
            }
          })
        },
      },
      '/health': 'http://127.0.0.1:8000',
      '/brand': 'http://127.0.0.1:8000',      // logo files live in client/brand, served by FastAPI
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    // Small chunks matter on Indian mobile networks.
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom', 'react-router-dom'],
        },
      },
    },
  },
})
