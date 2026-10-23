import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createVuetify } from 'vuetify'

vi.mock('@/api/tasks', () => ({
  getDownloadProgress: vi.fn(),
  requestDownloads: vi.fn(),
}))
vi.mock('@/api/eventStream', () => ({
  useConnectionSubscription: vi.fn(),
  useEventSubscription: vi.fn(),
}))

import { useConnectionSubscription, useEventSubscription } from '@/api/eventStream'
import { getDownloadProgress, requestDownloads } from '@/api/tasks'
import DownloadPage from '@/pages/DownloadPage.vue'
import type { DownloadProgressSnapshot, EventEnvelope } from '@/types/api'

function snapshotFixture(
  overrides: Partial<DownloadProgressSnapshot> = {},
): DownloadProgressSnapshot {
  return {
    manga_id: '900001',
    task_id: 'task-1',
    album_id: '900001',
    album_total: 2,
    album_done: 1,
    chapters: [
      { photo_id: 'p1', done: 2, total: 2, finished: true },
      { photo_id: 'p2', done: 1, total: 2, finished: false },
    ],
    started_at: '2026-10-20T10:00:00',
    updated_at: '2026-10-20T10:00:05',
    finished: false,
    succeeded: false,
    ...overrides,
  }
}

function mountPage() {
  return mount(DownloadPage, {
    global: { plugins: [createVuetify()] },
  })
}

describe('DownloadPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getDownloadProgress).mockResolvedValue({ active: null })
  })

  it('无活动任务时显示空态', async () => {
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).toContain('当前没有正在下载的漫画')
    wrapper.unmount()
  })

  it('解析多个 ID、提交后清空输入并提示重复任务', async () => {
    vi.mocked(requestDownloads).mockResolvedValue({
      items: [
        { manga_id: '100', status: 'queued', task_id: 'task-1' },
        { manga_id: '200', status: 'duplicate', task_id: 'task-2' },
      ],
      queued_count: 1,
      duplicate_count: 1,
      skipped_blacklisted: [],
    })
    const wrapper = mountPage()
    await flushPromises()

    await wrapper.find('textarea').setValue('100，200 100')
    const submitButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('请求下载'))
    expect(submitButton).toBeDefined()
    await submitButton!.trigger('click')
    await flushPromises()

    expect(requestDownloads).toHaveBeenCalledWith(['100', '200'])
    expect(wrapper.text()).toContain('已提交 1 个，正在加入队列')
    expect(wrapper.text()).toContain('1 个已有活动任务（200）')
    expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('')
    wrapper.unmount()
  })

  it('提示因黑名单跳过的下载请求', async () => {
    vi.mocked(requestDownloads).mockResolvedValue({
      items: [{ manga_id: '200', status: 'queued', task_id: 'task-2' }],
      queued_count: 1,
      duplicate_count: 0,
      skipped_blacklisted: ['100'],
    })
    const wrapper = mountPage()
    await flushPromises()

    await wrapper.find('textarea').setValue('100, 200')
    const submitButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('请求下载'))
    await submitButton!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('1 个已被拉黑跳过（100）')
    wrapper.unmount()
  })

  it('挂载时恢复 REST 快照并渲染两级进度', async () => {
    vi.mocked(getDownloadProgress).mockResolvedValue({
      active: snapshotFixture(),
    })
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).toContain('本子-JM900001')
    expect(wrapper.text()).toContain('章节 1/2')
    expect(wrapper.text()).toContain('图片 3/4')
    expect(wrapper.text()).toContain('50%')
    expect(wrapper.text()).toContain('章节-JMp1')
    expect(wrapper.text()).toContain('章节-JMp2')
    expect(wrapper.text()).toContain('正在下载')
    wrapper.unmount()
  })

  it('WebSocket 重连后重新拉取进度快照', async () => {
    const wrapper = mountPage()
    await flushPromises()
    vi.mocked(getDownloadProgress).mockClear()
    const reconnectHandler = vi.mocked(useConnectionSubscription).mock.calls[0][0]

    reconnectHandler()
    await flushPromises()

    expect(getDownloadProgress).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('收到 finished 事件后显示下载完成并保留快照', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const handler = vi.mocked(useEventSubscription).mock.calls[0][0]
    const event: EventEnvelope = {
      type: 'download.progress',
      occurred_at: '2026-10-20T10:00:05Z',
      data: {
        ...snapshotFixture({
          album_done: 2,
          chapters: [
            { photo_id: 'p1', done: 2, total: 2, finished: true },
            { photo_id: 'p2', done: 2, total: 2, finished: true },
          ],
          finished: true,
          succeeded: true,
        }),
        phase: 'finished',
      },
    }

    handler(event)
    await nextTick()

    expect(wrapper.text()).toContain('下载完成')
    expect(wrapper.text()).toContain('章节 2/2')
    expect(wrapper.text()).toContain('图片 4/4')
    wrapper.unmount()
  })
})
