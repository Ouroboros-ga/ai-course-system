import { fileURLToPath, URL } from 'node:url'

import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig(async ({ mode }) => {
    const env = loadEnv(mode, process.cwd(), '')

    // Vue Devtools 底部黑色浮动胶囊（vite-plugin-vue-devtools）开关。
    // 由环境变量 VITE_DEVTOOLS 控制：
    //   VITE_DEVTOOLS=true  → 加载插件，页面右下角出现黑色调试胶囊（点击展开 Vue Devtools）
    //   VITE_DEVTOOLS=false（或未设置）→ 不加载，无胶囊（默认关闭）
    const enableVueDevtools = env.VITE_DEVTOOLS === 'true'

    return {
        plugins: [
            vue(),
            ...(enableVueDevtools ? [await import('vite-plugin-vue-devtools').then(m => m.default())] : []),
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
