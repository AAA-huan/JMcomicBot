import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/system', () => ({
  getSystemStatus: vi.fn(),
  reconnectNapcat: vi.fn(),
  requestShutdown: vi.fn(),
}))

import { getSystemStatus } from '@/api/system'
import { useSystemStore } from '@/stores/system'
import type { SystemStatus } from '@/types/api'

const statusFixture: SystemStatus = {
  version: '0.1.0',
  uptime_seconds: 120,
  napcat_connected: true,
  manga_count: 3,
  download_queue: { running: true, queue_size: 1 },
  send_queue: { running: false, queue_size: 0 },
}

describe('system store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('refresh 拉取系统状态', async () => {
    vi.mocked(getSystemStatus).mockResolvedValue(statusFixture)
    const store = useSystemStore()

    await store.refresh()

    expect(store.status?.version).toBe('0.1.0')
    expect(store.status?.manga_count).toBe(3)
    expect(store.error).toBe('')
  })

  it('refresh 失败时记录中文错误且不抛出', async () => {
    vi.mocked(getSystemStatus).mockRejectedValue(new Error('Failed to fetch'))
    const store = useSystemStore()

    await store.refresh()

    expect(store.status).toBeNull()
    expect(store.error).toContain('网络请求失败')
  })

  it('无快照时忽略事件，有快照时增量更新', async () => {
    vi.mocked(getSystemStatus).mockResolvedValue(statusFixture)
    const store = useSystemStore()

    store.applyEvent({
      type: 'napcat.updated',
      occurred_at: '2026-10-01T00:00:00Z',
      data: { connected: false },
    })
    expect(store.status).toBeNull()

    await store.refresh()
    store.applyEvent({
      type: 'queue.updated',
      occurred_at: '2026-10-01T00:00:00Z',
      data: {
        download: { running: false, queue_size: 0 },
        send: { running: true, queue_size: 4, current_file: '第 3 章.pdf' },
      },
    })
    store.applyEvent({
      type: 'system.updated',
      occurred_at: '2026-10-01T00:00:00Z',
      data: { version: '0.2.0', uptime_seconds: 300, manga_count: 5 },
    })

    expect(store.status?.download_queue.queue_size).toBe(0)
    expect(store.status?.send_queue.current_file).toBe('第 3 章.pdf')
    expect(store.status?.version).toBe('0.2.0')
    expect(store.status?.manga_count).toBe(5)
  })
})
