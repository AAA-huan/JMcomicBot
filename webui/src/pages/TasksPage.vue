<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDisplay } from 'vuetify'

import { errorMessage } from '@/api/client'
import { useEventSubscription } from '@/api/eventStream'
import {
  cancelQueuedTasks,
  cancelTask,
  cancelTasks,
  listTasks,
  pauseDownloadQueue,
  resumeDownloadQueue,
  retryTasks,
} from '@/api/tasks'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import EmptyState from '@/components/EmptyState.vue'
import PaginationBar from '@/components/PaginationBar.vue'
import { useSystemStore } from '@/stores/system'
import type { OperationTask } from '@/types/api'
import { copyText } from '@/utils/clipboard'
import { formatDateTime } from '@/utils/format'
import {
  colorOf,
  labelOf,
  TASK_SOURCE_LABELS,
  TASK_STATUS_COLORS,
  TASK_STATUS_LABELS,
  TASK_TYPE_LABELS,
} from '@/utils/labels'

const route = useRoute()
const router = useRouter()
const { mobile } = useDisplay()
const system = useSystemStore()

const pageSizeOptions = [20, 50, 100]
const typeOptions = [
  { value: '', title: '全部类型' },
  { value: 'download', title: '下载' },
  { value: 'scan', title: '扫描' },
  { value: 'repair', title: '修复' },
  { value: 'delete', title: '删除' },
  { value: 'backup', title: '备份' },
  { value: 'verify', title: '校验' },
  { value: 'blacklist', title: '黑名单' },
]
const statusOptions = [
  { value: '', title: '全部状态' },
  { value: 'queued', title: '排队中' },
  { value: 'running', title: '进行中' },
  { value: 'succeeded', title: '成功' },
  { value: 'failed', title: '失败' },
  { value: 'cancelled', title: '已取消' },
  { value: 'interrupted', title: '已中断' },
]

const tasks = ref<OperationTask[]>([])
const total = ref(0)
const pages = ref(0)
const loading = ref(false)
const error = ref('')
const actionError = ref('')
const actionNotice = ref('')

const filters = ref({
  taskType: '',
  status: '',
  mangaId: '',
  page: 1,
  pageSize: 20,
})

const cancelTarget = ref<OperationTask | null>(null)
const cancelDialog = ref(false)
const cancelLoading = ref(false)

const cancelQueuedDialog = ref(false)
const cancelQueuedLoading = ref(false)

// 任务选中机制：仅 manga_id 非空的下载任务可勾选（复制ID与批量操作的基础）
const selected = ref<string[]>([])
const batchLoading = ref(false)

/** 当前页可勾选任务：仅下载任务支持批量取消/重试 */
const selectableTasks = computed(() =>
  tasks.value.filter(
    (task) => task.task_type === 'download' && task.manga_id !== null && task.manga_id !== '',
  ),
)
const selectableIds = computed(() => selectableTasks.value.map((task) => task.id))
const allSelectableSelected = computed(
  () => selectableIds.value.length > 0
    && selectableIds.value.every((id) => selected.value.includes(id)),
)
/** 选中中可批量取消的任务（download + queued） */
const cancelableSelected = computed(() =>
  tasks.value.filter(
    (task) => selected.value.includes(task.id) && canCancel(task),
  ),
)
/** 选中中可批量重试的任务（download + interrupted/failed） */
const retryableSelected = computed(() =>
  tasks.value.filter(
    (task) =>
      selected.value.includes(task.id)
      && task.task_type === 'download'
      && (task.status === 'interrupted' || task.status === 'failed'),
  ),
)

const downloadQueue = computed(() => system.status?.download_queue ?? null)
const sendQueue = computed(() => system.status?.send_queue ?? null)
const downloadPaused = computed(() => downloadQueue.value?.paused === true)
const pauseLoading = ref(false)

/** 暂停/恢复下载队列；当前下载任务不会被中断。 */
async function toggleQueuePause(): Promise<void> {
  if (pauseLoading.value) return
  pauseLoading.value = true
  actionError.value = ''
  actionNotice.value = ''
  try {
    const result = downloadPaused.value
      ? await resumeDownloadQueue()
      : await pauseDownloadQueue()
    actionNotice.value = result.paused
      ? '下载队列已暂停，当前任务完成后不再开始新任务'
      : '下载队列已恢复，将继续处理排队任务'
    // 立即更新本地状态，服务端队列事件随后保持一致
    if (system.status) {
      system.status.download_queue = {
        ...system.status.download_queue,
        paused: result.paused,
      }
    }
  } catch (err) {
    actionError.value = errorMessage(err)
  } finally {
    pauseLoading.value = false
  }
}

function readQuery(): void {
  const query = route.query
  filters.value.taskType = typeof query.task_type === 'string' ? query.task_type : ''
  filters.value.status = typeof query.status === 'string' ? query.status : ''
  filters.value.mangaId = typeof query.manga_id === 'string' ? query.manga_id : ''
  const page = Number.parseInt(typeof query.page === 'string' ? query.page : '1', 10)
  filters.value.page = Number.isFinite(page) && page > 0 ? page : 1
  const size = Number.parseInt(
    typeof query.page_size === 'string' ? query.page_size : '20',
    10,
  )
  filters.value.pageSize = pageSizeOptions.includes(size) ? size : 20
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const result = await listTasks({
      page: filters.value.page,
      page_size: filters.value.pageSize,
      task_type: filters.value.taskType || undefined,
      status: filters.value.status || undefined,
      manga_id: filters.value.mangaId || undefined,
    })
    tasks.value = result.items
    total.value = result.total
    pages.value = result.pages
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

function updateQuery(patch: Record<string, string | number | undefined>): void {
  const query: Record<string, string> = {}
  for (const [key, value] of Object.entries({ ...route.query, ...patch })) {
    if (value === undefined || value === null || value === '') continue
    query[key] = String(value)
  }
  void router.push({ query })
}

function applyMangaFilter(): void {
  updateQuery({ manga_id: filters.value.mangaId || undefined, page: 1 })
}

function canCancel(task: OperationTask): boolean {
  return task.task_type === 'download' && task.status === 'queued'
}

function askCancel(task: OperationTask): void {
  cancelTarget.value = task
  cancelDialog.value = true
}

async function confirmCancel(): Promise<void> {
  const target = cancelTarget.value
  if (!target) return
  cancelLoading.value = true
  actionError.value = ''
  actionNotice.value = ''
  try {
    await cancelTask(target.id)
    actionNotice.value = '任务已取消'
    cancelDialog.value = false
    await load()
  } catch (err) {
    actionError.value = errorMessage(err)
    cancelDialog.value = false
  } finally {
    cancelLoading.value = false
  }
}

async function confirmCancelQueued(): Promise<void> {
  cancelQueuedLoading.value = true
  actionError.value = ''
  actionNotice.value = ''
  try {
    const result = await cancelQueuedTasks()
    actionNotice.value = `已取消 ${result.cancelled_count} 个排队任务`
    cancelQueuedDialog.value = false
    await load()
  } catch (err) {
    actionError.value = errorMessage(err)
    cancelQueuedDialog.value = false
  } finally {
    cancelQueuedLoading.value = false
  }
}

function toggleSelectAll(): void {
  if (allSelectableSelected.value) {
    const removable = new Set(selectableIds.value)
    selected.value = selected.value.filter((id) => !removable.has(id))
  } else {
    const merged = new Set([...selected.value, ...selectableIds.value])
    selected.value = [...merged]
  }
}

async function copySelectedIds(): Promise<void> {
  const selectedTasks = tasks.value.filter((task) => selected.value.includes(task.id) && task.manga_id)
  const ids = [...new Set(selectedTasks.map((task) => task.manga_id!))].join(',')
  if (!ids) return
  const ok = await copyText(ids)
  actionError.value = ''
  actionNotice.value = ok
    ? `已复制 ${new Set(selectedTasks.map((t) => t.manga_id)).size} 个漫画 ID`
    : '复制失败，请手动选择并复制'
}

async function batchCancel(): Promise<void> {
  const targets = cancelableSelected.value
  if (targets.length === 0) return
  batchLoading.value = true
  actionError.value = ''
  actionNotice.value = ''
  try {
    const result = await cancelTasks(targets.map((task) => task.id))
    const succeeded = result.items.filter((item) => item.status === 'cancelled').length
    const failed = result.failed_count
    actionNotice.value = `已取消 ${succeeded} 个任务${failed > 0 ? `，${failed} 个失败` : ''}`
    await load()
  } catch (err) {
    actionError.value = errorMessage(err)
  } finally {
    batchLoading.value = false
  }
}

async function batchRetry(): Promise<void> {
  const targets = retryableSelected.value
  if (targets.length === 0) return
  batchLoading.value = true
  actionError.value = ''
  actionNotice.value = ''
  try {
    const result = await retryTasks(targets.map((task) => task.id))
    const succeeded = result.items.filter((item) => item.status === 'requeued').length
    const failed = result.failed_count
    actionNotice.value = `已重新入队 ${succeeded} 个任务${failed > 0 ? `，${failed} 个失败` : ''}`
    selected.value = []
    await load()
  } catch (err) {
    actionError.value = errorMessage(err)
  } finally {
    batchLoading.value = false
  }
}

// 任务事件触发防抖刷新，避免高频推送时反复请求
let reloadTimer: number | null = null
useEventSubscription((event) => {
  if (event.type !== 'task.updated') return
  if (reloadTimer !== null) window.clearTimeout(reloadTimer)
  reloadTimer = window.setTimeout(() => {
    reloadTimer = null
    void load()
  }, 600)
})

watch(
  () => route.query,
  () => {
    readQuery()
    selected.value = []
    void load()
  },
  { immediate: true },
)
</script>

<template>
  <div>
    <v-alert
      v-if="error"
      type="error"
      variant="tonal"
      density="comfortable"
      class="mb-4"
    >
      {{ error }}
      <template #append>
        <v-btn size="small" variant="text" @click="load">重试</v-btn>
      </template>
    </v-alert>
    <v-alert
      v-if="actionError"
      type="error"
      variant="tonal"
      density="comfortable"
      closable
      class="mb-4"
      @click:close="actionError = ''"
    >
      {{ actionError }}
    </v-alert>
    <v-alert
      v-if="actionNotice"
      type="success"
      variant="tonal"
      density="comfortable"
      closable
      class="mb-4"
      @click:close="actionNotice = ''"
    >
      {{ actionNotice }}
    </v-alert>

    <v-row dense class="mb-4">
      <v-col cols="12" md="6">
        <v-card class="pa-4 h-100">
          <div class="d-flex align-center flex-wrap">
            <v-icon class="mr-2">mdi-download-box-outline</v-icon>
            <span class="text-subtitle-2">下载队列</span>
            <v-spacer />
            <v-chip size="small" variant="tonal" :color="downloadQueue?.running ? 'success' : 'medium-emphasis'">
              {{ downloadQueue?.running ? '运行中' : '已停止' }}
            </v-chip>
            <v-btn
              size="small"
              variant="tonal"
              class="ml-2"
              :color="downloadPaused ? 'success' : 'warning'"
              :prepend-icon="downloadPaused ? 'mdi-play' : 'mdi-pause'"
              :loading="pauseLoading"
              :disabled="!downloadQueue?.running"
              @click="toggleQueuePause"
            >
              {{ downloadPaused ? '恢复队列' : '暂停队列' }}
            </v-btn>
          </div>
          <div class="text-h5 mt-2">{{ downloadQueue?.queue_size ?? 0 }} 个任务</div>
          <div class="text-caption text-medium-emphasis">
            {{
              downloadQueue?.current_manga_id
                ? `正在下载：${downloadQueue.current_manga_id}`
                : '当前没有正在下载的漫画'
            }}
          </div>
          <div v-if="downloadPaused" class="text-caption text-warning">
            队列已暂停，当前任务完成后停止取新任务。
          </div>
          <div class="text-caption text-medium-emphasis">
            下载任务由后台串行执行，刷新页面不会丢失。
          </div>
        </v-card>
      </v-col>
      <v-col cols="12" md="6">
        <v-card class="pa-4 h-100">
          <div class="d-flex align-center">
            <v-icon class="mr-2">mdi-send-outline</v-icon>
            <span class="text-subtitle-2">发送队列</span>
            <v-spacer />
            <v-chip size="small" variant="tonal" :color="sendQueue?.running ? 'success' : 'medium-emphasis'">
              {{ sendQueue?.running ? '运行中' : '已停止' }}
            </v-chip>
          </div>
          <div class="text-h5 mt-2">{{ sendQueue?.queue_size ?? 0 }} 个任务</div>
          <div class="text-caption text-medium-emphasis text-truncate">
            {{ sendQueue?.current_file ? `正在发送：${sendQueue.current_file}` : '当前没有正在发送的文件' }}
          </div>
        </v-card>
      </v-col>
    </v-row>

    <v-card class="mb-4">
      <v-card-text class="pb-2">
        <v-row dense>
          <v-col cols="6" md="3">
            <v-select
              v-model="filters.taskType"
              :items="typeOptions"
              label="类型"
              hide-details
              @update:model-value="updateQuery({ task_type: filters.taskType || undefined, page: 1 })"
            />
          </v-col>
          <v-col cols="6" md="3">
            <v-select
              v-model="filters.status"
              :items="statusOptions"
              label="状态"
              hide-details
              @update:model-value="updateQuery({ status: filters.status || undefined, page: 1 })"
            />
          </v-col>
          <v-col cols="12" md="4">
            <v-text-field
              v-model="filters.mangaId"
              label="漫画 ID"
              hide-details
              clearable
              @keyup.enter="applyMangaFilter"
              @click:clear="applyMangaFilter"
            />
          </v-col>
          <v-col cols="12" md="2" class="d-flex align-center">
            <v-btn color="primary" block prepend-icon="mdi-magnify" @click="applyMangaFilter">
              筛选
            </v-btn>
          </v-col>
        </v-row>
      </v-card-text>
      <v-divider />
      <v-card-actions class="flex-wrap">
        <span class="text-body-2 text-medium-emphasis ml-2">共 {{ total }} 条
          <template v-if="selected.length > 0">，已选 {{ selected.length }} 条</template>
        </span>
        <v-spacer />
        <div class="action-scroll" :class="{ 'action-scroll--block': mobile }">
          <v-btn
            variant="tonal"
            :disabled="selectableIds.length === 0"
            @click="toggleSelectAll"
          >
            {{ allSelectableSelected ? '取消全选' : '全选' }}
          </v-btn>
          <v-btn
            variant="tonal"
            prepend-icon="mdi-content-copy"
            :disabled="selected.length === 0"
            @click="copySelectedIds"
          >
            复制 ID
          </v-btn>
          <v-btn
            variant="tonal"
            color="warning"
            prepend-icon="mdi-cancel"
            :disabled="cancelableSelected.length === 0"
            :loading="batchLoading"
            @click="batchCancel"
          >
            批量取消{{ cancelableSelected.length > 0 ? `（${cancelableSelected.length}）` : '' }}
          </v-btn>
          <v-btn
            variant="tonal"
            color="info"
            prepend-icon="mdi-restart"
            :disabled="retryableSelected.length === 0"
            :loading="batchLoading"
            @click="batchRetry"
          >
            批量重试{{ retryableSelected.length > 0 ? `（${retryableSelected.length}）` : '' }}
          </v-btn>
          <v-btn
            variant="tonal"
            color="warning"
            prepend-icon="mdi-cancel"
            @click="cancelQueuedDialog = true"
          >
            取消全部排队
          </v-btn>
          <v-btn icon="mdi-refresh" variant="text" aria-label="刷新" @click="load" />
        </div>
      </v-card-actions>
    </v-card>

    <v-card>
      <v-progress-linear v-if="loading" indeterminate />

      <EmptyState
        v-if="!loading && tasks.length === 0"
        icon="mdi-clipboard-text-outline"
        title="没有任务记录"
        description="在漫画下载页请求下载后，任务会出现在这里。"
      />

      <template v-else>
        <v-table v-if="!mobile">
          <thead>
            <tr>
              <th style="width: 44px">
                <v-checkbox-btn
                  :model-value="allSelectableSelected"
                  :indeterminate="selected.length > 0 && !allSelectableSelected"
                  aria-label="全选"
                  @update:model-value="toggleSelectAll"
                />
              </th>
              <th>类型</th>
              <th>状态</th>
              <th>摘要</th>
              <th>漫画</th>
              <th class="text-no-wrap">来源</th>
              <th class="text-no-wrap">更新时间</th>
              <th class="text-no-wrap">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="task in tasks" :key="task.id">
              <td>
                <v-checkbox-btn
                  v-if="task.manga_id"
                  v-model="selected"
                  :value="task.id"
                  :aria-label="`选择任务 ${task.id}`"
                />
              </td>
              <td class="text-no-wrap">{{ labelOf(TASK_TYPE_LABELS, task.task_type) }}</td>
              <td style="min-width: 140px">
                <v-chip
                  size="small"
                  variant="tonal"
                  :color="colorOf(TASK_STATUS_COLORS, task.status)"
                >
                  {{ labelOf(TASK_STATUS_LABELS, task.status) }}
                </v-chip>
                <v-progress-linear
                  v-if="task.status === 'running' && task.progress !== null"
                  :model-value="task.progress"
                  height="4"
                  class="mt-1"
                />
                <div v-if="task.error_message" class="text-caption text-error text-wrap">
                  {{ task.error_message }}
                </div>
              </td>
              <td class="text-wrap">{{ task.summary }}</td>
              <td class="text-no-wrap">
                <router-link
                  v-if="task.manga_id"
                  class="text-primary text-decoration-none"
                  :to="{ name: 'manga-detail', params: { mangaId: task.manga_id } }"
                >
                  {{ task.manga_id }}
                </router-link>
                <span v-else>—</span>
              </td>
              <td class="text-no-wrap">{{ labelOf(TASK_SOURCE_LABELS, task.source) }}</td>
              <td class="text-no-wrap">{{ formatDateTime(task.updated_at) }}</td>
              <td class="text-no-wrap">
                <v-btn
                  v-if="canCancel(task)"
                  size="small"
                  variant="text"
                  color="warning"
                  @click="askCancel(task)"
                >
                  取消
                </v-btn>
                <span v-else class="text-caption text-medium-emphasis">—</span>
              </td>
            </tr>
          </tbody>
        </v-table>

        <v-list v-else lines="three">
          <v-list-item v-for="task in tasks" :key="task.id">
            <template #prepend>
              <v-checkbox-btn
                v-if="task.manga_id"
                v-model="selected"
                :value="task.id"
                :aria-label="`选择任务 ${task.id}`"
              />
            </template>
            <v-list-item-title class="text-wrap">
              {{ labelOf(TASK_TYPE_LABELS, task.task_type) }} · {{ task.summary }}
            </v-list-item-title>
            <v-list-item-subtitle class="text-wrap">
              {{ formatDateTime(task.updated_at) }} ·
              {{ labelOf(TASK_SOURCE_LABELS, task.source) }}
              <template v-if="task.manga_id"> · 漫画 {{ task.manga_id }}</template>
            </v-list-item-subtitle>
            <div class="mt-1">
              <v-chip
                size="small"
                variant="tonal"
                :color="colorOf(TASK_STATUS_COLORS, task.status)"
              >
                {{ labelOf(TASK_STATUS_LABELS, task.status) }}
              </v-chip>
              <v-btn
                v-if="canCancel(task)"
                size="small"
                variant="text"
                color="warning"
                class="ml-2"
                @click="askCancel(task)"
              >
                取消
              </v-btn>
            </div>
            <v-progress-linear
              v-if="task.status === 'running' && task.progress !== null"
              :model-value="task.progress"
              height="4"
              class="mt-2"
            />
            <div v-if="task.error_message" class="text-caption text-error text-wrap mt-1">
              {{ task.error_message }}
            </div>
          </v-list-item>
        </v-list>
      </template>

      <v-divider v-if="pages > 1" />
      <PaginationBar
        :page="filters.page"
        :pages="pages"
        :page-size="filters.pageSize"
        :page-size-options="pageSizeOptions"
        :loading="loading"
        @update:page="updateQuery({ page: $event })"
        @update:page-size="updateQuery({ page_size: $event, page: 1 })"
      />
    </v-card>

    <ConfirmDialog
      v-model="cancelDialog"
      title="取消该任务？"
      text="仅尚未开始的下载任务可以取消；已开始的任务无法中断。"
      confirm-text="取消任务"
      confirm-color="warning"
      :loading="cancelLoading"
      @confirm="confirmCancel"
    />

    <ConfirmDialog
      v-model="cancelQueuedDialog"
      title="取消全部排队任务？"
      text="将取消所有尚未开始的下载任务，已开始的任务不受影响。"
      confirm-text="全部取消"
      confirm-color="warning"
      :loading="cancelQueuedLoading"
      @confirm="confirmCancelQueued"
    />
  </div>
</template>
