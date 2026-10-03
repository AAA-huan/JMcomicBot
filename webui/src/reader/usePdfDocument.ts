/**
 * PDF 文档加载：Worker 同源打包、按需 Range 拉取、错误映射为中文提示。
 *
 * Worker 通过 Vite 的 `?worker&url` 打包为同源资源，
 * 生产环境不依赖 CDN；PDF 由 FileResponse 按 Range 分段提供，不会
 * 整本读入内存。
 */

import './promiseCompatibility'

import { GlobalWorkerOptions, getDocument } from 'pdfjs-dist/legacy/build/pdf.mjs'
import type { PDFDocumentLoadingTask, PDFDocumentProxy } from 'pdfjs-dist'
import { shallowRef, type ShallowRef } from 'vue'

import { fileContentUrl } from '@/api/files'

import { mapPdfError, type ReaderError } from './pdfErrors'
import pdfWorkerUrl from './pdf.worker?worker&url'

// 主线程与 Worker 均使用官方兼容构建，并显式补齐它不再提供的
// Promise.withResolvers；主线程中的补齐不会影响独立的 Worker 环境。
// Worker 与主线程同源：交给 PDF.js 按 workerSrc 自行创建与销毁 Worker。
// 不使用共享 workerPort，避免文档销毁时端口被终止后再次进入阅读器永久失败；
// Worker 加载失败时 PDF.js 会基于同一 URL 回退到主线程解析（fake worker）。
GlobalWorkerOptions.workerSrc = pdfWorkerUrl

/** 静默销毁可能已失败或被替换的加载任务，只记录不抛出。 */
async function destroyTask(task: PDFDocumentLoadingTask): Promise<void> {
  try {
    await task.destroy()
  } catch (error) {
    console.warn('销毁 PDF 加载任务时出现异常', error)
  }
}

export function usePdfDocument(): {
  doc: ShallowRef<PDFDocumentProxy | null>
  load: (fileId: number) => Promise<ReaderError | null>
  destroy: () => Promise<void>
} {
  const doc = shallowRef<PDFDocumentProxy | null>(null)
  let loadingTask: PDFDocumentLoadingTask | null = null

  async function destroy(): Promise<void> {
    const task = loadingTask
    loadingTask = null
    doc.value = null
    if (task) {
      await destroyTask(task)
    }
  }

  async function load(fileId: number): Promise<ReaderError | null> {
    await destroy()
    let task: PDFDocumentLoadingTask | null = null
    try {
      // 创建任务本身也可能同步抛错，必须进入统一错误处理，避免一直显示加载中。
      task = getDocument({
        url: fileContentUrl(fileId),
        withCredentials: true,
      })
      loadingTask = task
      doc.value = await task.promise
      return null
    } catch (error) {
      // 保留原始错误供排查（错误界面只展示安全的中文提示）
      console.error('PDF 加载失败', error)
      if (loadingTask === task) {
        loadingTask = null
        doc.value = null
      }
      if (task) await destroyTask(task)
      return mapPdfError(error)
    }
  }

  return { doc, load, destroy }
}
