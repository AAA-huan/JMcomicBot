import { ref } from 'vue'
import { defineStore } from 'pinia'

import { errorMessage } from '@/api/client'
import { getSystemStatus } from '@/api/system'
import type { EventEnvelope, QueueStatus, SystemStatus } from '@/types/api'

interface QueueUpdatedData {
  download: QueueStatus
  send: QueueStatus
}

interface NapcatUpdatedData {
  connected: boolean
}

interface SystemUpdatedData {
  version: string
  uptime_seconds: number
  manga_count: number
}

/** 系统状态：REST 快照 + WebSocket 增量更新。 */
export const useSystemStore = defineStore('system', () => {
  const status = ref<SystemStatus | null>(null)
  const loading = ref(false)
  const error = ref('')
  const eventsConnected = ref(false)

  async function refresh(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      status.value = await getSystemStatus()
    } catch (err) {
      error.value = errorMessage(err)
    } finally {
      loading.value = false
    }
  }

  function applyEvent(event: EventEnvelope): void {
    const current = status.value
    if (current === null) return
    if (event.type === 'queue.updated') {
      const data = event.data as QueueUpdatedData
      current.download_queue = data.download
      current.send_queue = data.send
    } else if (event.type === 'napcat.updated') {
      current.napcat_connected = (event.data as NapcatUpdatedData).connected
    } else if (event.type === 'system.updated') {
      const data = event.data as SystemUpdatedData
      current.version = data.version
      current.uptime_seconds = data.uptime_seconds
      current.manga_count = data.manga_count
    }
  }

  return { status, loading, error, eventsConnected, refresh, applyEvent }
})
