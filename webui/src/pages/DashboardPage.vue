<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { errorMessage } from '@/api/client'
import { useEventSubscription } from '@/api/eventStream'
import { reconnectNapcat, requestShutdown } from '@/api/system'
import { listTasks } from '@/api/tasks'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import EmptyState from '@/components/EmptyState.vue'
import { useSystemStore } from '@/stores/system'
import type { OperationTask } from '@/types/api'
import { formatDateTime, formatUptime } from '@/utils/format'
import {
  colorOf,
  labelOf,
  TASK_STATUS_COLORS,
  TASK_STATUS_LABELS,
  TASK_TYPE_LABELS,
} from '@/utils/labels'

const system = useSystemStore()

const actionError = ref('')
const notice = ref('')
const reconnecting = ref(false)
const shutdownDialog = ref(false)
const shuttingDown = ref(false)

const recentTasks = ref<OperationTask[]>([])
const tasksLoading = ref(false)
const tasksError = ref('')

const status = computed(() => system.status)

async function loadRecentTasks(): Promise<void> {
  tasksLoading.value = true
  tasksError.value = ''
  try {
    const result = await listTasks({ page: 1, page_size: 5 })
    recentTasks.value = result.items
  } catch (err) {
    tasksError.value = errorMessage(err)
  } finally {
    tasksLoading.value = false
  }
}

async function handleRefresh(): Promise<void> {
  await Promise.all([system.refresh(), loadRecentTasks()])
}

async function handleReconnect(): Promise<void> {
  actionError.value = ''
  notice.value = ''
  reconnecting.value = true
  try {
    await reconnectNapcat()
    notice.value = '已请求 NapCat 重连，状态恢复后会自动更新'
  } catch (err) {
    actionError.value = errorMessage(err)
  } finally {
    reconnecting.value = false
  }
}

async function confirmShutdown(): Promise<void> {
  actionError.value = ''
  notice.value = ''
  shuttingDown.value = true
  try {
    await requestShutdown()
    shutdownDialog.value = false
    notice.value = '已请求安全关闭，机器人即将停止'
  } catch (err) {
    actionError.value = errorMessage(err)
    shutdownDialog.value = false
  } finally {
    shuttingDown.value = false
  }
}

// 任务事件到达后防抖刷新最近任务
let refreshTimer: number | null = null
useEventSubscription((event) => {
  if (event.type !== 'task.updated') return
  if (refreshTimer !== null) window.clearTimeout(refreshTimer)
  refreshTimer = window.setTimeout(() => {
    refreshTimer = null
    void loadRecentTasks()
  }, 600)
})

onMounted(() => {
  void loadRecentTasks()
})
</script>

<template>
  <div>
    <v-alert
      v-if="system.error"
      type="error"
      variant="tonal"
      density="comfortable"
      class="mb-4"
    >
      {{ system.error }}
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
      v-if="notice"
      type="success"
      variant="tonal"
      density="comfortable"
      closable
      class="mb-4"
      @click:close="notice = ''"
    >
      {{ notice }}
    </v-alert>

    <div class="d-flex flex-wrap ga-2 mb-4">
      <v-btn
        color="primary"
        prepend-icon="mdi-refresh"
        :loading="system.loading"
        @click="handleRefresh"
      >
        刷新状态
      </v-btn>
      <v-btn
        variant="tonal"
        prepend-icon="mdi-connection"
        :loading="reconnecting"
        @click="handleReconnect"
      >
        重连 NapCat
      </v-btn>
      <v-btn variant="tonal" prepend-icon="mdi-bookshelf" to="/library">漫画库</v-btn>
      <v-btn variant="tonal" prepend-icon="mdi-download-outline" to="/tasks">下载任务</v-btn>
      <v-spacer />
      <v-btn
        variant="tonal"
        color="error"
        prepend-icon="mdi-power"
        @click="shutdownDialog = true"
      >
        安全关闭
      </v-btn>
    </div>

    <v-row dense>
      <v-col cols="12" sm="6" md="4">
        <v-card class="pa-4 h-100">
          <div class="text-caption text-medium-emphasis">机器人版本</div>
          <div class="text-h6">{{ status?.version ?? '—' }}</div>
        </v-card>
      </v-col>
      <v-col cols="12" sm="6" md="4">
        <v-card class="pa-4 h-100">
          <div class="text-caption text-medium-emphasis">运行时长</div>
          <div class="text-h6">
            {{ status ? formatUptime(status.uptime_seconds) : '—' }}
          </div>
        </v-card>
      </v-col>
      <v-col cols="12" sm="6" md="4">
        <v-card class="pa-4 h-100">
          <div class="text-caption text-medium-emphasis">漫画数量</div>
          <div class="text-h6">{{ status?.manga_count ?? '—' }}</div>
        </v-card>
      </v-col>
      <v-col cols="12" sm="6" md="4">
        <v-card class="pa-4 h-100">
          <div class="text-caption text-medium-emphasis">NapCat 连接</div>
          <div
            class="text-h6"
            :class="status?.napcat_connected ? 'text-success' : 'text-error'"
          >
            {{ status?.napcat_connected ? '已连接' : '未连接' }}
          </div>
          <div class="text-caption text-medium-emphasis">
            实时推送：{{ system.eventsConnected ? '已连接' : '已断开（自动重连中）' }}
          </div>
        </v-card>
      </v-col>
      <v-col cols="12" sm="6" md="4">
        <v-card class="pa-4 h-100">
          <div class="text-caption text-medium-emphasis">下载队列</div>
          <div class="text-h6">
            {{ status?.download_queue.queue_size ?? '—' }} 个任务
          </div>
          <div class="text-caption text-medium-emphasis text-truncate">
            {{
              status?.download_queue.current_manga_id
                ? `正在下载：${status.download_queue.current_manga_id}`
                : '当前没有正在下载的漫画'
            }}
          </div>
        </v-card>
      </v-col>
      <v-col cols="12" sm="6" md="4">
        <v-card class="pa-4 h-100">
          <div class="text-caption text-medium-emphasis">发送队列</div>
          <div class="text-h6">
            {{ status?.send_queue.queue_size ?? '—' }} 个任务
          </div>
          <div class="text-caption text-medium-emphasis text-truncate">
            {{
              status?.send_queue.current_file
                ? `正在发送：${status.send_queue.current_file}`
                : '当前没有正在发送的文件'
            }}
          </div>
        </v-card>
      </v-col>
    </v-row>

    <v-card class="mt-1">
      <v-card-title class="text-subtitle-1 d-flex align-center">
        最近任务
        <v-spacer />
        <v-btn
          size="small"
          variant="text"
          prepend-icon="mdi-refresh"
          :loading="tasksLoading"
          @click="loadRecentTasks"
        >
          刷新
        </v-btn>
      </v-card-title>
      <v-divider />
      <v-alert
        v-if="tasksError"
        type="error"
        variant="tonal"
        density="comfortable"
        class="ma-3"
      >
        {{ tasksError }}
      </v-alert>
      <EmptyState
        v-else-if="!tasksLoading && recentTasks.length === 0"
        icon="mdi-clipboard-text-outline"
        title="还没有任务记录"
        description="在漫画库发起下载后，任务进度会显示在这里。"
      />
      <v-list v-else lines="two">
        <v-list-item
          v-for="task in recentTasks"
          :key="task.id"
          :to="{ name: 'tasks', query: { manga_id: task.manga_id ?? undefined } }"
        >
          <v-list-item-title class="text-wrap">
            {{ labelOf(TASK_TYPE_LABELS, task.task_type) }} · {{ task.summary }}
          </v-list-item-title>
          <v-list-item-subtitle class="text-wrap">
            {{ formatDateTime(task.updated_at) }}
          </v-list-item-subtitle>
          <template #append>
            <v-chip
              size="small"
              variant="tonal"
              :color="colorOf(TASK_STATUS_COLORS, task.status)"
            >
              {{ labelOf(TASK_STATUS_LABELS, task.status) }}
            </v-chip>
          </template>
        </v-list-item>
      </v-list>
    </v-card>

    <ConfirmDialog
      v-model="shutdownDialog"
      title="确认安全关闭？"
      text="机器人将停止接收新请求并安全关闭 WebUI 与后台队列。关闭后需要手动重新启动。"
      confirm-text="确认关闭"
      :loading="shuttingDown"
      @confirm="confirmShutdown"
    />
  </div>
</template>
