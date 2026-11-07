/** 漫画详情页：操作按钮在手机宽度下的对齐与尺寸。 */

import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { createVuetify } from 'vuetify'
import { VBtn } from 'vuetify/components'

const routerMocks = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
}))
vi.mock('vue-router', () => ({
  useRoute: () => ({
    params: { mangaId: '100' },
    query: {},
    fullPath: '/library/100',
  }),
  useRouter: () => routerMocks,
}))
vi.mock('@/api/files', () => ({
  fileDownloadUrl: (fileId: number) => `/api/v1/files/${fileId}/content`,
  getReadingProgress: vi.fn(),
}))
vi.mock('@/api/favorites', () => ({
  setFavorite: vi.fn(),
}))
vi.mock('@/api/mangas', () => ({
  blacklistManga: vi.fn(),
  deleteManga: vi.fn(),
  getManga: vi.fn(),
  patchManga: vi.fn(),
  unblacklistManga: vi.fn(),
}))
vi.mock('@/api/folders', () => ({
  listFolders: vi.fn(),
  createFolder: vi.fn(),
  addFolderMangas: vi.fn(),
  removeFolderMangas: vi.fn(),
}))
vi.mock('@/api/tasks', () => ({
  requestDownloads: vi.fn(),
}))

import { getReadingProgress } from '@/api/files'
import { setFavorite } from '@/api/favorites'
import { addFolderMangas, listFolders, removeFolderMangas } from '@/api/folders'
import { blacklistManga, getManga } from '@/api/mangas'
import MangaDetailPage from '@/pages/MangaDetailPage.vue'
import { useToast } from '@/stores/toast'
import type { Manga } from '@/types/api'

/** 当前展示中的 toast 文案列表。 */
function toastMessages(): string[] {
  return useToast().visible.value.map((item) => item.message)
}

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
  useToast().clear()
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
  // 拉黑之后新增「加入文件夹」菜单按钮
  expect(buttons).toHaveLength(7)
  expect(buttons[0].text()).toBe('编辑元数据')
  expect(buttons[1].text()).toBe('查询同作者')
  expect(buttons[2].text()).toBe('请求下载')
  expect(buttons[3].text()).toBe('收藏')
  expect(buttons[4].text()).toBe('拉黑')
  expect(buttons[5].text()).toBe('加入文件夹')
  expect(buttons[6].text()).toBe('删除漫画')
  for (const button of buttons) {
    expect(button.props('size')).toBe('small')
    expect(button.props('density')).toBe('comfortable')
  }
  // flex-wrap 保留为极窄屏兜底，正常手机宽度下由 small 尺寸保证一行
  expect(actions.classes()).toContain('flex-wrap')
  wrapper.unmount()
})

it('查询同作者按钮携带作者和来源漫画跳转', async () => {
  const wrapper = mount(MangaDetailPage, {
    attachTo: document.body,
    global: { plugins: [createVuetify()] },
  })
  await flushPromises()

  const button = wrapper
    .findAllComponents(VBtn)
    .find((item) => item.text() === '查询同作者')!
  expect(button.props('disabled')).toBe(false)
  await button.trigger('click')

  expect(routerMocks.push).toHaveBeenCalledWith({
    name: 'author-search',
    query: { author: '作者', from: '100' },
  })
  wrapper.unmount()
})

it('作者为空时禁用查询同作者按钮', async () => {
  vi.mocked(getManga).mockResolvedValue({ ...mangaFixture(), author: '' })
  const wrapper = mount(MangaDetailPage, {
    attachTo: document.body,
    global: { plugins: [createVuetify()] },
  })
  await flushPromises()

  const button = wrapper
    .findAllComponents(VBtn)
    .find((item) => item.text() === '查询同作者')!
  expect(button.props('disabled')).toBe(true)
  await button.trigger('click')
  expect(routerMocks.push).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('收藏按钮调用收藏接口并更新按钮状态', async () => {
  vi.mocked(setFavorite).mockResolvedValue({
    manga_id: '100',
    is_favorite: true,
    changed: true,
  })
  const wrapper = mount(MangaDetailPage, {
    attachTo: document.body,
    global: { plugins: [createVuetify()] },
  })
  await flushPromises()

  const button = wrapper
    .findAllComponents(VBtn)
    .find((item) => item.text() === '收藏')!
  await button.trigger('click')
  await flushPromises()

  expect(setFavorite).toHaveBeenCalledWith('100', true)
  expect(toastMessages()).toContain('已收藏《测试漫画》')
  expect(wrapper.text()).toContain('取消收藏')
  wrapper.unmount()
})

it('拉黑按钮先弹出确认对话框', async () => {
  const wrapper = mount(MangaDetailPage, {
    attachTo: document.body,
    global: { plugins: [createVuetify()] },
  })
  await flushPromises()

  const button = wrapper
    .findAllComponents(VBtn)
    .find((item) => item.text() === '拉黑')!
  await button.trigger('click')
  await flushPromises()

  expect(blacklistManga).not.toHaveBeenCalled()
  const confirm = Array.from(document.querySelectorAll('button'))
    .find((item) => item.textContent?.trim() === '确认拉黑')
  expect(confirm).toBeTruthy()
  wrapper.unmount()
})

/** 点击菜单内文本匹配的列表项（菜单内容会被 teleport 到 body）。 */
function clickDocumentItem(text: string): void {
  const item = Array.from(document.querySelectorAll('.v-list-item')).find(
    (element) => element.textContent?.includes(text),
  )
  expect(item).toBeTruthy()
  item!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
}

it('加入文件夹菜单打开时拉取清单，勾选加入与取消移出', async () => {
  vi.mocked(listFolders).mockResolvedValue([
    {
      id: 7,
      name: '追更',
      sort_order: 0,
      manga_count: 1,
      created_at: '2026-10-01T00:00:00',
      updated_at: '2026-10-01T00:00:00',
    },
    {
      id: 8,
      name: '待补',
      sort_order: 0,
      manga_count: 0,
      created_at: '2026-10-01T00:00:00',
      updated_at: '2026-10-01T00:00:00',
    },
  ])
  vi.mocked(addFolderMangas).mockResolvedValue({
    folder_id: 8,
    added: ['100'],
    unchanged_count: 0,
  })
  vi.mocked(removeFolderMangas).mockResolvedValue({ folder_id: 7, removed_count: 1 })
  vi.mocked(getManga).mockResolvedValue({ ...mangaFixture(), folder_ids: [7] })

  const wrapper = mount(MangaDetailPage, {
    attachTo: document.body,
    global: { plugins: [createVuetify()] },
  })
  await flushPromises()

  const button = wrapper
    .findAllComponents(VBtn)
    .find((item) => item.text() === '加入文件夹')!
  await button.trigger('click')
  await flushPromises()
  expect(listFolders).toHaveBeenCalled()

  clickDocumentItem('待补')
  await flushPromises()
  expect(addFolderMangas).toHaveBeenCalledWith(8, ['100'])
  expect(toastMessages()).toContain('已加入文件夹「待补」')

  clickDocumentItem('追更')
  await flushPromises()
  expect(removeFolderMangas).toHaveBeenCalledWith(7, ['100'])
  expect(toastMessages()).toContain('已移出文件夹「追更」')
  wrapper.unmount()
})
