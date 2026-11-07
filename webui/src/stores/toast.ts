/**
 * 全局操作结果提示（toast）。
 *
 * 与 coverPreview 相同采用模块级状态：纯 UI 展示状态，无需持久化，
 * 也便于未安装 pinia 的页面与测试直接使用。
 * 同屏最多展示 MAX_VISIBLE 条，超出部分进入队列等待。
 */

import { ref } from 'vue'

export type ToastType = 'success' | 'error' | 'info'

export interface ToastMessage {
  id: number
  type: ToastType
  message: string
  /** 自动消失毫秒数；null 表示常驻，需手动关闭。 */
  timeout: number | null
}

/** 默认 4 秒自动消失。 */
export const DEFAULT_TOAST_TIMEOUT = 4000

/** 同屏最多展示条数。 */
export const MAX_VISIBLE_TOASTS = 3

const visible = ref<ToastMessage[]>([])
const pending: ToastMessage[] = []
const timers = new Map<number, ReturnType<typeof setTimeout>>()
let nextId = 1

/** 展示一条消息；同屏已满时排队等待前面的消息消失。 */
function push(type: ToastType, message: string, timeout: number | null): void {
  const item: ToastMessage = { id: nextId++, type, message, timeout }
  if (visible.value.length >= MAX_VISIBLE_TOASTS) {
    pending.push(item)
    return
  }
  show(item)
}

function show(item: ToastMessage): void {
  visible.value.push(item)
  if (item.timeout !== null) {
    timers.set(item.id, setTimeout(() => dismiss(item.id), item.timeout))
  }
}

/** 关闭一条消息；有排队消息时立即补位。 */
function dismiss(id: number): void {
  const timer = timers.get(id)
  if (timer !== undefined) {
    clearTimeout(timer)
    timers.delete(id)
  }
  const index = visible.value.findIndex((item) => item.id === id)
  if (index >= 0) {
    visible.value.splice(index, 1)
  }
  const next = pending.shift()
  if (next) show(next)
}

/** 清空全部消息与队列（页面级清理与测试用）。 */
function clear(): void {
  for (const timer of timers.values()) clearTimeout(timer)
  timers.clear()
  pending.length = 0
  visible.value = []
}

function success(message: string): void {
  push('success', message, DEFAULT_TOAST_TIMEOUT)
}

function error(message: string): void {
  push('error', message, DEFAULT_TOAST_TIMEOUT)
}

/** 信息提示；persistent 为 true 时不自动消失。 */
function info(message: string, options: { persistent?: boolean } = {}): void {
  push('info', message, options.persistent ? null : DEFAULT_TOAST_TIMEOUT)
}

export function useToast() {
  return { visible, pending, success, error, info, dismiss, clear }
}
