import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createVuetify } from 'vuetify'

vi.mock('@/api/mangas', () => ({
  listMangas: vi.fn(),
  deleteManga: vi.fn(),
  batchDeleteMangas: vi.fn(),
}))
vi.mock('@/api/favorites', () => ({ setFavorite: vi.fn() }))
vi.mock('@/api/tasks', () => ({
  requestDownloads: vi.fn(),
}))

import { listMangas } from '@/api/mangas'
import { setFavorite } from '@/api/favorites'
import { ApiError } from '@/api/client'
import LibraryPage from '@/pages/LibraryPage.vue'
import type { Manga } from '@/types/api'

function mangaFixture(id: string, title: string): Manga {
  return {
    id,
    title,
    is_favorite: false,
    author: '作者',
    description: null,
    chapter_count: 3,
    page_count: 60,
    status: 'downloaded',
    downloaded_at: '2026-10-01T00:00:00',
    updated_at: '2026-10-01T00:00:00',
    tags: ['标签'],
    files: [
      {
        id: Number(id),
        display_name: `${title}.pdf`,
        file_size_bytes: 1024,
        page_count: 10,
        status: 'ready',
      },
    ],
  }
}

async function mountPage(initialPath = '/library') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/library', name: 'library', component: LibraryPage },
      {
        path: '/library/:mangaId',
        name: 'manga-detail',
        component: { template: '<div />' },
      },
      { path: '/tasks', name: 'tasks', component: { template: '<div />' } },
    ],
  })
  await router.push(initialPath)
  await router.isReady()
  const wrapper = mount(LibraryPage, {
    global: {
      plugins: [createPinia(), router, createVuetify()],
    },
  })
  await flushPromises()
  return { wrapper, router }
}

describe('LibraryPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('渲染分页结果与总数', async () => {
    vi.mocked(listMangas).mockResolvedValue({
      items: [mangaFixture('100', '测试漫画'), mangaFixture('200', '第二本')],
      page: 1,
      page_size: 20,
      total: 2,
      pages: 1,
    })

    const { wrapper } = await mountPage()

    expect(listMangas).toHaveBeenCalledWith(
      expect.objectContaining({
        page: 1,
        page_size: 20,
        sort: 'downloaded_at_desc',
      }),
    )
    expect(wrapper.text()).toContain('测试漫画')
    expect(wrapper.text()).toContain('共 2 条')
    // 行内下载按钮指向 PDF 文件接口，而不是重新创建下载任务
    expect(
      wrapper.find('a[href="/api/v1/files/100/content"]').exists(),
    ).toBe(true)
    expect(
      wrapper.find('a[href="/api/v1/files/200/content"]').exists(),
    ).toBe(true)
  })

  it('加载失败展示中文错误与重试入口', async () => {
    vi.mocked(listMangas).mockRejectedValue(new Error('Failed to fetch'))

    const { wrapper } = await mountPage()

    expect(wrapper.text()).toContain('网络请求失败')
    expect(wrapper.text()).toContain('重试')
  })

  it('空结果显示空状态', async () => {
    vi.mocked(listMangas).mockResolvedValue({
      items: [],
      page: 1,
      page_size: 20,
      total: 0,
      pages: 0,
    })

    const { wrapper } = await mountPage()

    expect(wrapper.text()).toContain('没有找到漫画')
  })

  it('按标签范围搜索时以 tag 参数请求', async () => {
    vi.mocked(listMangas).mockResolvedValue({
      items: [],
      page: 1,
      page_size: 20,
      total: 0,
      pages: 0,
    })

    await mountPage('/library?tag=恋爱&scope=tag')

    expect(listMangas).toHaveBeenCalledWith(
      expect.objectContaining({ tag: '恋爱', search: undefined }),
    )
  })

  it('详情链接保留当前筛选参数', async () => {
    vi.mocked(listMangas).mockResolvedValue({
      items: [mangaFixture('100', '测试漫画')],
      page: 1,
      page_size: 20,
      total: 1,
      pages: 1,
    })

    const { wrapper } = await mountPage('/library?status=downloaded&sort=id_asc')
    const detailLink = wrapper.find('a[href*="/library/100"]')

    expect(detailLink.exists()).toBe(true)
    expect(detailLink.attributes('href')).toContain('status=downloaded')
    expect(detailLink.attributes('href')).toContain('sort=id_asc')
  })

  it('收藏成功切换按钮，失败保留原状态，取消后切回收藏', async () => {
    vi.mocked(listMangas).mockResolvedValue({
      items: [mangaFixture('100', '测试漫画')], page: 1, page_size: 20, total: 1, pages: 1,
    })
    vi.mocked(setFavorite).mockRejectedValueOnce(new ApiError(500, 'SAVE_FAILED', '收藏保存失败'))
    const { wrapper } = await mountPage()
    await wrapper.find('[aria-label="收藏"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('收藏保存失败')
    expect(wrapper.find('[aria-label="收藏"]').exists()).toBe(true)
    vi.mocked(setFavorite).mockResolvedValueOnce({ manga_id: '100', is_favorite: true, changed: true })
    await wrapper.find('[aria-label="收藏"]').trigger('click')
    await flushPromises()
    expect(setFavorite).toHaveBeenLastCalledWith('100', true)
    expect(wrapper.find('[aria-label="取消收藏"]').attributes('aria-pressed')).toBe('true')
    vi.mocked(setFavorite).mockResolvedValueOnce({ manga_id: '100', is_favorite: false, changed: true })
    await wrapper.find('[aria-label="取消收藏"]').trigger('click')
    await flushPromises()
    expect(setFavorite).toHaveBeenLastCalledWith('100', false)
    expect(wrapper.find('[aria-label="收藏"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('恢复收藏筛选并在取消收藏后重新请求当前列表', async () => {
    const manga = { ...mangaFixture('100', '测试漫画'), is_favorite: true }
    vi.mocked(listMangas).mockResolvedValueOnce({ items: [manga], page: 1, page_size: 20, total: 1, pages: 1 })
    vi.mocked(listMangas).mockResolvedValue({ items: [], page: 1, page_size: 20, total: 0, pages: 0 })
    vi.mocked(setFavorite).mockResolvedValue({ manga_id: '100', is_favorite: false, changed: true })
    const { wrapper } = await mountPage('/library?favorite_only=true&sort=id_asc')
    expect(listMangas).toHaveBeenCalledWith(expect.objectContaining({ favorite_only: true, sort: 'id_asc' }))
    await wrapper.find('[aria-label="取消收藏"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('没有找到漫画')
    expect(listMangas).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

})
