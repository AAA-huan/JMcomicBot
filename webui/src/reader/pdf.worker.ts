/** Worker 独立环境也需要补齐旧版手机浏览器缺少的 Promise API。 */
import './promiseCompatibility'

// 保留导出，供 PDF.js 在 Worker 无法启动时使用同一模块解析。
export { WorkerMessageHandler } from 'pdfjs-dist/legacy/build/pdf.worker.mjs'
