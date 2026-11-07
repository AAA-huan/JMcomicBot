import { flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createVuetify } from 'vuetify'

vi.mock('@/api/jmSearch', () => ({
  searchAuthorByAuthor: vi.fn(),
  getJmAlbumDetail: vi.fn(),
  favoriteJmAlbums: vi.fn(),
}))
vi.mock('@/api/tasks', () => ({
  requestDownloads: vi.fn(),
}))
vi.mock('@/utils/clipboard', () => ({
  copyText: vi.fn(),
}))

import { ApiError } from '@/api/client'
import {
  favoriteJmAlbums,
  getJmAlbumDetail,
  searchAuthorByAuthor,
} from '@/api/jmSearch'
import type {
  JmAlbumDetail,
  JmAuthorSearchResult,
  JmLocalStatus,
  JmSearchAlbum,
} from '@/api/jmSearch'
import { requestDownloads } from '@/api/tasks'
import AuthorSearchPage from '@/pages/AuthorSearchPage.vue'
import { useToast } from '@/stores/toast'
import { copyText } from '@/utils/clipboard'

const toast = useToast()

/** 当前展示中的 toast 文案列表。 */
function toastMessages(): string[] {
  return toast.visible.value.map((item) => item.message)
}

function localStatus(overrides: Partial<JmLocalStatus> = {}): JmLocalStatus {
  return { exists: false, status: null, favorited: false, downloaded: false, ...overrides }
}

const albums: JmSearchAlbum[] = [
  {
    album_id: '100',
    title: '漫画一',
    author: '测试作者',
    tags: ['恋爱'],
    local: localStatus(),
  },
  {
    album_id: '200',
    title: '漫画二',
    author: '测试作者',
    tags: [],
    local: localStatus(),
  },
]

const detail: JmAlbumDetail = {
  album_id: '100',
  title: '漫画一',
  author: '测试作者',
  tags: ['恋爱', '校园'],
  page_count: 88,
  chapter_ids: ['1001', '1002'],
  local: localStatus(),
}

function searchResult(
  overrides: Partial<JmAuthorSearchResult> = {},
): JmAuthorSearchResult {
  return {
    results: albums,
    page: 1,
    page_count: 2,
    page_size: 20,
    total: 40,
    ...overrides,
  }
}

async function mountPage(
  initialPath = '/search-author?author=测试作者&from=100',
  mobile = false,
) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/search-author', name: 'author-search', component: AuthorSearchPage },
      {
        path: '/library/:mangaId',
        name: 'manga-detail',
        component: { template: '<div />' },
      },
    ],
  })
  await router.push(initialPath)
  await router.isReady()
  const wrapper = mount(AuthorSearchPage, {
    attachTo: document.body,
    global: {
      plugins: [
        router,
        createVuetify({
          display: { mobileBreakpoint: mobile ? 'lg' : 'sm' },
        }),
      ],
    },
  })
  await flushPromises()
  return { wrapper, router }
}

function buttonWithText(wrapper: VueWrapper, text: string) {
  return wrapper.findAll('button').find((button) => button.text() === text)!
}

describe('AuthorSearchPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    toast.clear()
    document.body.innerHTML = ''
    // 列表对象会被收藏操作原地更新，每个用例开始前恢复初始本地状态
    for (const album of albums) album.local = localStatus()
    detail.local = localStatus()
    vi.mocked(searchAuthorByAuthor).mockResolvedValue(searchResult())
    vi.mocked(getJmAlbumDetail).mockResolvedValue(detail)
    vi.mocked(favoriteJmAlbums).mockResolvedValue({
      collected_count: 1,
      already_count: 0,
      failed: [],
    })
    vi.mocked(requestDownloads).mockResolvedValue({
      items: [],
      queued_count: 1,
      duplicate_count: 0,
      skipped_blacklisted: [],
      skipped_downloaded: [],
    })
    vi.mocked(copyText).mockResolvedValue(true)
  })

  it('展示查询作者、来源漫画与最简列表', async () => {
    const { wrapper } = await mountPage()

    expect(searchAuthorByAuthor).toHaveBeenCalledWith('测试作者', 1)
    expect(wrapper.text()).toContain('查询作者：测试作者')
    expect(wrapper.text()).toContain('来自漫画 ID 100')
    expect(wrapper.text()).toContain('漫画一')
    expect(wrapper.text()).toContain('漫画二')
    expect(wrapper.text()).toContain('100')
    expect(wrapper.text()).toContain('恋爱')
    expect(wrapper.findAll('tbody tr')).toHaveLength(2)
    expect(wrapper.text()).toContain('全选')
    expect(wrapper.text()).toContain('下载选中')
    expect(wrapper.text()).toContain('复制 ID')
    expect(wrapper.text()).not.toContain('批量删除')
    expect(wrapper.text()).not.toContain('批量拉黑')
    expect(wrapper.find('.pagination-size').exists()).toBe(false)
    wrapper.unmount()
  })

  it('全选后批量下载并复制选中 ID', async () => {
    const { wrapper } = await mountPage()

    await buttonWithText(wrapper, '全选').trigger('click')
    expect(wrapper.text()).toContain('已选 2 部')

    await buttonWithText(wrapper, '下载选中').trigger('click')
    await flushPromises()
    expect(requestDownloads).toHaveBeenCalledWith(['100', '200'])
    expect(toastMessages().join('')).toContain('已提交 1 个，正在加入队列')

    await buttonWithText(wrapper, '全选').trigger('click')
    await buttonWithText(wrapper, '复制 ID').trigger('click')
    await flushPromises()
    expect(copyText).toHaveBeenCalledWith('100,200')
    expect(toastMessages().join('')).toContain('已复制 2 个漫画 ID')
    wrapper.unmount()
  })

  it('移动端使用列表展示并保留下载与详情入口', async () => {
    const { wrapper } = await mountPage(
      '/search-author?author=测试作者&from=100',
      true,
    )

    expect(wrapper.find('.v-table').exists()).toBe(false)
    expect(wrapper.findAll('.v-list-item')).toHaveLength(2)
    expect(wrapper.find('[aria-label="下载 漫画一"]').exists()).toBe(true)
    expect(wrapper.find('[aria-label="查看 漫画一 的详情"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('单行下载只提交当前漫画 ID', async () => {
    const { wrapper } = await mountPage()

    await wrapper.find('[aria-label="下载 漫画一"]').trigger('click')
    await flushPromises()

    expect(requestDownloads).toHaveBeenCalledWith(['100'])
    wrapper.unmount()
  })

  it('翻页调用对应页码并渲染新结果', async () => {
    const { wrapper } = await mountPage()
    vi.mocked(searchAuthorByAuthor).mockResolvedValueOnce(
      searchResult({
        page: 2,
        results: [
          {
            album_id: '300',
            title: '漫画三',
            author: '测试作者',
            tags: ['校园'],
            local: localStatus(),
          },
        ],
      }),
    )

    await wrapper.find('[aria-label="下一页"]').trigger('click')
    await flushPromises()

    expect(searchAuthorByAuthor).toHaveBeenLastCalledWith('测试作者', 2)
    expect(wrapper.text()).toContain('漫画三')
    expect(wrapper.text()).not.toContain('漫画一')
    wrapper.unmount()
  })

  it('查看详情对话框展示概要并可直接下载', async () => {
    const { wrapper } = await mountPage()

    await wrapper.find('[aria-label="查看 漫画一 的详情"]').trigger('click')
    await flushPromises()

    expect(getJmAlbumDetail).toHaveBeenCalledWith('100')
    const dialogText = document.body.textContent ?? ''
    expect(dialogText).toContain('远程漫画详情')
    expect(dialogText).toContain('漫画一')
    expect(dialogText).toContain('测试作者')
    expect(dialogText).toContain('恋爱')
    expect(dialogText).toContain('88')
    expect(dialogText).toContain('1001')
    expect(dialogText).toContain('1002')

    const download = document.querySelector<HTMLButtonElement>(
      '[aria-label="下载详情漫画"]',
    )
    expect(download).not.toBeNull()
    download!.click()
    await flushPromises()
    expect(requestDownloads).toHaveBeenCalledWith(['100'])
    wrapper.unmount()
  })

  it('单本收藏调用接口并显示已收藏状态', async () => {
    const { wrapper } = await mountPage()

    await wrapper.find('[aria-label="收藏 漫画一"]').trigger('click')
    await flushPromises()

    expect(favoriteJmAlbums).toHaveBeenCalledWith(['100'])
    expect(toastMessages().join('')).toContain('已收藏 1 本')
    const button = wrapper.find('[aria-label="收藏 漫画一"]')
    expect(button.text()).toContain('已收藏')
    expect(button.attributes()).toHaveProperty('disabled')
    wrapper.unmount()
  })

  it('收藏选中漫画并汇总已在本地数量', async () => {
    vi.mocked(favoriteJmAlbums).mockResolvedValue({
      collected_count: 1,
      already_count: 1,
      failed: [],
    })
    const { wrapper } = await mountPage()

    await buttonWithText(wrapper, '全选').trigger('click')
    await buttonWithText(wrapper, '收藏选中').trigger('click')
    await flushPromises()

    expect(favoriteJmAlbums).toHaveBeenCalledWith(['100', '200'])
    expect(toastMessages().join('')).toContain('已收藏 1 本，1 本已在本地')
    wrapper.unmount()
  })

  it('收藏失败时保留原状态并展示中文原因', async () => {
    vi.mocked(favoriteJmAlbums).mockResolvedValue({
      collected_count: 0,
      already_count: 0,
      failed: [{ album_id: '200', error: '漫画不存在或已下架' }],
    })
    const { wrapper } = await mountPage()

    await wrapper.find('[aria-label="收藏 漫画二"]').trigger('click')
    await flushPromises()

    expect(toastMessages().join('')).toContain('200: 漫画不存在或已下架')
    expect(wrapper.find('[aria-label="收藏 漫画二"]').text()).toContain('收藏')
    wrapper.unmount()
  })

  it('已下载漫画禁用下载并在详情中跳转本地页面', async () => {
    const downloaded = localStatus({
      exists: true,
      status: 'downloaded',
      favorited: true,
      downloaded: true,
    })
    vi.mocked(searchAuthorByAuthor).mockResolvedValue(
      searchResult({
        results: [
          { ...albums[0], local: downloaded },
          albums[1],
        ],
      }),
    )
    vi.mocked(getJmAlbumDetail).mockResolvedValue({ ...detail, local: downloaded })
    const { wrapper, router } = await mountPage()
    const push = vi.spyOn(router, 'push')

    expect(wrapper.text()).toContain('已下载')
    expect(
      wrapper.find('[aria-label="下载 漫画一"]').attributes(),
    ).toHaveProperty('disabled')

    await wrapper.find('[aria-label="查看 漫画一 的详情"]').trigger('click')
    await flushPromises()
    const dialogText = document.body.textContent ?? ''
    expect(dialogText).toContain('已下载')
    expect(dialogText).toContain('查看本地详情')
    const download = document.querySelector<HTMLButtonElement>(
      '[aria-label="下载详情漫画"]',
    )
    expect(download).not.toBeNull()
    expect(download!.disabled).toBe(true)

    const localDetail = document.querySelector<HTMLButtonElement>(
      '[aria-label="查看本地详情"]',
    )
    localDetail!.click()
    await flushPromises()
    expect(push).toHaveBeenCalledWith({
      name: 'manga-detail',
      params: { mangaId: '100' },
    })
    await (push.mock.results[0]!.value as Promise<unknown>)
    expect(router.currentRoute.value.name).toBe('manga-detail')
    expect(router.currentRoute.value.params.mangaId).toBe('100')
    wrapper.unmount()
  })

  it('详情加载失败时在对话框内显示中文错误', async () => {
    vi.mocked(getJmAlbumDetail).mockRejectedValue(
      new ApiError(502, 'JM_ALBUM_DETAIL_FAILED', '漫画详情读取失败，请稍后重试'),
    )
    const { wrapper } = await mountPage()

    await wrapper.find('[aria-label="查看 漫画一 的详情"]').trigger('click')
    await flushPromises()

    expect(document.body.textContent).toContain('漫画详情读取失败，请稍后重试')
    expect(document.body.textContent).toContain('重试')
    wrapper.unmount()
  })

  it('缺少作者参数时不请求远程搜索', async () => {
    const { wrapper } = await mountPage('/search-author')

    expect(searchAuthorByAuthor).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('缺少作者参数，请从漫画详情页进入')
    wrapper.unmount()
  })
})
