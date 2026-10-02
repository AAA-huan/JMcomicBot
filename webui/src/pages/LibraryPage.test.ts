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
vi.mock('@/api/tasks', () => ({
  requestDownloads: vi.fn(),
}))

import { listMangas } from '@/api/mangas'
import LibraryPage from '@/pages/LibraryPage.vue'
import type { Manga } from '@/types/api'

function mangaFixture(id: string, title: string): Manga {
  return {
    id,
    title,
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
})
