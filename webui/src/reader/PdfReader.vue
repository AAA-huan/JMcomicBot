<script setup lang="ts">
/**
 * PDF 在线阅读器：单页/连排滚动、缩放、跳页、全屏、阅读设置与进度同步。
 *
 * 渲染只覆盖当前页 ±1，离开窗口释放 Canvas；缩放/翻页取消过期渲染任务。
 * 阅读模式、连续显示、点击翻页与深色背景统一保存在后端，工具栏改动即时
 * 同步并在失败时回滚。进度 1 秒防抖写入，页面隐藏/离开时 keepalive 立即
 * 刷新；失败明确提示「进度未同步」并可重试，不阻塞阅读。
 */

import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch, type Directive } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'

import { ApiError, errorMessage } from '@/api/client'
import { fileDownloadUrl, getReadingProgress, updateFilePageCount } from '@/api/files'
import { getReaderSettings, updateReaderSettings } from '@/api/reader'
import ReaderToolbar from './ReaderToolbar.vue'
import {
  createProgressSync,
  type ProgressSync,
  type ProgressSyncState,
} from './progressSync'
import {
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
const mode = ref<ReaderMode>('normal')
const continuous = ref(false)
const clickToTurn = ref(false)
const reverseClick = ref(false)
const dark = ref(false)
const settingsError = ref('')
const zoomMode = ref<ZoomMode>('fit-width')
const customScale = ref(1)
const fullscreen = ref(false)
const progressState = ref<ProgressSyncState>('synced')
const progressLoadFailed = ref(false)
const pageCountSyncError = ref('')
const baseSizes = ref<PageBaseSize[]>([])
const containerWidth = ref(0)
const containerHeight = ref(0)

const PAGE_PADDING = 16

const downloadUrl = computed(() => fileDownloadUrl(fileId))
const horizontal = computed(() => isHorizontalScroll(mode.value))

// ---------- 阅读设置 ----------

/** 把后端设置应用到阅读器状态。 */
function applyReaderSettings(settings: ReadingSettings): void {
  mode.value = settings.reading_mode
  continuous.value = settings.continuous
  clickToTurn.value = settings.click_to_turn
  reverseClick.value = settings.reverse_click
  dark.value = settings.dark_background
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

// ---------- 缩放 ----------

/** 适应计算的目标页面尺寸：单页用当前页，连排用最大页保证不溢出。 */
const fitBase = computed<PageBaseSize | null>(() => {
  const sizes = baseSizes.value
  if (sizes.length === 0) return null
  if (!continuous.value) {
    const current = sizes[pageNumber.value - 1]
    return current ?? null
  }
  let width = 0
  let height = 0
  for (const size of sizes) {
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

/** 连排占位尺寸，未进入渲染窗口的页面仍保留布局高度/宽度。 */
const pageSizes = computed<PageBaseSize[]>(() =>
  baseSizes.value.map((size) => ({
    width: size.width * scale.value,
    height: size.height * scale.value,
  })),
)

const windowPages = computed(() =>
  continuous.value
    ? windowPagesFor(pageNumber.value, pageCount.value)
    : [pageNumber.value],
)

// ---------- 渲染 ----------

async function renderWindow(): Promise<void> {
  if (!doc.value || baseSizes.value.length === 0) return
  try {
    await syncWindow(windowPages.value, scale.value)
  } catch (renderError) {
    error.value = mapPdfError(renderError)
  }
}

watch(
  [windowPages, scale],
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

let scrollElement: HTMLElement | null = null
let scrollRaf: number | null = null
let snapTimer: number | null = null

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

/** 在连排容器内查找指定页的占位元素。 */
function pageElement(target: number): HTMLElement | null {
  return (
    scrollElement?.querySelector<HTMLElement>(
      `[data-reader-page="${target}"]`,
    ) ?? null
  )
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
 * 普通/日漫横排把页面居中，保证停止滑动或点击后当前页完整落在视口中央；
 * 滚动模式保持原有行为，把目标页顶部对齐到容器起始位置。
 */
function scrollToPage(target: number, behavior: 'auto' | 'smooth' = 'auto'): void {
  cancelHorizontalSnap()
  const container = scrollElement
  const element = pageElement(target)
  if (!container || !element) return
  if (horizontal.value) {
    const centeredLeft =
      element.offsetLeft +
      element.offsetWidth / 2 -
      container.clientWidth / 2
    const maxLeft = Math.max(container.scrollWidth - container.clientWidth, 0)
    container.scrollTo({
      left: Math.min(Math.max(centeredLeft, 0), maxLeft),
      behavior,
    })
  } else {
    const gap = pageGap(true)
    container.scrollTo({
      top: Math.max(element.offsetTop - gap, 0),
      behavior,
    })
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

/** 连排模式：取视口中心所在的页面为当前页。 */
function updateCurrentFromScroll(): void {
  const container = scrollElement
  if (!container || !continuous.value) return
  const containerRect = container.getBoundingClientRect()
  const centerX = containerRect.left + container.clientWidth / 2
  const centerY = containerRect.top + container.clientHeight / 2
  let current = pageNumber.value
  let nearestDistance = Number.POSITIVE_INFINITY
  for (const element of container.querySelectorAll<HTMLElement>(
    '[data-reader-page]',
  )) {
    const page = Number(element.dataset.readerPage)
    if (!Number.isInteger(page)) continue
    const rect = element.getBoundingClientRect()
    const inside = horizontal.value
      ? centerX >= rect.left && centerX <= rect.right
      : centerY >= rect.top && centerY <= rect.bottom
    if (inside) {
      current = page
      break
    }
    const pageCenter = horizontal.value
      ? rect.left + rect.width / 2
      : rect.top + rect.height / 2
    const distance = Math.abs(
      (horizontal.value ? centerX : centerY) - pageCenter,
    )
    if (distance < nearestDistance) {
      nearestDistance = distance
      current = page
    }
  }
  if (current !== pageNumber.value) pageNumber.value = current
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

// ---------- 触摸、键盘与点击翻页 ----------

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

/** 读取服务端进度并跳转；读取失败明确提示而不是假装从头开始。 */
async function applyProgress(): Promise<void> {
  const totalPages = pageCount.value
  let target = 1
  try {
    const progress = await getReadingProgress(fileId)
    if (progress.page_number > totalPages) {
      // 数据库进度超过实际页数（文件被替换等）时回到最后一页
      target = totalPages
    } else if (progress.page_number >= 1) {
      target = progress.page_number
    }
    progressLoadFailed.value = false
  } catch (progressError) {
    if (progressError instanceof ApiError && progressError.status === 401) {
      redirectToLogin()
      return
    }
    // 读取失败不阻塞阅读，但明确标记，可重试；期间新进度仍会写入
    progressLoadFailed.value = true
    return
  }
  goToPage(target)
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

async function reloadProgress(): Promise<void> {
  await applyProgress()
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

async function initialize(): Promise<void> {
  loading.value = true
  error.value = null
  progressLoadFailed.value = false
  if (!(await loadReaderSettings())) {
    loading.value = false
    return
  }
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
  // 进度服务在恢复页码之后创建：首次恢复不触发写回
  await applyProgress()
  progressSync = createProgressSync({
    fileId,
    getPage: () => pageNumber.value,
    getPageCount: () => pageCount.value,
    onStateChange: (state) => {
      progressState.value = state
    },
  })
  loading.value = false
  await nextTick()
  if (continuous.value) {
    scrollToPage(pageNumber.value)
  }
  void renderWindow()
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
      <p class="text-body-2 mt-3">正在加载 PDF…</p>
    </div>

    <!-- 不连续：一次一页，按模式响应滑动、键盘与点击翻页 -->
    <div
      v-else-if="!continuous"
      v-reader-size
      v-reader-scroll
      class="reader-scroll"
      @touchstart.passive="onTouchStart"
      @touchend="onTouchEnd"
      @click="onReaderClick"
    >
      <div class="reader-single">
        <canvas :key="pageNumber" v-reader-canvas="{ pageNumber }" />
      </div>
    </div>

    <!-- 连排：普通/日漫水平横排，滚动模式垂直纵排；只渲染当前页 ±1 -->
    <div
      v-else
      v-reader-size
      v-reader-scroll
      class="reader-scroll"
      :class="{ 'reader-scroll--horizontal': horizontal }"
      @click="onReaderClick"
    >
      <div
        class="reader-pages"
        :class="{
          'reader-pages--horizontal': horizontal,
          'reader-pages--reverse': mode === 'manga',
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
          <canvas
            v-if="windowPages.includes(index + 1)"
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

.reader-page canvas {
  max-width: 100%;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.25);
}
</style>
