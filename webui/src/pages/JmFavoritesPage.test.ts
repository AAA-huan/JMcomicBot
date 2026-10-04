import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createVuetify } from 'vuetify'

vi.mock('@/api/jmFavorites', () => ({
  getJmAccount: vi.fn(), getJmImport: vi.fn(), listJmFavorites: vi.fn(), listJmImports: vi.fn(),
  loginJmAccount: vi.fn(), logoutJmAccount: vi.fn(), requestJmDownloads: vi.fn(), startJmImport: vi.fn(),
}))

import {
  getJmAccount, getJmImport, listJmFavorites, listJmImports, loginJmAccount,
  logoutJmAccount, requestJmDownloads, startJmImport,
} from '@/api/jmFavorites'
import type { JmImport } from '@/api/jmFavorites'
import JmFavoritesPage from './JmFavoritesPage.vue'

const account = { connected: true, username: 'user', total: 2, expires_at: '2026-10-04T12:00:00', folders: [{ id: '0', name: '全部收藏' }, { id: '7', name: '精选' }] }
const job: JmImport = { id: 'job', username: 'user', folder_ids: ['0'], status: 'running', pages_done: 0, imported_count: 0, duplicate_count: 0, local_count: 0, error_message: null, created_at: '', updated_at: '' }

async function mountPage() {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/jm-favorites', component: JmFavoritesPage },
    { path: '/library/:id?', component: { template: '<div>漫画库</div>' } },
    { path: '/tasks', component: { template: '<div>任务</div>' } },
  ] })
  await router.push('/jm-favorites')
  await router.isReady()
  const wrapper = mount(JmFavoritesPage, { global: { plugins: [router, createVuetify()] } })
  await flushPromises()
  return wrapper
}

describe('JM 收藏导入页', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getJmAccount).mockResolvedValue({ connected: false })
    vi.mocked(listJmImports).mockResolvedValue({ items: [] })
    vi.mocked(listJmFavorites).mockResolvedValue({
      items: [
        { manga_id: '100', title: '未下载漫画', username: 'user', folders: { '7': '精选' }, downloaded: false, file_id: null, imported_at: '' },
        { manga_id: '200', title: '本地漫画', username: 'user', folders: { '7': '精选' }, downloaded: true, file_id: 1, imported_at: '' },
      ], total: 2, page: 1, page_size: 20, pages: 1,
    })
    vi.mocked(loginJmAccount).mockResolvedValue(account)
    vi.mocked(logoutJmAccount).mockResolvedValue({ connected: false })
    vi.mocked(requestJmDownloads).mockResolvedValue({ items: [], queued_count: 1, duplicate_count: 0 })
    vi.mocked(startJmImport).mockResolvedValue(job)
  })

  afterEach(() => { vi.useRealTimers() })

  it('未登录 JM 仍可查看历史导入，只有未下载漫画可选择下载', async () => {
    const wrapper = await mountPage()
    expect(wrapper.text()).toContain('未下载漫画')
    expect(wrapper.findAll('input[type="checkbox"]')).toHaveLength(1)
    await wrapper.find('input[type="checkbox"]').setValue(true)
    await wrapper.find('[data-testid="jm-download"]').trigger('click')
    await flushPromises()
    expect(requestJmDownloads).toHaveBeenCalledWith(['100'])
    expect(wrapper.text()).toContain('已加入下载队列 1 本')
    wrapper.unmount()
  })

  it('登录后显示收藏夹，退出后清空密码且保留已导入列表', async () => {
    const wrapper = await mountPage()
    await wrapper.find('input[autocomplete="off"]').setValue('user')
    await wrapper.find('input[type="password"]').setValue('secret')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(loginJmAccount).toHaveBeenCalledWith('user', 'secret')
    expect(wrapper.text()).toContain('已登录：user')
    const logout = wrapper.findAll('button').find((button) => button.text() === '退出 JM 账号')!
    await logout.trigger('click')
    await flushPromises()
    expect(logoutJmAccount).toHaveBeenCalledOnce()
    expect((wrapper.find('input[type="password"]').element as HTMLInputElement).value).toBe('')
    expect(wrapper.text()).toContain('未下载漫画')
    wrapper.unmount()
  })

  it('后台导入轮询进度，失败时保留导入结果并显示原因', async () => {
    vi.useFakeTimers()
    vi.mocked(getJmAccount).mockResolvedValue(account)
    vi.mocked(getJmImport).mockResolvedValue({ ...job, status: 'failed', pages_done: 1, imported_count: 1, error_message: '第二页读取失败，已完成页保留' })
    const wrapper = await mountPage()
    await wrapper.find('[data-testid="jm-import"]').trigger('click')
    await flushPromises()
    expect(startJmImport).toHaveBeenCalledWith(['0'])
    expect(wrapper.text()).toContain('导入中')
    await vi.advanceTimersByTimeAsync(1500)
    await flushPromises()
    expect(getJmImport).toHaveBeenCalledWith('job')
    expect(wrapper.text()).toContain('第二页读取失败')
    expect(listJmFavorites).toHaveBeenCalledTimes(2)
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(5000)
    expect(getJmImport).toHaveBeenCalledOnce()
  })

  it('登录错误展示且不保留输入的密码', async () => {
    vi.mocked(loginJmAccount).mockRejectedValue(new Error('连接失败'))
    const wrapper = await mountPage()
    await wrapper.find('input[autocomplete="off"]').setValue('user')
    await wrapper.find('input[type="password"]').setValue('secret')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('连接失败')
    expect((wrapper.find('input[type="password"]').element as HTMLInputElement).value).toBe('')
    wrapper.unmount()
  })

  it('再次进入页面继续轮询正在运行的导入，不自动下载漫画', async () => {
    vi.useFakeTimers()
    vi.mocked(listJmImports).mockResolvedValue({ items: [job] })
    vi.mocked(getJmImport).mockResolvedValue({ ...job, pages_done: 2 })
    const wrapper = await mountPage()
    await vi.advanceTimersByTimeAsync(1500)
    await flushPromises()
    expect(wrapper.text()).toContain('已处理 2 页')
    expect(requestJmDownloads).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
