import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createVuetify } from 'vuetify'

vi.mock('@/api/tasks', () => ({
  listTasks: vi.fn(),
  cancelTask: vi.fn(),
  cancelTasks: vi.fn(),
  cancelQueuedTasks: vi.fn(),
  retryTasks: vi.fn(),
  pauseDownloadQueue: vi.fn(),
  resumeDownloadQueue: vi.fn(),
}))
vi.mock('@/api/eventStream', () => ({
  useEventSubscription: vi.fn(),
}))

import { listTasks, pauseDownloadQueue, resumeDownloadQueue } from '@/api/tasks'
import TasksPage from '@/pages/TasksPage.vue'
import { useSystemStore } from '@/stores/system'
import type { SystemStatus } from '@/types/api'

function statusFixture(paused: boolean): SystemStatus {
  return {
    version: 'test',
    uptime_seconds: 10,
    napcat_connected: true,
    manga_count: 1,
    total_size_bytes: 100,
    download_queue: { running: true, paused, queue_size: 1 },
    send_queue: { running: true, queue_size: 0 },
  }
}

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/tasks', name: 'tasks', component: TasksPage },
      {
        path: '/library/:mangaId',
        name: 'manga-detail',
        component: { template: '<div />' },
      },
    ],
  })
  await router.push('/tasks')
  await router.isReady()
  const pinia = createPinia()
  setActivePinia(pinia)
  const system = useSystemStore()
  system.status = statusFixture(false)
  const wrapper = mount(TasksPage, {
    global: { plugins: [pinia, router, createVuetify()] },
  })
  await flushPromises()
  return { wrapper, system }
}

describe('TasksPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(listTasks).mockResolvedValue({
      items: [],
      page: 1,
      page_size: 20,
      total: 0,
      pages: 0,
    })
  })

  it('暂停后切换为恢复按钮并更新队列状态', async () => {
    vi.mocked(pauseDownloadQueue).mockResolvedValue({ paused: true, changed: true })
    const { wrapper, system } = await mountPage()

    const pauseButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('暂停队列'))
    expect(pauseButton).toBeDefined()
    await pauseButton!.trigger('click')
    await flushPromises()

    expect(pauseDownloadQueue).toHaveBeenCalledTimes(1)
    expect(system.status?.download_queue.paused).toBe(true)
    expect(wrapper.text()).toContain('恢复队列')
    expect(wrapper.text()).toContain('队列已暂停，当前任务完成后停止取新任务')
    wrapper.unmount()
  })

  it('暂停状态下点击恢复并更新队列状态', async () => {
    vi.mocked(resumeDownloadQueue).mockResolvedValue({
      paused: false,
      changed: true,
    })
    const { wrapper, system } = await mountPage()
    system.status!.download_queue.paused = true
    await wrapper.vm.$nextTick()

    const resumeButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('恢复队列'))
    expect(resumeButton).toBeDefined()
    await resumeButton!.trigger('click')
    await flushPromises()

    expect(resumeDownloadQueue).toHaveBeenCalledTimes(1)
    expect(system.status?.download_queue.paused).toBe(false)
    expect(wrapper.text()).toContain('暂停队列')
    wrapper.unmount()
  })
})
