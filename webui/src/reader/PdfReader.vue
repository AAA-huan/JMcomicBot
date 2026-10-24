<script setup lang="ts">
/**
 * 漫画在线阅读器：单页/连排滚动、缩放、跳页、全屏、阅读设置与进度同步。
 *
 * 首次打开只请求当前进度页的尺寸端点：图片型 PDF 使用 <img> 按窗口懒加载，
 * 完全不经过 PDF.js；非图片型 PDF 回退到 PDF.js + Canvas。尺寸请求不下载
 * 图字节、不在客户端 decode，首页尺寸在 loading 结束后后台补全。连排滚动
 * 位置由页面尺寸缓存的 offset 二分查找，不再逐页 getBoundingClientRect。
 * 阅读模式、连续显示、点击翻页、深色背景与预加载页数统一保存在后端，
 * 工具栏改动即时同步并在失败时回滚。进度 1 秒防抖写入，页面隐藏/离开时
 * keepalive 立即刷新；失败明确提示「进度未同步」并可重试，不阻塞阅读。
 */

import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch, type Directive } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'

import { ApiError, errorMessage } from '@/api/client'
import { fileDownloadUrl, getReadingProgress, updateFilePageCount } from '@/api/files'
import { getReaderSettings, updateReaderSettings } from '@/api/reader'
import type { ReadingProgress } from '@/types/api'
import ReaderToolbar from './ReaderToolbar.vue'
import {
  buildPageLayout,
  findPageIndexAt,
  positionAlongContent,
  scrollPositionForPage,
} from './layout'
import { loadPageImageSize, pageImageUrl, probePageImage } from './pageImage'
import {
  createProgressSync,
  type ProgressSync,
  type ProgressSyncState,
} from './progressSync'
import {
  RENDER_WINDOW_RADIUS,
  clickTurnDelta,
  computeFitScale,
  isHorizontalScroll,
  keyTurnDelta,
  pageGap,
  swipeTurnDelta,
  windowPagesFor,
  type PageBaseSize,
  type ReaderMode,
  type ReadingSettingUpdate,
  type ReadingSettings,
  type ZoomMode,
} from './types'
import { mapPdfError, type ReaderError } from './pdfErrors'
import { usePdfDocument } from './usePdfDocument'
import { useRenderWindow } from './useRenderWindow'

const route = useRoute()
const router = useRouter()

const fileId = Number(route.params.fileId)
const from = typeof route.query.from === 'string' ? route.query.from : ''

const { doc, load, destroy } = usePdfDocument()
const { registerCanvas, syncWindow, releaseAll } = useRenderWindow(doc)

const readerRoot = ref<HTMLElement | null>(null)
const loading = ref(true)
const error = ref<ReaderError | null>(null)
const pageNumber = ref(1)
const pageCount = ref(0)
const imageMode = ref(false)
const mode = ref<ReaderMode>('normal')
const continuous = ref(false)
const clickToTurn = ref(false)
const reverseClick = ref(false)
const dark = ref(false)
const prefetchPages = ref(RENDER_WINDOW_RADIUS)
const settingsError = ref('')
const zoomMode = ref<ZoomMode>('fit-width')
const customScale = ref(1)
const fullscreen = ref(false)
const progressState = ref<ProgressSyncState>('synced')
const progressLoadFailed = ref(false)
const pageCountSyncError = ref('')
// 图片型路径初始只有当前页尺寸，其余页为 null，占位使用 probe 页尺寸
const baseSizes = ref<Array<PageBaseSize | null>>([])
// probe 页尺寸作为所有未知页的占位基准；首页尺寸在后台单独补全
const probeBaseSize = ref<PageBaseSize | null>(null)
// 已成功加载图片的页码，用于清除当前页的背景占位
const loadedPages = ref<Set<number>>(new Set())
const containerWidth = ref(0)
const containerHeight = ref(0)

const PAGE_PADDING = 16
const FALLBACK_PAGE_SIZE: PageBaseSize = { width: 600, height: 800 }

const downloadUrl = computed(() => fileDownloadUrl(fileId))
const horizontal = computed(() => isHorizontalScroll(mode.value))
const mangaDirection = computed(() => mode.value === 'manga')

// ---------- 阅读设置 ----------

/** 把后端设置应用到阅读器状态。 */
function applyReaderSettings(settings: ReadingSettings): void {
  mode.value = settings.reading_mode
  continuous.value = settings.continuous
  clickToTurn.value = settings.click_to_turn
  reverseClick.value = settings.reverse_click
  dark.value = settings.dark_background
  prefetchPages.value = settings.prefetch_pages
}

/** 启动时加载后端设置；401 时返回 false，由调用方中止初始化。 */
async function loadReaderSettings(): Promise<boolean> {
  try {
    applyReaderSettings(await getReaderSettings())
    return true
  } catch (settingsLoadError) {
    if (settingsLoadError instanceof ApiError && settingsLoadError.status === 401) {
      redirectToLogin()
      return false
    }
    settingsError.value = `阅读设置加载失败：${errorMessage(settingsLoadError)}`
    return true
  }
}

let settingsRequestId = 0

/** 保存部分设置；失败回滚本地状态并提示。*/
async function persistReaderSettings(
  payload: ReadingSettingUpdate,
  rollback: () => void,
): Promise<void> {
  const requestId = (settingsRequestId += 1)
  try {
    const updated = await updateReaderSettings(payload)
    if (requestId === settingsRequestId) applyReaderSettings(updated)
  } catch (saveError) {
    if (requestId !== settingsRequestId) return
    rollback()
    if (saveError instanceof ApiError && saveError.status === 401) {
      redirectToLogin()
      return
    }
    settingsError.value = `阅读设置保存失败：${errorMessage(saveError)}`
  }
}

/** 布局或滚动轴变化后，把当前页重新对齐到连排容器。 */
function alignCurrentPage(): void {
  if (!continuous.value) return
  void nextTick(() => scrollToPage(pageNumber.value))
}

function setMode(value: ReaderMode): void {
  if (mode.value === value) return
  cancelHorizontalSnap()
  const previous = mode.value
  mode.value = value
  alignCurrentPage()
  void persistReaderSettings({ reading_mode: value }, () => {
    mode.value = previous
    alignCurrentPage()
  })
}

function setContinuous(value: boolean): void {
  if (continuous.value === value) return
  cancelHorizontalSnap()
  continuous.value = value
  alignCurrentPage()
  void persistReaderSettings({ continuous: value }, () => {
    continuous.value = !value
    alignCurrentPage()
  })
}

function setClickToTurn(value: boolean): void {
  if (clickToTurn.value === value) return
  const previous = clickToTurn.value
  const previousReverse = reverseClick.value
  clickToTurn.value = value
  // 关闭点击翻页时同时关闭反转，避免触发后端依赖校验失败
  if (!value) reverseClick.value = false
  void persistReaderSettings(
    value
      ? { click_to_turn: true }
      : { click_to_turn: false, reverse_click: false },
    () => {
      clickToTurn.value = previous
      reverseClick.value = previousReverse
    },
  )
}

function setReverseClick(value: boolean): void {
  if (!clickToTurn.value || reverseClick.value === value) return
  const previous = reverseClick.value
  reverseClick.value = value
  void persistReaderSettings({ reverse_click: value }, () => {
    reverseClick.value = previous
  })
}

function setDark(value: boolean): void {
  if (dark.value === value) return
  const previous = dark.value
  dark.value = value
  void persistReaderSettings({ dark_background: value }, () => {
    dark.value = previous
  })
}

function setPrefetchPages(value: number): void {
  if (prefetchPages.value === value) return
  const previous = prefetchPages.value
  prefetchPages.value = value
  alignCurrentPage()
  void persistReaderSettings({ prefetch_pages: value }, () => {
    prefetchPages.value = previous
    alignCurrentPage()
  })
}

// 预加载页数变化会改变渲染窗口；连排时保持当前页位置不跳动
watch(prefetchPages, () => {
  alignCurrentPage()
})

// ---------- 缩放与页面尺寸 ----------

/** 未知页占位尺寸：优先 probe 页尺寸，PDF.js 路径回退到已知尺寸。 */
const placeholderSize = computed<PageBaseSize>(() => {
  if (probeBaseSize.value) return probeBaseSize.value
  const known = baseSizes.value.find(
    (size): size is PageBaseSize => size !== null,
  )
  return known ?? FALLBACK_PAGE_SIZE
})

/** 单页/占位使用的基准尺寸。 */
function baseSizeOf(target: number): PageBaseSize {
  return baseSizes.value[target - 1] ?? placeholderSize.value
}

/** 适应计算的目标页面尺寸：单页用当前页，连排用最大页保证不溢出。 */
const fitBase = computed<PageBaseSize | null>(() => {
  if (pageCount.value === 0) return null
  if (!continuous.value) return baseSizeOf(pageNumber.value)
  let width = 0
  let height = 0
  for (let page = 1; page <= pageCount.value; page += 1) {
    const size = baseSizeOf(page)
    width = Math.max(width, size.width)
    height = Math.max(height, size.height)
  }
  return { width, height }
})

const scale = computed(() => {
  if (zoomMode.value === 'custom') return customScale.value
  const base = fitBase.value
  if (!base || containerWidth.value === 0) return 1
  const availableWidth = Math.max(containerWidth.value - PAGE_PADDING * 2, 100)
  const availableHeight = Math.max(containerHeight.value - PAGE_PADDING * 2, 100)
  return computeFitScale(base, availableWidth, availableHeight, zoomMode.value)
})

/** 连排占位尺寸，未加载真实尺寸的页面仍保留布局高度/宽度。 */
const pageSizes = computed<PageBaseSize[]>(() => {
  const sizes: PageBaseSize[] = []
  for (let page = 1; page <= pageCount.value; page += 1) {
    const base = baseSizeOf(page)
    sizes.push({
      width: base.width * scale.value,
      height: base.height * scale.value,
    })
  }
  return sizes
})

/** 每页沿滚动方向的起始偏移；页面尺寸或缩放变化时整体重算一次。 */
const pageLayout = computed(() =>
  buildPageLayout(pageSizes.value, horizontal.value, pageGap(continuous.value)),
)
const pageOffsets = computed(() => pageLayout.value.offsets)

const windowPages = computed(() =>
  continuous.value
    ? windowPagesFor(pageNumber.value, pageCount.value, prefetchPages.value)
    : [pageNumber.value],
)

/** 某页图片的显示样式：使用缩放后的占位尺寸，浏览器只负责解码。 */
function pageStyle(target: number): Record<string, string> {
  const size = pageSizes.value[target - 1]
  if (!size) return {}
  return { width: `${size.width}px`, height: `${size.height}px` }
}

/** 当前页图片是否已完成加载；未完成时保留背景色占位。 */
function isPageLoaded(target: number): boolean {
  return loadedPages.value.has(target)
}

/** <img> 加载完成后清除占位，并记录真实尺寸驱动布局自动更新。 */
function onPageLoad(target: number, event: Event): void {
  const image = event.target
  if (!(image instanceof HTMLImageElement)) return
  if (!loadedPages.value.has(target)) {
    const loaded = new Set(loadedPages.value)
    loaded.add(target)
    loadedPages.value = loaded
  }
  const width = image.naturalWidth
  const height = image.naturalHeight
  if (width <= 0 || height <= 0) return
  const current = baseSizes.value[target - 1]
  if (current?.width === width && current.height === height) return
  const updated = baseSizes.value.slice()
  updated[target - 1] = { width, height }
  baseSizes.value = updated
}

// ---------- 渲染 ----------

async function renderWindow(): Promise<void> {
  // 图片型路径完全由 windowPages + v-if 管理 <img> 挂载
  if (imageMode.value) return
  if (!doc.value || baseSizes.value.length === 0) return
  try {
    await syncWindow(windowPages.value, scale.value)
  } catch (renderError) {
    error.value = mapPdfError(renderError)
  }
}

watch(
  [windowPages, scale, imageMode],
  () => {
    void renderWindow()
  },
  { flush: 'post' },
)

// Canvas 由指令注册，元素挂载/卸载时触发，不受组件重渲染影响
const vReaderCanvas: Directive<HTMLCanvasElement, { pageNumber: number }> = {
  mounted(element, binding) {
    registerCanvas(binding.value.pageNumber, element)
    void renderWindow()
  },
  unmounted(_element, binding) {
    registerCanvas(binding.value.pageNumber, null)
  },
}

// 滚动容器通过指令绑定尺寸监听，避免频繁解绑重绑
let resizeObserver: ResizeObserver | null = null

function updateContainerSize(element: HTMLElement): void {
  containerWidth.value = element.clientWidth
  containerHeight.value = element.clientHeight
}

const vReaderSize: Directive<HTMLElement> = {
  mounted(element) {
    resizeObserver = new ResizeObserver(() => updateContainerSize(element))
    resizeObserver.observe(element)
    updateContainerSize(element)
  },
  unmounted() {
    resizeObserver?.disconnect()
    resizeObserver = null
  },
}

// ---------- 翻页与滚动 ----------

/** 连续横排滚动停止后，等待短暂时间再居中当前页。 */
const HORIZONTAL_SNAP_DELAY = 80
/** 单页模式滚轮翻页的最小间隔，避免触控板惯性一次翻多页。 */
const WHEEL_TURN_THROTTLE = 300

let scrollElement: HTMLElement | null = null
let scrollRaf: number | null = null
let snapTimer: number | null = null
let wheelLock = 0

const vReaderScroll: Directive<HTMLElement> = {
  mounted(element) {
    scrollElement = element
    element.addEventListener('scroll', onScroll, { passive: true })
  },
  unmounted(element) {
    element.removeEventListener('scroll', onScroll)
    scrollElement = null
  },
}

/** 取消待执行的横排自动居中，避免与主动跳页冲突。 */
function cancelHorizontalSnap(): void {
  if (snapTimer === null) return
  window.clearTimeout(snapTimer)
  snapTimer = null
}

/**
 * 连排模式：把目标页对齐到滚动容器。
 *
 * 普通/日漫横排把页面居中；滚动模式把目标页顶部对齐到容器起始位置。
 * 位置全部由缓存的 pageLayout 计算，不读取页面元素的位置。
 */
function scrollToPage(target: number, behavior: 'auto' | 'smooth' = 'auto'): void {
  cancelHorizontalSnap()
  const container = scrollElement
  const index = target - 1
  if (!container || index < 0 || index >= pageOffsets.value.length) return
  if (horizontal.value) {
    const left = scrollPositionForPage(
      pageLayout.value,
      index,
      container.clientWidth,
      mangaDirection.value,
      true,
    )
    container.scrollTo({ left, behavior })
  } else {
    const top = scrollPositionForPage(
      pageLayout.value,
      index,
      container.clientHeight,
      false,
      false,
    )
    container.scrollTo({ top, behavior })
  }
}

/** 用户停止横排滚动后，把视口中心所在的页面扶正到中央。 */
function centerCurrentPage(): void {
  if (!continuous.value || !horizontal.value) return
  updateCurrentFromScroll()
  scrollToPage(pageNumber.value, 'smooth')
}

function onScroll(): void {
  // 每次滚动事件都重置防抖计时，等用户真正停下后再自动居中
  if (continuous.value && horizontal.value) {
    cancelHorizontalSnap()
    snapTimer = window.setTimeout(() => {
      snapTimer = null
      centerCurrentPage()
    }, HORIZONTAL_SNAP_DELAY)
  }
  if (scrollRaf !== null) return
  scrollRaf = window.requestAnimationFrame(() => {
    scrollRaf = null
    updateCurrentFromScroll()
  })
}

/**
 * 连排模式：取视口中心所在的页面为当前页。
 *
 * 只读取容器滚动位置与尺寸，对缓存的 pageOffsets 二分查找，复杂度
 * O(log n)，滚动过程中不触发页面元素 reflow。
 */
function updateCurrentFromScroll(): void {
  const container = scrollElement
  if (!container || !continuous.value) return
  const layout = pageLayout.value
  if (layout.offsets.length === 0) return
  const viewportLength = horizontal.value
    ? container.clientWidth
    : container.clientHeight
  if (viewportLength <= 0) return
  const scrollOffset = horizontal.value
    ? container.scrollLeft
    : container.scrollTop
  const position = positionAlongContent(
    layout,
    scrollOffset,
    viewportLength,
    mangaDirection.value,
  )
  const index = findPageIndexAt(layout, position)
  if (index >= 0 && index + 1 !== pageNumber.value) {
    pageNumber.value = index + 1
  }
}

function goToPage(target: number): void {
  if (pageCount.value === 0) return
  const clamped = Math.min(Math.max(target, 1), pageCount.value)
  if (continuous.value) {
    pageNumber.value = clamped
    void nextTick(() => scrollToPage(clamped))
  } else {
    pageNumber.value = clamped
  }
}

function goRelative(delta: number): void {
  goToPage(pageNumber.value + delta)
}

function setZoomMode(value: ZoomMode): void {
  zoomMode.value = value
}

function setZoomPercent(percent: number): void {
  customScale.value = percent / 100
  zoomMode.value = 'custom'
}

// ---------- 鼠标滚轮、触摸、键盘与点击翻页 ----------

/**
 * 鼠标滚轮：单页翻页、连续横排转横向滚动，垂直连排交给原生滚动。
 *
 * 滚轮「下滚=下一页」的语义固定，不随普通/日漫模式反转。横向模式需要
 * preventDefault 阻止页面整体纵向滚动，因此监听器不能使用 passive。
 */
function onWheel(event: WheelEvent): void {
  if (!continuous.value) {
    if (event.deltaY === 0) return
    const now = Date.now()
    if (wheelLock !== 0 && now - wheelLock < WHEEL_TURN_THROTTLE) return
    wheelLock = now
    goRelative(event.deltaY > 0 ? 1 : -1)
    return
  }
  if (!horizontal.value) return
  const container = scrollElement
  if (!container || event.deltaY === 0) return
  event.preventDefault()
  container.scrollLeft += event.deltaY
}

let touchStart: { x: number; y: number } | null = null
let suppressClick = false
let suppressClickTimer: number | null = null

function onTouchStart(event: TouchEvent): void {
  if (continuous.value) return
  const touch = event.touches[0]
  if (!touch) return
  touchStart = { x: touch.clientX, y: touch.clientY }
}

function onTouchEnd(event: TouchEvent): void {
  if (continuous.value || touchStart === null) return
  const touch = event.changedTouches[0]
  const start = touchStart
  touchStart = null
  if (!touch) return
  const delta = swipeTurnDelta(
    mode.value,
    touch.clientX - start.x,
    touch.clientY - start.y,
  )
  if (delta === 0) return
  suppressClick = true
  if (suppressClickTimer !== null) window.clearTimeout(suppressClickTimer)
  suppressClickTimer = window.setTimeout(() => {
    suppressClick = false
    suppressClickTimer = null
  }, 400)
  goRelative(delta)
}

function onKeydown(event: KeyboardEvent): void {
  const target = event.target
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) return
  const delta = keyTurnDelta(mode.value, event.key)
  if (delta === 0) return
  event.preventDefault()
  goRelative(delta)
}

/** 点击左右热区翻页；连续模式跳到目标页并居中。 */
function onReaderClick(event: MouseEvent): void {
  if (!clickToTurn.value || event.button !== 0) return
  if (suppressClick) {
    suppressClick = false
    return
  }
  const container = scrollElement
  if (!container) return
  const rect = container.getBoundingClientRect()
  if (rect.width <= 0) return
  const delta = clickTurnDelta(
    mode.value,
    (event.clientX - rect.left) / rect.width,
    reverseClick.value,
  )
  if (delta !== 0) goRelative(delta)
}

// ---------- 全屏 ----------

function toggleFullscreen(): void {
  const element = readerRoot.value
  if (!element) return
  if (document.fullscreenElement) {
    void document.exitFullscreen()
  } else {
    element.requestFullscreen().catch((fullscreenError) => {
      // 浏览器拒绝全屏（权限或非用户手势）时保持原状态即可
      console.warn('进入全屏失败', fullscreenError)
    })
  }
}

function onFullscreenChange(): void {
  fullscreen.value = document.fullscreenElement !== null
}

// ---------- 进度同步 ----------

let progressSync: ProgressSync | null = null

watch(pageNumber, () => {
  if (progressSync) progressSync.schedule()
})

function onVisibilityChange(): void {
  if (document.visibilityState === 'hidden') {
    void progressSync?.flush(true)
  }
}

function retryProgress(): void {
  void progressSync?.retry()
}

/** 读取服务端进度；401 跳转登录，其他失败明确标记但不阻塞阅读。 */
async function fetchProgress(): Promise<ReadingProgress | null> {
  try {
    const progress = await getReadingProgress(fileId)
    progressLoadFailed.value = false
    return progress
  } catch (progressError) {
    if (progressError instanceof ApiError && progressError.status === 401) {
      redirectToLogin()
      return null
    }
    // 读取失败不阻塞阅读，但明确标记，可重试；期间新进度仍会写入
    progressLoadFailed.value = true
    return null
  }
}

/** 把已读取的进度应用到当前页码；页数变化时夹紧到有效范围。 */
function applyProgress(progress: ReadingProgress | null): void {
  if (!progress) return
  const totalPages = pageCount.value
  let target = 1
  if (progress.page_number > totalPages) {
    // 数据库进度超过实际页数（文件被替换等）时回到最后一页
    target = totalPages
  } else if (progress.page_number >= 1) {
    target = progress.page_number
  }
  goToPage(target)
}

async function reloadProgress(): Promise<void> {
  applyProgress(await fetchProgress())
}

/** 页数在 PDF 加载后立即同步，失败时显示具体错误并允许重试。 */
async function syncPageCount(): Promise<void> {
  pageCountSyncError.value = ''
  try {
    await updateFilePageCount(fileId, pageCount.value)
  } catch (syncError) {
    pageCountSyncError.value = errorMessage(syncError)
  }
}

// ---------- 初始化与销毁 ----------

function redirectToLogin(): void {
  void router.replace({ name: 'login', query: { redirect: route.fullPath } })
}

async function loadBaseSizes(totalPages: number): Promise<PageBaseSize[]> {
  const documentProxy = doc.value
  if (!documentProxy) return []
  const sizes: PageBaseSize[] = []
  for (let page = 1; page <= totalPages; page += 1) {
    const pageProxy = await documentProxy.getPage(page)
    const viewport = pageProxy.getViewport({ scale: 1 })
    sizes.push({ width: viewport.width, height: viewport.height })
    pageProxy.cleanup()
  }
  return sizes
}

function startProgressSync(): void {
  // 进度服务在恢复页码之后创建：首次恢复不触发写回
  progressSync = createProgressSync({
    fileId,
    getPage: () => pageNumber.value,
    getPageCount: () => pageCount.value,
    onStateChange: (state) => {
      progressState.value = state
    },
  })
}

/** 后台补全首页尺寸；不阻塞 loading，失败时继续使用 probe 页占位。 */
function supplementFirstPageSize(): void {
  void loadPageImageSize(fileId, 1)
    .then((size) => {
      if (!size) return
      const updated = baseSizes.value.slice()
      updated[0] = size
      baseSizes.value = updated
    })
    .catch(() => {
      // 后台补尺寸失败时保持 probe 页占位，不影响阅读
    })
}

/** 图片型路径：只用 <img> 渲染，不加载 PDF.js，也不使用渲染窗口。 */
async function initializeImageMode(
  progress: ReadingProgress,
  probeSize: PageBaseSize,
): Promise<void> {
  imageMode.value = true
  pageCount.value = progress.page_count
  const sizes: Array<PageBaseSize | null> = Array.from(
    { length: pageCount.value },
    () => null,
  )
  const target = Math.min(Math.max(progress.page_number, 1), pageCount.value)
  sizes[target - 1] = probeSize
  probeBaseSize.value = probeSize
  baseSizes.value = sizes
  pageNumber.value = target
  startProgressSync()
  // probe 已拿到当前页尺寸，立即结束转圈；其余页先用 probe 尺寸占位
  loading.value = false
  await nextTick()
  if (continuous.value) {
    scrollToPage(pageNumber.value)
  }
  if (target !== 1) {
    // 首页真实尺寸不阻塞打开，后台补全后由 computed 自动重算布局
    supplementFirstPageSize()
  }
}

/** PDF.js 回退路径：非图片型 PDF 保留原有 Canvas 渲染与全量尺寸读取。 */
async function initializePdfMode(progress: ReadingProgress | null): Promise<void> {
  imageMode.value = false
  const loadError = await load(fileId)
  if (loadError) {
    loading.value = false
    if (loadError.type === 'auth') {
      redirectToLogin()
      return
    }
    error.value = loadError
    return
  }
  const documentProxy = doc.value
  if (!documentProxy) {
    loading.value = false
    error.value = { type: 'unknown', message: 'PDF 加载失败，请重试' }
    return
  }
  pageCount.value = documentProxy.numPages
  await syncPageCount()
  try {
    baseSizes.value = await loadBaseSizes(documentProxy.numPages)
  } catch (layoutError) {
    loading.value = false
    error.value = mapPdfError(layoutError)
    return
  }
  applyProgress(progress)
  startProgressSync()
  loading.value = false
  await nextTick()
  if (continuous.value) {
    scrollToPage(pageNumber.value)
  }
  void renderWindow()
}

async function initialize(): Promise<void> {
  loading.value = true
  error.value = null
  progressLoadFailed.value = false
  imageMode.value = false
  pageCount.value = 0
  baseSizes.value = []
  probeBaseSize.value = null
  loadedPages.value = new Set()

  // 设置与进度互不依赖，并行请求以重叠网络等待；probe 依赖进度页码
  const [settingsLoaded, progress] = await Promise.all([
    loadReaderSettings(),
    fetchProgress(),
  ])
  if (!settingsLoaded) {
    loading.value = false
    return
  }

  // 首次尺寸请求即探测：200 进入图片型路径，404/415 回退 PDF.js
  const probePage = progress?.page_number ?? 1
  try {
    const probe = await probePageImage(fileId, probePage)
    if (probe.kind === 'image' && progress && progress.page_count > 0) {
      await initializeImageMode(progress, probe.size)
      return
    }
  } catch (probeError) {
    if (probeError instanceof ApiError && probeError.status === 401) {
      redirectToLogin()
      loading.value = false
      return
    }
    // 探测失败不直接报错：回退 PDF.js，由其给出统一的中文错误提示
  }
  await initializePdfMode(progress)
}

function goBack(): void {
  if (from) {
    void router.push(from)
  } else {
    void router.push({ name: 'library' })
  }
}

onBeforeRouteLeave(() => {
  void progressSync?.flush(true)
})

onBeforeUnmount(() => {
  void progressSync?.flush(true)
  progressSync?.dispose()
  releaseAll()
  void destroy()
  cancelHorizontalSnap()
  if (scrollRaf !== null) window.cancelAnimationFrame(scrollRaf)
  if (suppressClickTimer !== null) window.clearTimeout(suppressClickTimer)
  window.removeEventListener('keydown', onKeydown)
  document.removeEventListener('visibilitychange', onVisibilityChange)
  document.removeEventListener('fullscreenchange', onFullscreenChange)
})

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  document.addEventListener('visibilitychange', onVisibilityChange)
  document.addEventListener('fullscreenchange', onFullscreenChange)
  void initialize()
})
</script>

<template>
  <div
    ref="readerRoot"
    class="reader-root"
    :class="{ 'reader-root--dark': dark }"
  >
    <v-alert v-if="pageCountSyncError" type="error" variant="tonal" class="ma-2">
      漫画实际页数同步失败：{{ pageCountSyncError }}
      <template #append><v-btn variant="text" size="small" @click="syncPageCount">重试</v-btn></template>
    </v-alert>
    <v-alert
      v-if="settingsError"
      type="warning"
      variant="tonal"
      closable
      class="ma-2"
      @click:close="settingsError = ''"
    >
      {{ settingsError }}
    </v-alert>
    <ReaderToolbar
      :page-number="pageNumber"
      :page-count="pageCount"
      :mode="mode"
      :continuous="continuous"
      :click-to-turn="clickToTurn"
      :reverse-click="reverseClick"
      :prefetch-pages="prefetchPages"
      :zoom-mode="zoomMode"
      :zoom-percent="Math.round(scale * 100)"
      :dark="dark"
      :fullscreen="fullscreen"
      :progress-state="progressState"
      :progress-load-failed="progressLoadFailed"
      :disabled="loading || error !== null"
      :menu-attach="readerRoot ?? undefined"
      @back="goBack"
      @go="goToPage"
      @update:mode="setMode"
      @update:continuous="setContinuous"
      @update:click-to-turn="setClickToTurn"
      @update:reverse-click="setReverseClick"
      @update:prefetch-pages="setPrefetchPages"
      @update:zoom-mode="setZoomMode"
      @zoom-percent="setZoomPercent"
      @update:dark="setDark"
      @toggle-fullscreen="toggleFullscreen"
      @retry-progress="retryProgress"
      @reload-progress="reloadProgress"
    />

    <div v-if="error" class="reader-status">
      <v-icon size="56" color="warning">mdi-alert-circle-outline</v-icon>
      <p class="text-body-1 mt-3 text-center">{{ error.message }}</p>
      <div class="d-flex flex-wrap justify-center ga-2 mt-4">
        <v-btn color="primary" prepend-icon="mdi-refresh" @click="initialize">重试</v-btn>
        <v-btn variant="tonal" prepend-icon="mdi-arrow-left" @click="goBack">返回</v-btn>
        <v-btn variant="tonal" prepend-icon="mdi-download" :href="downloadUrl">下载 PDF</v-btn>
      </div>
    </div>

    <div v-else-if="loading" class="reader-status">
      <v-progress-circular indeterminate color="primary" size="48" />
      <p class="text-body-2 mt-3">正在加载漫画…</p>
    </div>

    <!-- 不连续：一次一页，按模式响应滑动、键盘与点击翻页 -->
    <div
      v-else-if="!continuous"
      v-reader-size
      v-reader-scroll
      class="reader-scroll"
      @wheel="onWheel"
      @touchstart.passive="onTouchStart"
      @touchend="onTouchEnd"
      @click="onReaderClick"
    >
      <div class="reader-single">
        <img
          v-if="imageMode"
          :key="`image-${pageNumber}`"
          :src="pageImageUrl(fileId, pageNumber)"
          :style="pageStyle(pageNumber)"
          class="reader-page-image"
          :class="{ 'reader-page-image--loading': !isPageLoaded(pageNumber) }"
          :alt="`第 ${pageNumber} 页`"
          @load="onPageLoad(pageNumber, $event)"
        >
        <canvas v-else :key="pageNumber" v-reader-canvas="{ pageNumber }" />
      </div>
    </div>

    <!-- 连排：图片型按预加载窗口挂载 <img>；PDF.js 回退路径挂载 Canvas -->
    <div
      v-else
      v-reader-size
      v-reader-scroll
      class="reader-scroll"
      :class="{ 'reader-scroll--horizontal': horizontal }"
      @wheel="onWheel"
      @click="onReaderClick"
    >
      <div
        class="reader-pages"
        :class="{
          'reader-pages--horizontal': horizontal,
          'reader-pages--reverse': mangaDirection,
        }"
        :style="{ '--reader-page-gap': `${pageGap(true)}px` }"
      >
        <div
          v-for="(pageSize, index) in pageSizes"
          :key="index + 1"
          class="reader-page"
          :data-reader-page="index + 1"
          :style="{ width: `${pageSize.width}px`, height: `${pageSize.height}px` }"
        >
          <img
            v-if="imageMode && windowPages.includes(index + 1)"
            :src="pageImageUrl(fileId, index + 1)"
            class="reader-page-image"
            :class="{ 'reader-page-image--loading': !isPageLoaded(index + 1) }"
            :alt="`第 ${index + 1} 页`"
            @load="onPageLoad(index + 1, $event)"
          >
          <canvas
            v-else-if="!imageMode && windowPages.includes(index + 1)"
            v-reader-canvas="{ pageNumber: index + 1 }"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.reader-root {
  display: flex;
  flex-direction: column;
  height: 100dvh;
  overflow: hidden;
  background: #eceff1;
  transition: background-color 0.2s ease;
}

.reader-root--dark {
  background: #101214;
}

.reader-status {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.reader-scroll {
  position: relative;
  flex: 1 1 auto;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  -webkit-overflow-scrolling: touch;
}

.reader-scroll--horizontal {
  overflow-x: auto;
  overflow-y: hidden;
}

.reader-single {
  display: flex;
  min-height: 100%;
  padding: 16px;
  box-sizing: border-box;
}

/* margin:auto 让小于容器时居中、大于容器时顶部可见不被裁剪 */
.reader-single canvas {
  margin: auto;
  max-width: 100%;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.25);
}

.reader-single .reader-page-image {
  margin: auto;
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.25);
}

/* 当前页图片出图前固定白色占位，不跟随深色主题变化 */
.reader-page-image--loading {
  background: #ffffff;
}

.reader-pages {
  --reader-page-gap: 0px;
  box-sizing: border-box;
  width: 100%;
  padding: var(--reader-page-gap) 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--reader-page-gap);
}

.reader-pages--horizontal {
  width: max-content;
  min-width: 100%;
  height: 100%;
  padding: 0 var(--reader-page-gap);
  flex-direction: row;
  align-items: center;
}

/* 日漫连排：首页在右，滚动方向与普通模式相反 */
.reader-pages--reverse {
  flex-direction: row-reverse;
}

.reader-page {
  flex: 0 0 auto;
  display: flex;
  justify-content: center;
}

.reader-page canvas,
.reader-page .reader-page-image {
  max-width: 100%;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.25);
}

.reader-page .reader-page-image {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
</style>
