/**
 * 阅读进度同步：1 秒防抖写入，页面隐藏/离开时 keepalive 立即刷新。
 *
 * 发送失败只更新状态并回调，不阻塞阅读；界面据此展示「进度未同步」
 * 并提供重试，绝不静默伪装成功。
 */

import { readCsrfToken } from '@/api/client'

export type ProgressSyncState = 'synced' | 'pending' | 'failed'

/** 进度写入防抖时间：翻页/滚动停止 1 秒后上报。 */
export const PROGRESS_DEBOUNCE_MS = 1000

export interface ProgressSyncOptions {
  fileId: number
  getPage: () => number
  getPageCount: () => number
  onStateChange: (state: ProgressSyncState) => void
  debounceMs?: number
}

export interface ProgressSync {
  /** 记录一次进度变化，防抖后写入。 */
  schedule: () => void
  /**
   * 立即写入待同步进度。
   *
   * keepalive=true 用于页面隐藏、切换文件或路由离开：即使页面随后被
   * 卸载也尽量把请求送达；等待前序请求完成后再发出，避免旧页码覆盖。
   */
  flush: (keepalive?: boolean) => Promise<boolean>
  /** 忽略防抖与脏标记，立即重发（失败重试按钮使用）。 */
  retry: () => Promise<boolean>
  /** 取消未决定时器并停用后续调度。 */
  dispose: () => void
}

export function createProgressSync(options: ProgressSyncOptions): ProgressSync {
  const { fileId, getPage, getPageCount, onStateChange } = options
  const debounceMs = options.debounceMs ?? PROGRESS_DEBOUNCE_MS

  let timer: number | null = null
  let disposed = false
  let dirty = false
  let inFlight: Promise<boolean> | null = null

  function clearTimer(): void {
    if (timer !== null) {
      window.clearTimeout(timer)
      timer = null
    }
  }

  async function doSend(keepalive: boolean): Promise<boolean> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    const csrf = readCsrfToken()
    if (csrf) headers['X-CSRF-Token'] = csrf
    try {
      const response = await fetch(`/api/v1/files/${fileId}/progress`, {
        method: 'PUT',
        headers,
        credentials: 'same-origin',
        body: JSON.stringify({
          page_number: getPage(),
          page_count: getPageCount(),
        }),
        keepalive,
      })
      if (!response.ok) {
        dirty = true
        onStateChange('failed')
        return false
      }
      dirty = false
      onStateChange('synced')
      return true
    } catch {
      // 网络中断或 keepalive 被拒：明确标记失败，由界面提示重试
      dirty = true
      onStateChange('failed')
      return false
    }
  }

  async function send(keepalive: boolean): Promise<boolean> {
    // 串行化发送，避免两个请求乱序导致旧页码覆盖新页码
    if (inFlight) {
      await inFlight
    }
    const task = doSend(keepalive)
    inFlight = task
    try {
      return await task
    } finally {
      if (inFlight === task) {
        inFlight = null
      }
    }
  }

  function schedule(): void {
    if (disposed) return
    dirty = true
    onStateChange('pending')
    clearTimer()
    timer = window.setTimeout(() => {
      timer = null
      if (dirty) void send(false)
    }, debounceMs)
  }

  async function flush(keepalive = false): Promise<boolean> {
    clearTimer()
    if (!dirty) return true
    return send(keepalive)
  }

  async function retry(): Promise<boolean> {
    onStateChange('pending')
    return send(false)
  }

  function dispose(): void {
    disposed = true
    clearTimer()
  }

  return { schedule, flush, retry, dispose }
}
