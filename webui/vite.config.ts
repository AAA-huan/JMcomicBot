/// <reference types="vitest/config" />
import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'
import vuetify from 'vite-plugin-vuetify'

// 构建产物直接输出到后端静态目录，随仓库发布
export default defineConfig({
  plugins: [vue(), vuetify({ autoImport: true })],
  worker: {
    format: 'es',
    // PDF.js 会在 Worker 无法创建时动态导入入口，必须保留解析器导出。
    plugins: () => [{
      name: 'preserve-pdf-worker-exports',
      options: (options) => ({ ...options, preserveEntrySignatures: 'strict' }),
    }],
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    outDir: '../src/web/static',
    emptyOutDir: true,
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      // 开发环境把 API 与事件推送代理到本机后端
      '/api': {
        target: 'http://127.0.0.1:7999',
        changeOrigin: false,
        ws: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['src/tests/setup.ts'],
    include: ['src/**/*.test.ts'],
    server: {
      deps: {
        // Vuetify 的 ESM 内含 CSS 导入，需要交给 Vite 转换
        inline: ['vuetify'],
      },
    },
  },
})
