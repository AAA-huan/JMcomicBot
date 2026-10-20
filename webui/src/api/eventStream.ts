/** 模块级事件分发：布局收到 WS 事件后分发给页面订阅者（不进入 Pinia）。 */

import { onBeforeUnmount, onMounted } from 'vue'

import type { EventEnvelope } from '@/types/api'

export type EventHandler = (event: EventEnvelope) => void
export type ConnectionHandler = () => void

const handlers = new Set<EventHandler>()
const connectionHandlers = new Set<ConnectionHandler>()

export function emitEvent(event: EventEnvelope): void {
  // 复制一份避免处理过程中增删订阅者影响遍历
  for (const handler of [...handlers]) {
    handler(event)
  }
}

export function subscribeEvents(handler: EventHandler): () => void {
  handlers.add(handler)
  return () => {
    handlers.delete(handler)
  }
}

/** 在组件生命周期内订阅事件，卸载时自动取消。 */
export function useEventSubscription(handler: EventHandler): void {
  let unsubscribe: (() => void) | null = null
  onMounted(() => {
    unsubscribe = subscribeEvents(handler)
  })
  onBeforeUnmount(() => {
    unsubscribe?.()
    unsubscribe = null
  })
}

/** 通知订阅者 WebSocket 已连接；页面应重新拉取 REST 快照补上断线期间的数据。 */
export function emitConnection(): void {
  for (const handler of [...connectionHandlers]) {
    handler()
  }
}

export function subscribeConnection(handler: ConnectionHandler): () => void {
  connectionHandlers.add(handler)
  return () => {
    connectionHandlers.delete(handler)
  }
}

/** 在组件生命周期内订阅连接恢复事件，卸载时自动取消。 */
export function useConnectionSubscription(handler: ConnectionHandler): void {
  let unsubscribe: (() => void) | null = null
  onMounted(() => {
    unsubscribe = subscribeConnection(handler)
  })
  onBeforeUnmount(() => {
    unsubscribe?.()
    unsubscribe = null
  })
}
