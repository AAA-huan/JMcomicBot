import { flushPromises, shallowMount } from '@vue/test-utils'
import { ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getReadingProgress, updateFilePageCount } from '@/api/files'
import { getReaderSettings, updateReaderSettings } from '@/api/reader'
import type { ReadingProgress } from '@/types/api'
import PdfReader from './PdfReader.vue'
import ReaderToolbar from './ReaderToolbar.vue'
import type { PageBaseSize, ReadingSettingUpdate, ReadingSettings } from './types'

/** 记录进度同步配置，便于按键/点击后读取当前页码。 */
const progressState = vi.hoisted(() => ({
  schedule: vi.fn(),
  getPage: null as null | (() => number),
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { fileId: '42' }, query: {}, fullPath: '/reader/42' }),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  onBeforeRouteLeave: vi.fn(),
}))
vi.mock('@/api/files', () => ({
  fileDownloadUrl: () => '/pdf',
  getReadingProgress: vi.fn(),
  updateFilePageCount: vi.fn(),
}))
vi.mock('@/api/reader', () => ({
  getReaderSettings: vi.fn(),
  updateReaderSettings: vi.fn(),
}))
const pageImageMocks = vi.hoisted(() => ({
  probePageImage: vi.fn(),
  loadPageImageSize: vi.fn(),
}))
vi.mock('./pageImage', () => ({
  pageImageUrl: (_fileId: number, pageNumber: number) =>
    `/api/v1/files/42/page/${pageNumber}`,
  probePageImage: pageImageMocks.probePageImage,
  loadPageImageSize: pageImageMocks.loadPageImageSize,
}))
vi.mock('./usePdfDocument', () => ({
  usePdfDocument: () => ({
    doc: ref({
      numPages: 12,
      getPage: async () => ({
        getViewport: () => ({ width: 600, height: 800 }),
        cleanup: vi.fn(),
      }),
    }),
    load: async () => null,
    destroy: vi.fn(),
  }),
}))
vi.mock('./useRenderWindow', () => ({
  useRenderWindow: () => ({
    registerCanvas: vi.fn(),
    syncWindow: vi.fn(),
    releaseAll: vi.fn(),
  }),
}))
vi.mock('./progressSync', () => ({
  createProgressSync: (config: { getPage: () => number }) => {
    progressState.getPage = config.getPage
    return {
      schedule: progressState.schedule,
      flush: vi.fn().mockResolvedValue(undefined),
      retry: vi.fn(),
      dispose: vi.fn(),
    }
  },
}))

const DEFAULT_SETTINGS: ReadingSettings = {
  reading_mode: 'normal',
  continuous: false,
  click_to_turn: false,
  reverse_click: false,
  dark_background: false,
  prefetch_pages: 1,
  updated_at: '2026-01-01T00:00:00Z',
}

/** 让提示条 stub 渲染默认插槽，便于断言错误文案。 */
const MOUNT_OPTIONS = {
  global: {
    stubs: {
      VAlert: { template: '<div class="alert-stub"><slot /></div>' },
    },
  },
}

function makeSettings(overrides: Partial<ReadingSettings> = {}): ReadingSettings {
  return { ...DEFAULT_SETTINGS, ...overrides }
}

function applyUpdate(payload: ReadingSettingUpdate): ReadingSettings {
  return makeSettings(payload)
}

/** 让页面探测返回图片型结果，并指定当前页原始尺寸。 */
function useImageProbe(
  size: { width: number; height: number } = { width: 800, height: 1200 },
): void {
  pageImageMocks.probePageImage.mockResolvedValue({ kind: 'image', size })
}

/** 等待 PDF 初始化完成（页数登记、12 页尺寸读取与进度恢复）。 */
async function mountReader(
  settings: Partial<ReadingSettings> = {},
): Promise<ReturnType<typeof shallowMount>> {
  vi.mocked(getReaderSettings).mockResolvedValue(makeSettings(settings))
  const wrapper = shallowMount(PdfReader, MOUNT_OPTIONS)
  await flushPromises()
  await flushPromises()
  return wrapper
}

function currentPage(): number | undefined {
  return progressState.getPage?.()
}

/** 模拟点击阅读区横向位置；容器宽度固定为 300。 */
async function clickAt(
  wrapper: ReturnType<typeof shallowMount>,
  clientX: number,
): Promise<void> {
  const scroll = wrapper.find('.reader-scroll')
  const element = scroll.element as HTMLElement
  element.getBoundingClientRect = () =>
    ({ left: 0, top: 0, width: 300, height: 400 }) as DOMRect
  await scroll.trigger('click', { clientX, button: 0 })
  await flushPromises()
}

async function pressKey(key: string): Promise<void> {
  window.dispatchEvent(new KeyboardEvent('keydown', { key }))
  await flushPromises()
}

beforeEach(() => {
  pageImageMocks.probePageImage.mockReset()
  pageImageMocks.probePageImage.mockResolvedValue({ kind: 'fallback' })
  pageImageMocks.loadPageImageSize.mockReset()
  pageImageMocks.loadPageImageSize.mockResolvedValue({ width: 1000, height: 1320 })
  vi.mocked(getReaderSettings).mockReset()
  vi.mocked(updateReaderSettings).mockReset()
  vi.mocked(updateReaderSettings).mockImplementation(async (payload) =>
    applyUpdate(payload),
  )
  vi.mocked(getReadingProgress).mockReset()
  vi.mocked(getReadingProgress).mockResolvedValue({
    file_id: 42,
    page_number: 1,
    page_count: 12,
    percent: 0,
    updated_at: null,
  })
  vi.mocked(updateFilePageCount).mockReset()
  vi.mocked(updateFilePageCount).mockResolvedValue(undefined)
  progressState.getPage = null
  progressState.schedule.mockReset()
  // 连续模式初始化会调用 scrollTo 对齐当前页，jsdom 未实现该方法
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
    configurable: true,
    value: vi.fn(),
  })
  window.localStorage.clear()
})

describe('初始化', () => {
  it('打开后不翻页也立即上报 PDF 实际页数', async () => {
    const wrapper = await mountReader()
    expect(updateFilePageCount).toHaveBeenCalledExactlyOnceWith(42, 12)
    wrapper.unmount()
  })

  it('设置与进度并行请求，probe 在两者完成后执行', async () => {
    let resolveSettings!: (value: ReadingSettings) => void
    let resolveProgress!: (value: ReadingProgress) => void
    vi.mocked(getReaderSettings).mockReturnValue(
      new Promise((resolve) => {
        resolveSettings = resolve
      }),
    )
    vi.mocked(getReadingProgress).mockReturnValue(
      new Promise((resolve) => {
        resolveProgress = resolve
      }),
    )
    const wrapper = shallowMount(PdfReader, MOUNT_OPTIONS)
    await flushPromises()

    expect(getReaderSettings).toHaveBeenCalledTimes(1)
    expect(getReadingProgress).toHaveBeenCalledTimes(1)
    expect(pageImageMocks.probePageImage).not.toHaveBeenCalled()

    resolveSettings(makeSettings())
    resolveProgress({
      file_id: 42,
      page_number: 1,
      page_count: 12,
      percent: 0,
      updated_at: null,
    })
    await flushPromises()
    await flushPromises()

    expect(pageImageMocks.probePageImage).toHaveBeenCalledWith(42, 1)
    wrapper.unmount()
  })

  it('首页尺寸后台补全，不阻塞 loading 且不改变其余页占位', async () => {
    vi.mocked(getReadingProgress).mockResolvedValue({
      file_id: 42,
      page_number: 2,
      page_count: 12,
      percent: 8,
      updated_at: null,
    })
    let resolveFirstSize!: (size: PageBaseSize | null) => void
    pageImageMocks.loadPageImageSize.mockReturnValue(
      new Promise((resolve) => {
        resolveFirstSize = resolve
      }),
    )
    useImageProbe({ width: 800, height: 1200 })
    const wrapper = await mountReader({ continuous: true, prefetch_pages: 2 })

    expect(wrapper.find('.reader-status').exists()).toBe(false)
    expect(pageImageMocks.probePageImage).toHaveBeenCalledWith(42, 2)
    expect(pageImageMocks.loadPageImageSize).toHaveBeenCalledWith(42, 1)
    const pageOne = wrapper.find('[data-reader-page="1"]')
    const pageThree = wrapper.find('[data-reader-page="3"]')
    expect(pageOne.attributes('style')).toContain('width: 800px')
    expect(pageThree.attributes('style')).toContain('width: 800px')

    resolveFirstSize({ width: 1000, height: 1320 })
    await flushPromises()

    expect(pageOne.attributes('style')).toContain('width: 1000px')
    // 其余未知页继续使用 probe 页尺寸，不随首页尺寸整体跳动
    expect(pageThree.attributes('style')).toContain('width: 800px')
    wrapper.unmount()
  })

  it('进度页就是首页时不再额外请求首页尺寸', async () => {
    useImageProbe()
    const wrapper = await mountReader()

    expect(pageImageMocks.loadPageImageSize).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('用后端设置初始化模式、连续、点击、反转与深色背景', async () => {
    const wrapper = await mountReader({
      reading_mode: 'manga',
      continuous: true,
      click_to_turn: true,
      reverse_click: true,
      dark_background: true,
    })
    const toolbar = wrapper.findComponent(ReaderToolbar)
    expect(toolbar.props()).toMatchObject({
      mode: 'manga',
      continuous: true,
      clickToTurn: true,
      reverseClick: true,
      dark: true,
    })
    expect(wrapper.find('.reader-root').classes()).toContain('reader-root--dark')
    wrapper.unmount()
  })

  it('读取设置失败时保留默认值并提示，不阻塞阅读', async () => {
    vi.mocked(getReaderSettings).mockRejectedValue(new Error('网络断开'))
    const wrapper = shallowMount(PdfReader, MOUNT_OPTIONS)
    await flushPromises()
    await flushPromises()

    const toolbar = wrapper.findComponent(ReaderToolbar)
    expect(toolbar.props()).toMatchObject({
      mode: 'normal',
      continuous: false,
      clickToTurn: false,
      reverseClick: false,
      dark: false,
    })
    expect(wrapper.text()).toContain('阅读设置加载失败')
    expect(updateFilePageCount).toHaveBeenCalledExactlyOnceWith(42, 12)
    wrapper.unmount()
  })

  it('不再读取或写入旧的 localStorage 深色背景', async () => {
    window.localStorage.setItem('jmbot-reader-dark', '1')
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    const wrapper = await mountReader({ dark_background: false })

    expect(wrapper.findComponent(ReaderToolbar).props('dark')).toBe(false)
    expect(setItem).not.toHaveBeenCalledWith('jmbot-reader-dark', expect.anything())
    wrapper.unmount()
    setItem.mockRestore()
  })
})

describe('翻页方向', () => {
  it('普通模式右滑/右方向键下一页，左方向键上一页', async () => {
    const wrapper = await mountReader({ reading_mode: 'normal' })
    await pressKey('ArrowRight')
    expect(currentPage()).toBe(2)
    await pressKey('ArrowLeft')
    expect(currentPage()).toBe(1)
    wrapper.unmount()
  })

  it('日漫模式左方向键下一页，右方向键上一页', async () => {
    const wrapper = await mountReader({ reading_mode: 'manga' })
    await pressKey('ArrowLeft')
    expect(currentPage()).toBe(2)
    await pressKey('ArrowRight')
    expect(currentPage()).toBe(1)
    wrapper.unmount()
  })

  it('滚动模式下方向键下一页，上方向键上一页', async () => {
    const wrapper = await mountReader({ reading_mode: 'scroll' })
    await pressKey('ArrowDown')
    expect(currentPage()).toBe(2)
    await pressKey('ArrowUp')
    expect(currentPage()).toBe(1)
    wrapper.unmount()
  })

  it('点击翻页关闭时点击左右区域均不翻页', async () => {
    const wrapper = await mountReader({ click_to_turn: false })
    await clickAt(wrapper, 20)
    expect(currentPage()).toBe(1)
    await clickAt(wrapper, 280)
    expect(currentPage()).toBe(1)
    wrapper.unmount()
  })

  it('普通模式点击左区上一页、右区下一页、中间不响应', async () => {
    const wrapper = await mountReader({ click_to_turn: true })
    await clickAt(wrapper, 270)
    expect(currentPage()).toBe(2)
    await clickAt(wrapper, 150)
    expect(currentPage()).toBe(2)
    await clickAt(wrapper, 20)
    expect(currentPage()).toBe(1)
    wrapper.unmount()
  })

  it('日漫模式点击方向与普通模式相反', async () => {
    const wrapper = await mountReader({
      reading_mode: 'manga',
      click_to_turn: true,
    })
    await clickAt(wrapper, 20)
    expect(currentPage()).toBe(2)
    await clickAt(wrapper, 280)
    expect(currentPage()).toBe(1)
    wrapper.unmount()
  })

  it('反转点击只翻转点击方向，不影响键盘翻页', async () => {
    const wrapper = await mountReader({
      reading_mode: 'manga',
      click_to_turn: true,
      reverse_click: true,
    })
    // 日漫 + 反转抵消为普通方向：左侧上一页、右侧下一页
    await clickAt(wrapper, 280)
    expect(currentPage()).toBe(2)
    await clickAt(wrapper, 20)
    expect(currentPage()).toBe(1)
    await pressKey('ArrowLeft')
    expect(currentPage()).toBe(2)
    wrapper.unmount()
  })

  it('连续模式点击翻页并把目标页居中', async () => {
    const wrapper = await mountReader({
      continuous: true,
      click_to_turn: true,
    })
    const scroll = wrapper.find('.reader-scroll').element as HTMLElement
    Object.defineProperty(scroll, 'clientWidth', {
      configurable: true,
      value: 300,
    })
    const scrollTo = HTMLElement.prototype.scrollTo as ReturnType<typeof vi.fn>
    scrollTo.mockClear()

    await clickAt(wrapper, 270)
    expect(currentPage()).toBe(2)
    // 页宽 600、间距/内边距 4：第 2 页中心 908，减去视口中心 150
    expect(scrollTo).toHaveBeenCalledWith({ left: 758, behavior: 'auto' })
    wrapper.unmount()
  })

  it('连续横排停止滚动后自动把当前页居中', async () => {
    const wrapper = await mountReader({
      continuous: true,
      reading_mode: 'normal',
    })
    const scroll = wrapper.find('.reader-scroll').element as HTMLElement
    Object.defineProperty(scroll, 'clientWidth', {
      configurable: true,
      value: 300,
    })
    scroll.scrollLeft = 100
    const scrollTo = HTMLElement.prototype.scrollTo as ReturnType<typeof vi.fn>
    scrollTo.mockClear()

    scroll.dispatchEvent(new Event('scroll'))
    await new Promise((resolve) => setTimeout(resolve, 220))

    expect(currentPage()).toBe(1)
    // 第 1 页中心 304，减去视口中心 150
    expect(scrollTo).toHaveBeenCalledWith({ left: 154, behavior: 'smooth' })
    wrapper.unmount()
  })
})

describe('连续布局', () => {
  it('普通模式水平横排，页间距 4px', async () => {
    const wrapper = await mountReader({ continuous: true, reading_mode: 'normal' })
    const scroll = wrapper.find('.reader-scroll')
    const pages = wrapper.find('.reader-pages')
    expect(scroll.classes()).toContain('reader-scroll--horizontal')
    expect(pages.classes()).toContain('reader-pages--horizontal')
    expect(pages.classes()).not.toContain('reader-pages--reverse')
    expect(pages.attributes('style')).toContain('--reader-page-gap: 4px')
    expect(wrapper.findAll('.reader-page')).toHaveLength(12)
    wrapper.unmount()
  })

  it('日漫模式水平反向排列', async () => {
    const wrapper = await mountReader({ continuous: true, reading_mode: 'manga' })
    const pages = wrapper.find('.reader-pages')
    expect(pages.classes()).toContain('reader-pages--horizontal')
    expect(pages.classes()).toContain('reader-pages--reverse')
    wrapper.unmount()
  })

  it('滚动模式垂直纵排且可上下滚动', async () => {
    const wrapper = await mountReader({ continuous: true, reading_mode: 'scroll' })
    const scroll = wrapper.find('.reader-scroll')
    const pages = wrapper.find('.reader-pages')
    expect(scroll.classes()).not.toContain('reader-scroll--horizontal')
    expect(pages.classes()).not.toContain('reader-pages--horizontal')
    expect(pages.classes()).not.toContain('reader-pages--reverse')
    expect(pages.attributes('style')).toContain('--reader-page-gap: 4px')
    expect(wrapper.findAll('canvas')).toHaveLength(2)
    wrapper.unmount()
  })

  it('不连续模式只渲染当前页，不产生连排容器', async () => {
    const wrapper = await mountReader({ continuous: false })
    expect(wrapper.find('.reader-pages').exists()).toBe(false)
    expect(wrapper.findAll('canvas')).toHaveLength(1)
    wrapper.unmount()
  })
})

describe('页面类型探测', () => {
  it('探测为图片型时使用 <img> 渲染且不再加载 PDF.js', async () => {
    useImageProbe()
    const wrapper = await mountReader()

    expect(pageImageMocks.probePageImage).toHaveBeenCalledWith(42, 1)
    const image = wrapper.find('.reader-single img')
    expect(image.exists()).toBe(true)
    expect(image.attributes('src')).toBe('/api/v1/files/42/page/1')
    expect(image.attributes('alt')).toBe('第 1 页')
    expect(wrapper.find('canvas').exists()).toBe(false)
    // 图片型页数直接取进度接口，不再通过 PDF.js 回写
    expect(updateFilePageCount).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('探测为 404/415 回退时保留 PDF.js Canvas 并同步页数', async () => {
    const wrapper = await mountReader()

    expect(pageImageMocks.probePageImage).toHaveBeenCalledWith(42, 1)
    expect(wrapper.find('canvas').exists()).toBe(true)
    expect(wrapper.find('.reader-single img').exists()).toBe(false)
    expect(updateFilePageCount).toHaveBeenCalledWith(42, 12)
    wrapper.unmount()
  })
})

describe('图片型连续模式', () => {
  it('按预加载页数限制 <img> 挂载窗口', async () => {
    useImageProbe()
    const wrapper = await mountReader({ continuous: true, prefetch_pages: 2 })

    // 第 1 页窗口为 1-3 页
    expect(wrapper.findAll('.reader-page img')).toHaveLength(3)
    expect(
      wrapper.findAll('.reader-page img').map((image) => image.attributes('src')),
    ).toEqual([
      '/api/v1/files/42/page/1',
      '/api/v1/files/42/page/2',
      '/api/v1/files/42/page/3',
    ])

    vi.mocked(updateReaderSettings).mockResolvedValueOnce(
      makeSettings({ continuous: true, prefetch_pages: 0 }),
    )
    wrapper
      .findComponent(ReaderToolbar)
      .vm.$emit('update:prefetch-pages', 0)
    await flushPromises()
    expect(wrapper.findAll('.reader-page img')).toHaveLength(1)
    wrapper.unmount()
  })

  it('单页模式忽略预加载页数，只保留当前页', async () => {
    useImageProbe()
    const wrapper = await mountReader({ continuous: false, prefetch_pages: 5 })

    expect(wrapper.findAll('img')).toHaveLength(1)
    expect(wrapper.find('img').attributes('src')).toBe('/api/v1/files/42/page/1')
    wrapper.unmount()
  })

  it('图片加载完成后用真实尺寸更新占位布局', async () => {
    useImageProbe({ width: 800, height: 1200 })
    const wrapper = await mountReader()

    const image = wrapper.find('.reader-single img')
    expect(image.attributes('style')).toContain('width: 800px')
    expect(image.attributes('style')).toContain('height: 1200px')
    expect(image.classes()).toContain('reader-page-image--loading')

    Object.defineProperty(image.element, 'naturalWidth', {
      configurable: true,
      value: 1000,
    })
    Object.defineProperty(image.element, 'naturalHeight', {
      configurable: true,
      value: 1500,
    })
    await image.trigger('load')

    expect(image.attributes('style')).toContain('width: 1000px')
    expect(image.attributes('style')).toContain('height: 1500px')
    expect(image.classes()).not.toContain('reader-page-image--loading')
    wrapper.unmount()
  })

  it('日漫连排滚动位置按从右往左映射当前页', async () => {
    useImageProbe()
    const wrapper = await mountReader({
      continuous: true,
      reading_mode: 'manga',
      prefetch_pages: 1,
    })
    const scroll = wrapper.find('.reader-scroll').element as HTMLElement
    Object.defineProperty(scroll, 'clientWidth', {
      configurable: true,
      value: 300,
    })
    scroll.scrollLeft = 0

    const rectSpy = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect')
    scroll.dispatchEvent(new Event('scroll'))
    await new Promise((resolve) => setTimeout(resolve, 220))

    // 反向排列时首页在最右，scrollLeft=0 对应最后一页
    expect(currentPage()).toBe(12)
    expect(rectSpy).not.toHaveBeenCalled()
    rectSpy.mockRestore()
    wrapper.unmount()
  })
})

describe('工具栏设置同步', () => {
  it('切换模式立即提交后端并应用返回结果', async () => {
    const wrapper = await mountReader()
    wrapper.findComponent(ReaderToolbar).vm.$emit('update:mode', 'manga')
    await flushPromises()

    expect(updateReaderSettings).toHaveBeenCalledWith({ reading_mode: 'manga' })
    expect(wrapper.findComponent(ReaderToolbar).props('mode')).toBe('manga')
    wrapper.unmount()
  })

  it('关闭点击翻页时同时关闭反转并提交两项', async () => {
    const wrapper = await mountReader({
      click_to_turn: true,
      reverse_click: true,
    })
    wrapper
      .findComponent(ReaderToolbar)
      .vm.$emit('update:click-to-turn', false)
    await flushPromises()

    expect(updateReaderSettings).toHaveBeenCalledWith({
      click_to_turn: false,
      reverse_click: false,
    })
    const toolbar = wrapper.findComponent(ReaderToolbar)
    expect(toolbar.props('clickToTurn')).toBe(false)
    expect(toolbar.props('reverseClick')).toBe(false)
    wrapper.unmount()
  })

  it('点击翻页关闭时忽略反转开关事件', async () => {
    const wrapper = await mountReader({ click_to_turn: false })
    wrapper
      .findComponent(ReaderToolbar)
      .vm.$emit('update:reverse-click', true)
    await flushPromises()

    expect(updateReaderSettings).not.toHaveBeenCalled()
    expect(wrapper.findComponent(ReaderToolbar).props('reverseClick')).toBe(false)
    wrapper.unmount()
  })

  it('保存失败时回滚本地状态并明确提示', async () => {
    const wrapper = await mountReader()
    vi.mocked(updateReaderSettings).mockRejectedValueOnce(new Error('写入失败'))
    wrapper.findComponent(ReaderToolbar).vm.$emit('update:dark', true)
    await flushPromises()

    expect(wrapper.findComponent(ReaderToolbar).props('dark')).toBe(false)
    expect(wrapper.text()).toContain('阅读设置保存失败')
    expect(wrapper.text()).toContain('写入失败')
    wrapper.unmount()
  })
})
