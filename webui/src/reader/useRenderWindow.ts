/**
 * 渲染窗口管理：只渲染当前页 ±1，离开窗口释放 Canvas 与页面资源。
 *
 * 同一 Canvas 禁止并发渲染；缩放/翻页时通过版本号与 RenderTask.cancel()
 * 取消过期任务。渲染失败会抛出，由页面统一映射为错误界面。
 */

import type { PDFDocumentProxy, PDFPageProxy, RenderTask } from 'pdfjs-dist'
import { onBeforeUnmount, watch, type Ref } from 'vue'

import { MAX_CANVAS_DIMENSION } from './types'
import { isRenderingCancelled } from './pdfErrors'

export interface RenderWindowHandle {
  /** 由模板 ref 调用：注册/注销页面 Canvas。 */
  registerCanvas: (pageNumber: number, canvas: HTMLCanvasElement | null) => void
  /** 同步渲染窗口：渲染窗口内页面并释放窗口外页面。 */
  syncWindow: (pageNumbers: number[], scale: number) => Promise<void>
  /** 取消所有进行中的渲染任务（不释放已渲染内容）。 */
  cancelAll: () => void
  /** 释放全部页面资源（组件卸载时调用）。 */
  releaseAll: () => void
}

export function useRenderWindow(
  doc: Ref<PDFDocumentProxy | null>,
): RenderWindowHandle {
  const canvases = new Map<number, HTMLCanvasElement>()
  const pages = new Map<number, PDFPageProxy>()
  const tasks = new Map<number, RenderTask>()
  const renderedScale = new Map<number, number>()
  const pendingScale = new Map<number, number>()
  const versions = new Map<number, number>()

  function bumpVersion(pageNumber: number): number {
    const version = (versions.get(pageNumber) ?? 0) + 1
    versions.set(pageNumber, version)
    return version
  }

  function cancelPage(pageNumber: number): void {
    const task = tasks.get(pageNumber)
    if (task) {
      task.cancel()
      tasks.delete(pageNumber)
    }
  }

  function releasePage(pageNumber: number): void {
    cancelPage(pageNumber)
    bumpVersion(pageNumber)
    renderedScale.delete(pageNumber)
    pendingScale.delete(pageNumber)
    const page = pages.get(pageNumber)
    if (page) {
      page.cleanup()
      pages.delete(pageNumber)
    }
    const canvas = canvases.get(pageNumber)
    if (canvas) {
      // 尺寸归零释放位图内存；重新进入窗口会重新渲染
      canvas.width = 0
      canvas.height = 0
    }
  }

  function registerCanvas(
    pageNumber: number,
    canvas: HTMLCanvasElement | null,
  ): void {
    if (canvas) {
      canvases.set(pageNumber, canvas)
    } else {
      canvases.delete(pageNumber)
      releasePage(pageNumber)
    }
  }

  async function getPage(pageNumber: number): Promise<PDFPageProxy | null> {
    const document = doc.value
    if (!document) return null
    const cached = pages.get(pageNumber)
    if (cached) return cached
    const page = await document.getPage(pageNumber)
    pages.set(pageNumber, page)
    return page
  }

  async function renderPage(pageNumber: number, scale: number): Promise<void> {
    const canvas = canvases.get(pageNumber)
    if (!canvas) return
    if (renderedScale.get(pageNumber) === scale && canvas.width > 0) return
    if (pendingScale.get(pageNumber) === scale) return
    const version = bumpVersion(pageNumber)
    pendingScale.set(pageNumber, scale)
    cancelPage(pageNumber)
    try {
      const page = await getPage(pageNumber)
      if (!page) return
      // 页面在等待期间被释放/替换时放弃本次渲染
      if (versions.get(pageNumber) !== version) return
      const viewport = page.getViewport({ scale })
      const outputScale = Math.min(
        window.devicePixelRatio || 1,
        MAX_CANVAS_DIMENSION / Math.max(viewport.width, viewport.height),
      )
      canvas.width = Math.floor(viewport.width * outputScale)
      canvas.height = Math.floor(viewport.height * outputScale)
      canvas.style.width = `${viewport.width}px`
      canvas.style.height = `${viewport.height}px`
      const task = page.render({
        canvas,
        viewport,
        transform:
          Math.abs(outputScale - 1) < 0.001
            ? undefined
            : [outputScale, 0, 0, outputScale, 0, 0],
      })
      tasks.set(pageNumber, task)
      try {
        await task.promise
        renderedScale.set(pageNumber, scale)
      } catch (error) {
        if (!isRenderingCancelled(error)) throw error
      } finally {
        if (tasks.get(pageNumber) === task) tasks.delete(pageNumber)
      }
    } finally {
      if (pendingScale.get(pageNumber) === scale) {
        pendingScale.delete(pageNumber)
      }
    }
  }

  async function syncWindow(
    pageNumbers: number[],
    scale: number,
  ): Promise<void> {
    const wanted = new Set(pageNumbers)
    for (const existing of [...canvases.keys()]) {
      if (!wanted.has(existing)) releasePage(existing)
    }
    await Promise.all(pageNumbers.map((page) => renderPage(page, scale)))
  }

  function cancelAll(): void {
    for (const pageNumber of [...tasks.keys()]) cancelPage(pageNumber)
  }

  function releaseAll(): void {
    for (const pageNumber of [...canvases.keys()]) releasePage(pageNumber)
    for (const pageNumber of [...pages.keys()]) releasePage(pageNumber)
  }

  // 文档替换（重新加载/销毁）时释放旧页资源
  watch(doc, () => {
    releaseAll()
  })

  onBeforeUnmount(releaseAll)

  return { registerCanvas, syncWindow, cancelAll, releaseAll }
}
