/** 阅读进度同步：防抖、flush、失败标记与重试。 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createProgressSync,
  type ProgressSync,
  type ProgressSyncState,
} from './progressSync'

describe('createProgressSync', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  let states: ProgressSyncState[]
  let page: number

  function build(debounceMs = 1000): ProgressSync {
    return createProgressSync({
      fileId: 7,
      getPage: () => page,
      getPageCount: () => 20,
      onStateChange: (state) => states.push(state),
      debounceMs,
    })
  }

  beforeEach(() => {
    vi.useFakeTimers()
    document.cookie = 'jmbot_csrf=csrf-token'
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    states = []
    page = 1
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    document.cookie = 'jmbot_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT'
  })

  it('防抖窗口内多次调度只发送一次，并携带 CSRF 与最新页码', async () => {
    fetchMock.mockResolvedValue({ ok: true })
    const sync = build()
    sync.schedule()
    page = 2
    sync.schedule()
    expect(fetchMock).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(1000)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/files/7/progress')
    expect(options.method).toBe('PUT')
    expect(options.keepalive).toBe(false)
    expect(options.headers['X-CSRF-Token']).toBe('csrf-token')
    expect(JSON.parse(options.body)).toEqual({ page_number: 2, page_count: 20 })
    expect(states).toContain('pending')
    expect(states[states.length - 1]).toBe('synced')
  })

  it('flush 使用 keepalive 立即发送；无新变化时不重复发送', async () => {
    fetchMock.mockResolvedValue({ ok: true })
    const sync = build()
    page = 3
    sync.schedule()
    expect(await sync.flush(true)).toBe(true)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [, options] = fetchMock.mock.calls[0]
    expect(options.keepalive).toBe(true)
    expect(JSON.parse(options.body).page_number).toBe(3)

    expect(await sync.flush(true)).toBe(true)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('网络失败标记 failed，重试成功后回到 synced', async () => {
    fetchMock.mockRejectedValueOnce(new Error('network down'))
    const sync = build()
    sync.schedule()
    await vi.advanceTimersByTimeAsync(1000)
    expect(states[states.length - 1]).toBe('failed')

    fetchMock.mockResolvedValueOnce({ ok: true })
    expect(await sync.retry()).toBe(true)
    expect(states[states.length - 1]).toBe('synced')
  })

  it('HTTP 非 2xx 视为失败，失败后 flush 仍会重发', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 400 })
    const sync = build()
    sync.schedule()
    await vi.advanceTimersByTimeAsync(1000)
    expect(states[states.length - 1]).toBe('failed')

    fetchMock.mockResolvedValueOnce({ ok: true })
    await sync.flush(true)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(states[states.length - 1]).toBe('synced')
  })

  it('dispose 后不再调度发送', async () => {
    fetchMock.mockResolvedValue({ ok: true })
    const sync = build()
    sync.dispose()
    sync.schedule()
    await vi.advanceTimersByTimeAsync(2000)
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
