<script setup lang="ts">
/**
 * PDF 在线阅读器：单页/连续滚动、缩放、跳页、全屏、深色背景与进度同步。
 *
 * 渲染只覆盖当前页 ±1，离开窗口释放 Canvas；缩放/翻页取消过期渲染任务。
 * 进度 1 秒防抖写入，页面隐藏/离开时 keepalive 立即刷新；失败明确提示
 * 「进度未同步」并可重试，不阻塞阅读。
 */

import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch, type Directive } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'

import { ApiError, errorMessage } from '@/api/client'
import { fileDownloadUrl, getReadingProgress, updateFilePageCount } from '@/api/files'
import ReaderToolbar from './ReaderToolbar.vue'
import {
  createProgressSync,
  type ProgressSync,
  type ProgressSyncState,
} from './progressSync'
import {
  computeFitScale,
  windowPagesFor,
  type PageBaseSize,
  type ReaderMode,
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
const mode = ref<ReaderMode>('single')
const zoomMode = ref<ZoomMode>('fit-width')
const customScale = ref(1)
const fullscreen = ref(false)
const progressState = ref<ProgressSyncState>('synced')
const progressLoadFailed = ref(false)
const pageCountSyncError = ref('')
const baseSizes = ref<PageBaseSize[]>([])
const containerWidth = ref(0)
const containerHeight = ref(0)

const DARK_BACKGROUND_KEY = 'jmbot-reader-dark'
const PAGE_PADDING = 16
const PAGE_GAP = 12

const dark = ref(window.localStorage.getItem(DARK_BACKGROUND_KEY) === '1')
watch(dark, (value) => {
  window.localStorage.setItem(DARK_BACKGROUND_KEY, value ? '1' : '0')
})

const downloadUrl = computed(() => fileDownloadUrl(fileId))

// ---------- 缩放 ----------

/** 适应计算的目标页面尺寸：单页用当前页，连续模式用最大页保证不溢出。 */
const fitBase = computed<PageBaseSize | null>(() => {
  const sizes = baseSizes.value
  if (sizes.length === 0) return null
  if (mode.value === 'single') {
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

// ---------- 连续模式布局 ----------

interface PageLayout {
  pageNumber: number
  top: number
  height: number
  width: number
}

const pageLayouts = computed<PageLayout[]>(() => {
  const layouts: PageLayout[] = []
  const currentScale = scale.value
  let top = PAGE_GAP
  for (let index = 0; index < baseSizes.value.length; index += 1) {
    const base = baseSizes.value[index]
    const width = base.width * currentScale
    const height = base.height * currentScale
    layouts.push({ pageNumber: index + 1, top, height, width })
    top += height + PAGE_GAP
  }
  return layouts
})

const totalHeight = computed(() => {
  const layouts = pageLayouts.value
  const last = layouts[layouts.length - 1]
  return last ? last.top + last.height + PAGE_GAP : 0
})

const windowPages = computed(() =>
  mode.value === 'single'
    ? [pageNumber.value]
    : windowPagesFor(pageNumber.value, pageCount.value),
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

function scrollToPage(target: number, behavior: 'auto' | 'smooth' = 'auto'): void {
  const layout = pageLayouts.value[target - 1]
  const container = scrollElement
  if (!layout || !container) return
  container.scrollTo({ top: layout.top, behavior })
}

let scrollElement: HTMLElement | null = null
let scrollRaf: number | null = null

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

function onScroll(): void {
  if (scrollRaf !== null) return
  scrollRaf = window.requestAnimationFrame(() => {
    scrollRaf = null
    updateCurrentFromScroll()
  })
}

/** 连续模式：取视口中心所在的页面为当前页。 */
function updateCurrentFromScroll(): void {
  const container = scrollElement
  if (!container || mode.value !== 'continuous') return
  const center = container.scrollTop + container.clientHeight / 2
  let current = 1
  for (const layout of pageLayouts.value) {
    const bottom = layout.top + layout.height
    if (center < bottom) {
      current = layout.pageNumber
      break
    }
    current = layout.pageNumber
  }
  if (current !== pageNumber.value) pageNumber.value = current
}

function goToPage(target: number): void {
  if (pageCount.value === 0) return
  const clamped = Math.min(Math.max(target, 1), pageCount.value)
  if (mode.value === 'continuous') {
    pageNumber.value = clamped
    void nextTick(() => scrollToPage(clamped))
  } else {
    pageNumber.value = clamped
  }
}

function goRelative(delta: number): void {
  goToPage(pageNumber.value + delta)
}

function setMode(value: ReaderMode): void {
  if (mode.value === value) return
  mode.value = value
  void nextTick(() => {
    if (value === 'continuous') {
      scrollToPage(pageNumber.value)
    } else {
      void renderWindow()
    }
  })
}

function setZoomMode(value: ZoomMode): void {
  zoomMode.value = value
}

function setZoomPercent(percent: number): void {
  customScale.value = percent / 100
  zoomMode.value = 'custom'
}

// ---------- 触摸与键盘 ----------

let touchStart: { x: number; y: number } | null = null

function onTouchStart(event: TouchEvent): void {
  if (mode.value !== 'single') return
  const touch = event.touches[0]
  if (!touch) return
  touchStart = { x: touch.clientX, y: touch.clientY }
}

function onTouchEnd(event: TouchEvent): void {
  if (mode.value !== 'single' || touchStart === null) return
  const touch = event.changedTouches[0]
  const start = touchStart
  touchStart = null
  if (!touch) return
  const deltaX = touch.clientX - start.x
  const deltaY = touch.clientY - start.y
  // 仅在水平方向明显滑动时翻页，避免与垂直滚动冲突
  if (Math.abs(deltaX) < 60 || Math.abs(deltaX) < Math.abs(deltaY) * 1.5) return
  goRelative(deltaX < 0 ? 1 : -1)
}

function onKeydown(event: KeyboardEvent): void {
  const target = event.target
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) return
  if (event.key === 'ArrowLeft') goRelative(-1)
  else if (event.key === 'ArrowRight') goRelative(1)
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
  if (mode.value === 'continuous') {
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
    <ReaderToolbar
      :page-number="pageNumber"
      :page-count="pageCount"
      :mode="mode"
      :zoom-mode="zoomMode"
      :zoom-percent="Math.round(scale * 100)"
      :dark="dark"
      :fullscreen="fullscreen"
      :progress-state="progressState"
      :progress-load-failed="progressLoadFailed"
      :disabled="loading || error !== null"
      @back="goBack"
      @go="goToPage"
      @update:mode="setMode"
      @update:zoom-mode="setZoomMode"
      @zoom-percent="setZoomPercent"
      @update:dark="dark = $event"
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

    <!-- 单页模式：当前页独立居中，支持左右滑动翻页 -->
    <div
      v-else-if="mode === 'single'"
      v-reader-size
      v-reader-scroll
      class="reader-scroll"
      @touchstart.passive="onTouchStart"
      @touchend="onTouchEnd"
    >
      <div class="reader-single">
        <canvas :key="pageNumber" v-reader-canvas="{ pageNumber }" />
      </div>
    </div>

    <!-- 连续滚动：所有页面按布局占位，只渲染当前页 ±1 -->
    <div
      v-else
      v-reader-size
      v-reader-scroll
      class="reader-scroll"
    >
      <div class="reader-pages" :style="{ height: `${totalHeight}px` }">
        <div
          v-for="layout in pageLayouts"
          :key="layout.pageNumber"
          class="reader-page"
          :style="{
            top: `${layout.top}px`,
            width: `${layout.width}px`,
            height: `${layout.height}px`,
          }"
        >
          <canvas
            v-if="windowPages.includes(layout.pageNumber)"
            v-reader-canvas="{ pageNumber: layout.pageNumber }"
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
  position: relative;
  width: 100%;
}

.reader-page {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  justify-content: center;
}

.reader-page canvas {
  max-width: 100%;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.25);
}
</style>
