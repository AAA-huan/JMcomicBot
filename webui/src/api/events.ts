/** WebSocket 事件客户端：自动退避重连，恢复后由调用方重新拉取 REST 快照。 */

import type { EventEnvelope } from '@/types/api'

const MAX_RECONNECT_DELAY_MS = 30_000
const BASE_RECONNECT_DELAY_MS = 1_000
const PING_INTERVAL_MS = 30_000

export interface EventClientHandlers {
  onEvent: (event: EventEnvelope) => void
  /** 连接建立（含重连成功）：调用方应在此重新拉取完整 REST 快照。 */
  onOpen?: () => void
  /** 连接断开，参数为下一次重连的等待毫秒数。 */
  onClose?: (reconnectDelayMs: number) => void
}

export class EventClient {
  private readonly handlers: EventClientHandlers
  private socket: WebSocket | null = null
  private pingTimer: number | null = null
  private reconnectTimer: number | null = null
  private reconnectDelayMs = BASE_RECONNECT_DELAY_MS
  private stopped = true

  constructor(handlers: EventClientHandlers) {
    this.handlers = handlers
  }

  get connected(): boolean {
    return this.socket !== null && this.socket.readyState === WebSocket.OPEN
  }

  connect(): void {
    if (!this.stopped) return
    this.stopped = false
    this.open()
  }

  disconnect(): void {
    this.stopped = true
    this.clearPing()
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    const socket = this.socket
    this.socket = null
    if (socket !== null) {
      socket.onopen = null
      socket.onmessage = null
      socket.onclose = null
      socket.onerror = null
      socket.close()
    }
  }

  private open(): void {
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${protocol}://${window.location.host}/api/v1/events`
    const socket = new WebSocket(url)
    this.socket = socket

    socket.onopen = () => {
      this.reconnectDelayMs = BASE_RECONNECT_DELAY_MS
      this.startPing()
      this.handlers.onOpen?.()
    }

    socket.onmessage = (message: MessageEvent<string>) => {
      try {
        const event = JSON.parse(message.data) as EventEnvelope
        this.handlers.onEvent(event)
      } catch {
        // 无法解析的消息直接忽略，不影响后续推送
      }
    }

    socket.onclose = () => {
      this.clearPing()
      if (this.socket === socket) this.socket = null
      if (this.stopped) return
      const delay = this.reconnectDelayMs
      this.handlers.onClose?.(delay)
      this.reconnectTimer = window.setTimeout(() => {
        this.reconnectTimer = null
        if (!this.stopped) this.open()
      }, delay)
      this.reconnectDelayMs = Math.min(delay * 2, MAX_RECONNECT_DELAY_MS)
    }

    socket.onerror = () => {
      socket.close()
    }
  }

  private startPing(): void {
    this.clearPing()
    this.pingTimer = window.setInterval(() => {
      if (this.socket !== null && this.socket.readyState === WebSocket.OPEN) {
        this.socket.send('ping')
      }
    }, PING_INTERVAL_MS)
  }

  private clearPing(): void {
    if (this.pingTimer !== null) {
      window.clearInterval(this.pingTimer)
      this.pingTimer = null
    }
  }
}
