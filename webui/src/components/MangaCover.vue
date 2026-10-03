<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { RenderTask } from 'pdfjs-dist'

import { usePdfDocument } from '@/reader/usePdfDocument'

const props = defineProps<{ fileId: number }>()
const canvas = ref<HTMLCanvasElement | null>(null)
const loading = ref(true)
const error = ref('')
const pdf = usePdfDocument()
let disposed = false
let renderTask: RenderTask | null = null

/** 只渲染第一页，不写入阅读进度，预览不会进入阅读历史。 */
async function renderCover(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const loadError = await pdf.load(props.fileId)
    if (disposed) return
    if (loadError) {
      error.value = loadError.message
      return
    }
    const document = pdf.doc.value
    if (!document) return
    const page = await document.getPage(1)
    if (disposed || !canvas.value) return
    const original = page.getViewport({ scale: 1 })
    const viewport = page.getViewport({ scale: 640 / original.width })
    canvas.value.width = viewport.width
    canvas.value.height = viewport.height
    renderTask = page.render({ canvas: canvas.value, viewport })
    await renderTask.promise
    page.cleanup()
  } catch (err) {
    if (!disposed) {
      console.error('漫画封面预览失败', err)
      error.value = '封面预览失败，请重试'
    }
  } finally {
    if (!disposed) loading.value = false
  }
}

onMounted(renderCover)
onBeforeUnmount(() => {
  disposed = true
  renderTask?.cancel()
  void pdf.destroy()
})
</script>

<template>
  <div class="mb-4">
    <div class="text-subtitle-2 mb-2">封面预览 · 第一页</div>
    <v-progress-linear v-if="loading" indeterminate class="mb-2" />
    <v-alert v-if="error" type="error" variant="tonal">
      {{ error }}
      <template #append>
        <v-btn variant="text" size="small" @click="renderCover">重试</v-btn>
      </template>
    </v-alert>
    <canvas
      v-show="!loading && !error"
      ref="canvas"
      role="img"
      aria-label="漫画第一页封面预览"
      style="display: block; max-width: 100%; width: 320px; height: auto"
    />
  </div>
</template>
