<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { errorMessage } from '@/api/client'
import { useConnectionSubscription, useEventSubscription } from '@/api/eventStream'
import { getDownloadProgress, requestDownloads } from '@/api/tasks'
import EmptyState from '@/components/EmptyState.vue'
import type {
  DownloadChapterProgress,
  DownloadProgressEventData,
  DownloadProgressSnapshot,
} from '@/types/api'
import { formatElapsed, parseBackendTime, parseMangaIds } from '@/utils/format'

const downloadInput = ref('')
const submitting = ref(false)
const requestError = ref('')
const requestNotice = ref('')

const snapshot = ref<DownloadProgressSnapshot | null>(null)
const progressError = ref('')
const now = ref(Date.now())
let tickTimer: number | null = null

const albumPercent = computed(() => {
  const current = snapshot.value
  if (!current || current.album_total <= 0) return 0
  return Math.min(100, Math.round((current.album_done / current.album_total) * 100))
})

const imageDone = computed(() =>
  snapshot.value?.chapters.reduce((total, chapter) => total + chapter.done, 0) ?? 0,
)

const imageTotal = computed(() =>
  snapshot.value?.chapters.reduce((total, chapter) => total + chapter.total, 0) ?? 0,
)

const elapsedSeconds = computed(() => {
  const current = snapshot.value
  if (!current) return 0
  const started = parseBackendTime(current.started_at).getTime()
  const ended = current.finished
    ? parseBackendTime(current.updated_at).getTime()
    : now.value
  if (Number.isNaN(started) || Number.isNaN(ended)) return 0
  return Math.max(0, (ended - started) / 1000)
})

const elapsedText = computed(() => formatElapsed(elapsedSeconds.value))

const statusLabel = computed(() => {
  const current = snapshot.value
  if (!current) return ''
  if (!current.finished) return '正在下载'
  return current.succeeded ? '下载完成' : '下载未完成'
})

const statusColor = computed(() => {
  const current = snapshot.value
  if (!current || !current.finished) return 'primary'
  return current.succeeded ? 'success' : 'warning'
})

/** 章节完成显示成功，整体结束但章节缺图时显示警告。 */
function chapterIcon(chapter: DownloadChapterProgress): string {
  if (chapter.finished) return 'mdi-check-circle'
  if (snapshot.value?.finished) return 'mdi-alert-circle'
  return ''
}

function chapterIconColor(chapter: DownloadChapterProgress): string {
  return chapter.finished ? 'success' : 'warning'
}

function chapterPercent(chapter: DownloadChapterProgress): number {
  if (chapter.total <= 0) return 0
  return Math.min(100, Math.round((chapter.done / chapter.total) * 100))
}

async function loadProgress(): Promise<void> {
  progressError.value = ''
  try {
    const result = await getDownloadProgress()
    snapshot.value = result.active
  } catch (err) {
    progressError.value = errorMessage(err)
  }
}

async function submitDownload(): Promise<void> {
  if (submitting.value) return
  requestError.value = ''
  requestNotice.value = ''
  const mangaIds = parseMangaIds(downloadInput.value)
  if (mangaIds.length === 0) {
    requestError.value = '请输入至少一个漫画 ID'
    return
  }
  if (mangaIds.length > 100) {
    requestError.value = '单次最多请求 100 个漫画'
    return
  }

  submitting.value = true
  try {
    const result = await requestDownloads(mangaIds)
    const parts = [`已入队 ${result.queued_count} 个`]
    if (result.duplicate_count > 0) {
      const duplicates = result.items
        .filter((item) => item.status === 'duplicate')
        .map((item) => item.manga_id)
      parts.push(
        `${result.duplicate_count} 个已有活动任务（${duplicates.join('、')}）`,
      )
    }
    requestNotice.value = parts.join('，')
    downloadInput.value = ''
  } catch (err) {
    requestError.value = errorMessage(err)
  } finally {
    submitting.value = false
  }
}

useEventSubscription((event) => {
  if (event.type !== 'download.progress') return
  snapshot.value = event.data as DownloadProgressEventData
})

// WebSocket 重连后重新读取快照，补齐断线期间遗漏的事件
useConnectionSubscription(() => {
  void loadProgress()
})

onMounted(() => {
  void loadProgress()
  tickTimer = window.setInterval(() => {
    now.value = Date.now()
  }, 1000)
})

onBeforeUnmount(() => {
  if (tickTimer !== null) {
    window.clearInterval(tickTimer)
    tickTimer = null
  }
})
</script>

<template>
  <v-row>
    <v-col cols="12" lg="5">
      <v-card>
        <v-card-title class="text-subtitle-1">请求下载</v-card-title>
        <v-card-subtitle class="text-wrap">
          输入漫画 ID，支持逗号、句号、换行或空格分隔；单次最多 100 个。
        </v-card-subtitle>
        <v-card-text>
          <v-textarea
            v-model="downloadInput"
            label="漫画 ID"
            rows="5"
            placeholder="例如：350234, 422866"
            :disabled="submitting"
            hide-details="auto"
          />
          <v-alert v-if="requestError" type="error" variant="tonal" class="mt-3">
            {{ requestError }}
          </v-alert>
          <v-alert v-if="requestNotice" type="success" variant="tonal" class="mt-3">
            {{ requestNotice }}
          </v-alert>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn
            color="primary"
            prepend-icon="mdi-cloud-download-outline"
            :loading="submitting"
            @click="submitDownload"
          >
            请求下载
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-col>

    <v-col cols="12" lg="7">
      <v-card>
        <v-card-title class="d-flex flex-wrap align-center ga-2">
          <span class="text-subtitle-1">实时进度</span>
          <v-chip
            v-if="snapshot"
            size="small"
            variant="tonal"
            :color="statusColor"
          >
            {{ statusLabel }}
          </v-chip>
        </v-card-title>
        <v-progress-linear v-if="progressError" color="error" indeterminate />
        <v-card-text>
          <v-alert v-if="progressError" type="error" variant="tonal">
            {{ progressError }}
          </v-alert>

          <template v-if="snapshot">
            <div class="d-flex flex-wrap align-center justify-space-between ga-2">
              <div class="text-subtitle-1">本子-JM{{ snapshot.album_id }}</div>
              <div class="text-caption text-medium-emphasis">
                已耗时 {{ elapsedText }}
              </div>
            </div>
            <div class="text-body-2 text-medium-emphasis mt-1 mb-2">
              章节 {{ snapshot.album_done }}/{{ snapshot.album_total }} · 图片
              {{ imageDone }}/{{ imageTotal }} · {{ albumPercent }}%
            </div>
            <v-progress-linear
              :model-value="albumPercent"
              :color="statusColor"
              height="12"
              rounded
            />

            <v-divider class="my-4" />
            <div class="text-subtitle-2 mb-3">章节进度</div>
            <div
              v-for="chapter in snapshot.chapters"
              :key="chapter.photo_id"
              class="mb-3"
            >
              <div class="d-flex flex-wrap align-center ga-2">
                <span class="text-body-2">章节-JM{{ chapter.photo_id }}</span>
                <v-spacer />
                <span class="text-caption text-medium-emphasis">
                  图片 {{ chapter.done }}/{{ chapter.total }}
                </span>
                <v-icon
                  v-if="chapterIcon(chapter)"
                  :color="chapterIconColor(chapter)"
                  size="18"
                  :aria-label="chapter.finished ? '章节下载完成' : '章节图片不完整'"
                >
                  {{ chapterIcon(chapter) }}
                </v-icon>
              </div>
              <v-progress-linear
                class="mt-1"
                :model-value="chapterPercent(chapter)"
                :color="chapter.finished ? 'success' : 'primary'"
                height="8"
                rounded
              />
            </div>
            <div
              v-if="snapshot.chapters.length === 0"
              class="text-body-2 text-medium-emphasis"
            >
              正在获取章节信息…
            </div>
          </template>

          <EmptyState
            v-else
            icon="mdi-progress-download"
            title="当前没有正在下载的漫画"
            description="输入漫画 ID 请求下载后，这里会实时显示本子与章节进度。"
          />
        </v-card-text>
      </v-card>
    </v-col>
  </v-row>
</template>
