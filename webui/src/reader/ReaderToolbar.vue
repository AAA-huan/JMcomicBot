<script setup lang="ts">
/** 阅读器顶部工具栏：返回、页码跳转、缩放、模式、深色背景、全屏与进度状态。 */

import { ref, watch } from 'vue'
import { useDisplay } from 'vuetify'

import type { ProgressSyncState } from './progressSync'
import { ZOOM_PERCENT_OPTIONS, type ReaderMode, type ZoomMode } from './types'

const props = defineProps<{
  pageNumber: number
  pageCount: number
  mode: ReaderMode
  zoomMode: ZoomMode
  zoomPercent: number
  dark: boolean
  fullscreen: boolean
  progressState: ProgressSyncState
  progressLoadFailed?: boolean
  disabled?: boolean
}>()

const emit = defineEmits<{
  (event: 'back'): void
  (event: 'go', page: number): void
  (event: 'update:mode', mode: ReaderMode): void
  (event: 'update:zoomMode', mode: ZoomMode): void
  (event: 'zoom-percent', percent: number): void
  (event: 'update:dark', dark: boolean): void
  (event: 'toggle-fullscreen'): void
  (event: 'retry-progress'): void
  (event: 'reload-progress'): void
}>()

const { mobile } = useDisplay()
const pageInput = ref(String(props.pageNumber))
const menuOpen = ref(false)

watch(
  () => props.pageNumber,
  (value) => {
    pageInput.value = String(value)
  },
)

function submitPage(): void {
  const parsed = Number.parseInt(pageInput.value, 10)
  if (Number.isNaN(parsed)) {
    pageInput.value = String(props.pageNumber)
    return
  }
  const target = Math.min(Math.max(parsed, 1), props.pageCount)
  pageInput.value = String(target)
  if (target !== props.pageNumber) emit('go', target)
}

function toggleMode(): void {
  emit('update:mode', props.mode === 'single' ? 'continuous' : 'single')
}

function selectZoom(mode: ZoomMode): void {
  emit('update:zoomMode', mode)
  menuOpen.value = false
}

function selectPercent(percent: number): void {
  emit('zoom-percent', percent)
  menuOpen.value = false
}

/** 当前缩放按钮的展示文本。 */
function zoomLabel(): string {
  if (props.zoomMode === 'fit-width') return '适宽'
  if (props.zoomMode === 'fit-page') return '适页'
  return `${props.zoomPercent}%`
}
</script>

<template>
  <v-toolbar density="comfortable" color="surface" class="reader-toolbar" flat>
    <v-btn
      icon="mdi-arrow-left"
      variant="text"
      aria-label="返回"
      @click="emit('back')"
    />

    <div class="d-flex align-center ga-1 ml-1">
      <v-text-field
        v-model="pageInput"
        class="reader-page-input"
        type="text"
        inputmode="numeric"
        hide-details
        density="compact"
        variant="outlined"
        :disabled="disabled"
        aria-label="跳转页码"
        @keydown.enter="submitPage"
        @blur="submitPage"
      />
      <span class="text-body-2 text-medium-emphasis text-no-wrap">/ {{ pageCount }}</span>
    </div>

    <!-- 进度状态：读取/写入失败都必须可见并可重试 -->
    <v-chip
      v-if="progressLoadFailed"
      class="ml-2"
      size="small"
      color="warning"
      variant="tonal"
      prepend-icon="mdi-cloud-question-outline"
    >
      <span v-if="!mobile">进度读取失败</span>
      <v-btn
        icon="mdi-refresh"
        size="small"
        variant="text"
        aria-label="重新读取进度"
        @click="emit('reload-progress')"
      />
    </v-chip>
    <v-chip
      v-else-if="progressState === 'failed'"
      class="ml-2"
      size="small"
      color="warning"
      variant="tonal"
      prepend-icon="mdi-cloud-alert-outline"
    >
      <span v-if="!mobile">进度未同步</span>
      <v-btn
        icon="mdi-refresh"
        size="small"
        variant="text"
        aria-label="重试同步进度"
        @click="emit('retry-progress')"
      />
    </v-chip>
    <v-progress-circular
      v-else-if="progressState === 'pending'"
      class="ml-2"
      size="18"
      width="2"
      indeterminate
      aria-label="进度同步中"
    />

    <v-spacer />

    <!-- 桌面端直接展示操作按钮 -->
    <template v-if="!mobile">
      <v-menu location="bottom end">
        <template #activator="{ props: menuProps }">
          <v-btn
            v-bind="menuProps"
            variant="text"
            :prepend-icon="zoomMode === 'custom' ? 'mdi-magnify-plus-outline' : 'mdi-fit-to-screen-outline'"
          >
            {{ zoomLabel() }}
          </v-btn>
        </template>
        <v-list density="comfortable">
          <v-list-item title="适应宽度" @click="selectZoom('fit-width')" />
          <v-list-item title="适应页面" @click="selectZoom('fit-page')" />
          <v-divider class="my-1" />
          <v-list-item
            v-for="percent in ZOOM_PERCENT_OPTIONS"
            :key="percent"
            :title="`${percent}%`"
            @click="selectPercent(percent)"
          />
        </v-list>
      </v-menu>

      <v-btn
        :icon="mode === 'single' ? 'mdi-file-document-outline' : 'mdi-view-agenda-outline'"
        variant="text"
        :aria-label="mode === 'single' ? '切换到连续滚动' : '切换到单页模式'"
        @click="toggleMode"
      />

      <v-btn
        :icon="dark ? 'mdi-white-balance-sunny' : 'mdi-weather-night'"
        variant="text"
        :aria-label="dark ? '切换到浅色背景' : '切换到深色背景'"
        @click="emit('update:dark', !dark)"
      />

      <v-btn
        :icon="fullscreen ? 'mdi-fullscreen-exit' : 'mdi-fullscreen'"
        variant="text"
        :aria-label="fullscreen ? '退出全屏' : '进入全屏'"
        @click="emit('toggle-fullscreen')"
      />
    </template>

    <!-- 移动端收纳进菜单，避免 360px 宽度溢出 -->
    <v-menu v-else v-model="menuOpen" location="bottom end">
      <template #activator="{ props: menuProps }">
        <v-btn
          v-bind="menuProps"
          icon="mdi-dots-vertical"
          variant="text"
          aria-label="阅读设置"
        />
      </template>
      <v-list density="comfortable">
        <v-list-subheader>缩放</v-list-subheader>
        <v-list-item title="适应宽度" @click="selectZoom('fit-width')" />
        <v-list-item title="适应页面" @click="selectZoom('fit-page')" />
        <v-list-item
          v-for="percent in ZOOM_PERCENT_OPTIONS"
          :key="percent"
          :title="`${percent}%`"
          @click="selectPercent(percent)"
        />
        <v-divider class="my-1" />
        <v-list-item
          :title="mode === 'single' ? '连续滚动' : '单页模式'"
          :prepend-icon="mode === 'single' ? 'mdi-view-agenda-outline' : 'mdi-file-document-outline'"
          @click="emit('update:mode', mode === 'single' ? 'continuous' : 'single'); menuOpen = false"
        />
        <v-list-item
          :title="dark ? '浅色背景' : '深色背景'"
          :prepend-icon="dark ? 'mdi-white-balance-sunny' : 'mdi-weather-night'"
          @click="emit('update:dark', !dark); menuOpen = false"
        />
        <v-list-item
          :title="fullscreen ? '退出全屏' : '进入全屏'"
          :prepend-icon="fullscreen ? 'mdi-fullscreen-exit' : 'mdi-fullscreen'"
          @click="emit('toggle-fullscreen'); menuOpen = false"
        />
      </v-list>
    </v-menu>
  </v-toolbar>
</template>

<style scoped>
.reader-toolbar {
  flex: 0 0 auto;
  border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
}

.reader-page-input {
  max-width: 72px;
  min-width: 56px;
}

/* 移动端隐藏输入框的上下箭头 */
.reader-page-input :deep(input) {
  text-align: center;
}
</style>
