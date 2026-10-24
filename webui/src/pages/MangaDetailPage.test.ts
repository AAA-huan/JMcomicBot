/** 漫画详情页：操作按钮在手机宽度下的对齐与尺寸。 */

import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { createVuetify } from 'vuetify'
import { VBtn } from 'vuetify/components'

vi.mock('vue-router', () => ({
  useRoute: () => ({
    params: { mangaId: '100' },
    query: {},
    fullPath: '/library/100',
  }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))
vi.mock('@/api/files', () => ({
  fileDownloadUrl: (fileId: number) => `/api/v1/files/${fileId}/content`,
  getReadingProgress: vi.fn(),
}))
vi.mock('@/api/mangas', () => ({
  deleteManga: vi.fn(),
  getManga: vi.fn(),
  patchManga: vi.fn(),
}))
vi.mock('@/api/tasks', () => ({
  requestDownloads: vi.fn(),
}))

import { getReadingProgress } from '@/api/files'
import { getManga } from '@/api/mangas'
import MangaDetailPage from '@/pages/MangaDetailPage.vue'
import type { Manga } from '@/types/api'

function mangaFixture(): Manga {
  return {
    id: '100',
    title: '测试漫画',
    author: '作者',
    description: null,
    chapter_count: 1,
    page_count: 20,
    status: 'downloaded',
    downloaded_at: '2026-10-01T00:00:00',
    updated_at: '2026-10-01T00:00:00',
    tags: ['标签'],
    is_favorite: false,
    is_blacklisted: false,
    files: [
      {
        id: 1,
        display_name: '测试漫画.pdf',
        file_size_bytes: 1024,
        page_count: 20,
        status: 'ready',
      },
    ],
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  document.body.innerHTML = ''
  window.localStorage.clear()
  vi.mocked(getManga).mockResolvedValue(mangaFixture())
  vi.mocked(getReadingProgress).mockResolvedValue({
    file_id: 1,
    page_number: 1,
    page_count: 20,
    percent: 0,
    updated_at: null,
  })
})

it('操作按钮无前置空白，小尺寸平铺并保留换行兜底', async () => {
  const wrapper = mount(MangaDetailPage, {
    attachTo: document.body,
    global: { plugins: [createVuetify()] },
  })
  await flushPromises()

  const actions = wrapper.find('.v-card-actions')
  expect(actions.exists()).toBe(true)
  expect(actions.classes()).toEqual(
    expect.arrayContaining(['d-flex', 'flex-wrap', 'ga-2']),
  )
  // 去掉 spacer 后第一个子元素就是「编辑元数据」，不再被推到右侧
  expect(actions.find('.v-spacer').exists()).toBe(false)
  expect(actions.element.firstElementChild?.textContent?.trim()).toBe(
    '编辑元数据',
  )

  const buttons = actions.findAllComponents(VBtn)
  expect(buttons).toHaveLength(3)
  expect(buttons[0].text()).toBe('编辑元数据')
  expect(buttons[1].text()).toBe('请求下载')
  expect(buttons[2].text()).toBe('删除漫画')
  for (const button of buttons) {
    expect(button.props('size')).toBe('small')
    expect(button.props('density')).toBe('comfortable')
  }
  // flex-wrap 保留为极窄屏兜底，正常手机宽度下由 small 尺寸保证一行
  expect(actions.classes()).toContain('flex-wrap')
  wrapper.unmount()
})
