import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('../', import.meta.url))
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, root, 'VITE_')
  return {
    plugins: [vue()],
    build: mode === 'offline' ? {
      outDir: '../.runtime/web-preview', emptyOutDir: true,
      lib: { entry: 'src/offline.js', name: 'Shanhe', formats: ['iife'], fileName: () => 'preview.iife.js', cssFileName: 'preview' },
    } : {},
    define: { 'process.env.NODE_ENV': JSON.stringify(mode === 'development' ? 'development' : 'production') },
    envDir: root,
    server: { host: '127.0.0.1', strictPort: true, port: 5173, proxy: {
      '/api/v1': env.VITE_DEV_PROXY_TARGET || 'http://127.0.0.1:5000',
    } },
  }
})
