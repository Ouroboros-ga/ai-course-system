import { fileURLToPath, URL } from 'node:url'

import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig(async ({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  
  return {
    plugins: [
      vue(),
      ...(env.VITE_DEVTOOLS !== 'false' ? [await import('vite-plugin-vue-devtools').then(m => m.default())] : []),
    ],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url))
      },
    },
    server: {
      host: '0.0.0.0',
      // 5173 落在 Windows 端口排除范围(5156-5255,Hyper-V/WinNAT 动态保留)内,
      // bind 会报 EACCES。5300 不在任何排除范围内。
      port: 5300,
      strictPort: false,
      proxy: {
        '/api': {
          // Windows can reserve a development port even when no process is
          // listening.  Keep the normal 8000 default, while letting a local
          // developer point this proxy at the active backend without editing
          // committed source again.
          target: env.VITE_API_PROXY_TARGET || 'http://localhost:8000',
          changeOrigin: true,
        },
      },
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks: {
            'vue-vendor': ['vue', 'vue-router', 'pinia'],
            'markdown': ['marked', 'marked-highlight', 'highlight.js', 'katex'],
            'ui-utils': ['axios', 'dompurify'],
          }
        }
      },
      chunkSizeWarningLimit: 1000,
    },
  }
})
