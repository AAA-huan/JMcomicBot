<script setup lang="ts">
/** 阅读器顶部工具栏：返回、页码跳转、缩放、阅读模式、阅读开关、全屏与进度状态。 */

import { computed, ref, watch } from 'vue'
import { useDisplay } from 'vuetify'

import type { ProgressSyncState } from './progressSync'
import {
  PREFETCH_OPTIONS,
  ZOOM_PERCENT_OPTIONS,
  type ReaderMode,
  type ZoomMode,
} from './types'

const props = defineProps<{
  pageNumber: number
  pageCount: number
  mode: ReaderMode
  continuous: boolean
  clickToTurn: boolean
  reverseClick: boolean
  prefetchPages: number
  zoomMode: ZoomMode
  zoomPercent: number
  dark: boolean
  fullscreen: boolean
  progressState: ProgressSyncState
  progressLoadFailed?: boolean
  disabled?: boolean
  /** 菜单挂载点；全屏时挂到阅读器根节点，避免弹层被留在全屏元素之外。 */
  menuAttach?: HTMLElement | string
}>()

const emit = defineEmits<{
  (event: 'back'): void
  (event: 'go', page: number): void
  (event: 'update:mode', mode: ReaderMode): void
  (event: 'update:continuous', continuous: boolean): void
  (event: 'update:click-to-turn', clickToTurn: boolean): void
  (event: 'update:reverse-click', reverseClick: boolean): void
  (event: 'update:prefetch-pages', prefetchPages: number): void
  (event: 'update:zoomMode', mode: ZoomMode): void
  (event: 'zoom-percent', percent: number): void
  (event: 'update:dark', dark: boolean): void
  (event: 'toggle-fullscreen'): void
  (event: 'retry-progress'): void
  (event: 'reload-progress'): void
}>()

interface ModeOption {
  value: ReaderMode
  title: string
  icon: string
}

const MODE_OPTIONS: ModeOption[] = [
  { value: 'normal', title: '普通模式', icon: 'mdi-book-open-page-variant-outline' },
  { value: 'manga', title: '日漫模式', icon: 'mdi-book-open-variant' },
  { value: 'scroll', title: '滚动模式', icon: 'mdi-view-agenda-outline' },
]

const PREFETCH_ITEMS = PREFETCH_OPTIONS.map((value) => ({
  title: value === 0 ? '仅当前页' : `${value} 页`,
  value,
}))
const PREFETCH_HINT = '连续模式当前页前后保留的页数，越大越流畅但更耗内存；手机建议 1-2'

const { mobile } = useDisplay()
const pageInput = ref(String(props.pageNumber))
const menuOpen = ref(false)
const modeMenuOpen = ref(false)
const settingsMenuOpen = ref(false)

const modeOption = computed(
  () => MODE_OPTIONS.find((option) => option.value === props.mode) ?? MODE_OPTIONS[0],
)

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

function selectMode(mode: ReaderMode): void {
  emit('update:mode', mode)
  modeMenuOpen.value = false
  menuOpen.value = false
}

function setContinuous(value: unknown): void {
  emit('update:continuous', Boolean(value))
}

function setClickToTurn(value: unknown): void {
  emit('update:click-to-turn', Boolean(value))
}

function setReverseClick(value: unknown): void {
  emit('update:reverse-click', Boolean(value))
}

function setPrefetchPages(value: unknown): void {
  emit('update:prefetch-pages', Number(value))
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

    <!-- 桌面端直接展示缩放、模式与设置入口 -->
    <template v-if="!mobile">
      <v-menu :attach="menuAttach" location="bottom end">
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

      <v-menu v-model="modeMenuOpen" :attach="menuAttach" location="bottom end">
        <template #activator="{ props: menuProps }">
          <v-btn
            v-bind="menuProps"
            variant="text"
            :prepend-icon="modeOption.icon"
            aria-label="阅读模式"
          >
            {{ modeOption.title }}
          </v-btn>
        </template>
        <v-list density="comfortable">
          <v-list-item
            v-for="option in MODE_OPTIONS"
            :key="option.value"
            :title="option.title"
            :prepend-icon="option.icon"
            :active="mode === option.value"
            @click="selectMode(option.value)"
          />
        </v-list>
      </v-menu>

      <v-menu v-model="settingsMenuOpen" :attach="menuAttach" location="bottom end">
        <template #activator="{ props: menuProps }">
          <v-btn
            v-bind="menuProps"
            icon="mdi-tune"
            variant="text"
            aria-label="阅读设置"
          />
        </template>
        <v-list density="comfortable" min-width="260">
          <v-list-subheader>显示方式</v-list-subheader>
          <div class="px-4 pb-2">
            <v-switch
              :model-value="continuous"
              label="连续翻页"
              color="primary"
              density="compact"
              hide-details
              @update:model-value="setContinuous"
            />
            <v-switch
              :model-value="clickToTurn"
              label="点击翻页"
              color="primary"
              density="compact"
              hide-details
              @update:model-value="setClickToTurn"
            />
            <v-switch
              :model-value="reverseClick"
              label="反转点击翻页"
              color="primary"
              density="compact"
              hide-details
              :disabled="!clickToTurn"
              @update:model-value="setReverseClick"
            />
          </div>
          <v-divider class="my-1" />
          <div class="px-4 py-2">
            <v-switch
              :model-value="dark"
              label="深色背景"
              color="primary"
              density="compact"
              hide-details
              @update:model-value="emit('update:dark', Boolean($event))"
            />
            <v-select
              :model-value="prefetchPages"
              :items="PREFETCH_ITEMS"
              label="预加载页数"
              :hint="PREFETCH_HINT"
              persistent-hint
              color="primary"
              density="compact"
              variant="outlined"
              class="mt-2"
              @update:model-value="setPrefetchPages"
            />
          </div>
        </v-list>
      </v-menu>

      <v-btn
        :icon="fullscreen ? 'mdi-fullscreen-exit' : 'mdi-fullscreen'"
        variant="text"
        :aria-label="fullscreen ? '退出全屏' : '进入全屏'"
        @click="emit('toggle-fullscreen')"
      />
    </template>

    <!-- 移动端收纳进菜单，避免 360px 宽度溢出 -->
    <v-menu
      v-else
      v-model="menuOpen"
      :attach="menuAttach"
      location="bottom end"
    >
      <template #activator="{ props: menuProps }">
        <v-btn
          v-bind="menuProps"
          icon="mdi-dots-vertical"
          variant="text"
          aria-label="阅读设置"
        />
      </template>
      <v-list density="comfortable" min-width="260">
        <v-list-subheader>阅读模式</v-list-subheader>
        <v-list-item
          v-for="option in MODE_OPTIONS"
          :key="option.value"
          :title="option.title"
          :prepend-icon="option.icon"
          :active="mode === option.value"
          @click="selectMode(option.value)"
        />
        <v-divider class="my-1" />
        <v-list-subheader>阅读设置</v-list-subheader>
        <div class="px-4 pb-2">
          <v-switch
            :model-value="continuous"
            label="连续翻页"
            color="primary"
            density="compact"
            hide-details
            @update:model-value="setContinuous"
          />
          <v-switch
            :model-value="clickToTurn"
            label="点击翻页"
            color="primary"
            density="compact"
            hide-details
            @update:model-value="setClickToTurn"
          />
          <v-switch
            :model-value="reverseClick"
            label="反转点击翻页"
            color="primary"
            density="compact"
            hide-details
            :disabled="!clickToTurn"
            @update:model-value="setReverseClick"
          />
          <v-switch
            :model-value="dark"
            label="深色背景"
            color="primary"
            density="compact"
            hide-details
            @update:model-value="emit('update:dark', Boolean($event))"
          />
          <v-select
            :model-value="prefetchPages"
            :items="PREFETCH_ITEMS"
            label="预加载页数"
            :hint="PREFETCH_HINT"
            persistent-hint
            color="primary"
            density="compact"
            variant="outlined"
            class="mt-2"
            @update:model-value="setPrefetchPages"
          />
        </div>
        <v-divider class="my-1" />
        <v-list-subheader>缩放</v-list-subheader>
        <v-list-item title="适应宽度" @click="selectZoom('fit-width')" />
        <v-list-item title="适应页面" @click="selectZoom('fit-page')" />
        <v-divider class="my-1" />
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
