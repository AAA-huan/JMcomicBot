/// <reference types="vite/client" />

// PDF.js 的 Worker 入口未随包发布类型声明，仅用于导出解析器供内部调用。
declare module 'pdfjs-dist/legacy/build/pdf.worker.mjs' {
  export const WorkerMessageHandler: unknown
}

declare module '*.vue' {
  import type { DefineComponent } from 'vue'

  const component: DefineComponent<Record<string, never>, Record<string, never>, unknown>
  export default component
}
