<script setup lang="ts">
import { computed, ref } from 'vue'

import { errorMessage } from '@/api/client'
import { reconnectNapcat, requestShutdown } from '@/api/system'
import { useSystemStore } from '@/stores/system'

const system = useSystemStore()

const actionError = ref('')
const notice = ref('')
const reconnecting = ref(false)
const shutdownDialog = ref(false)
const shuttingDown = ref(false)

const status = computed(() => system.status)

function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (days > 0) return `${days} 天 ${hours} 小时`
  if (hours > 0) return `${hours} 小时 ${minutes} 分钟`
  return `${minutes} 分钟`
}

async function handleRefresh(): Promise<void> {
  await system.refresh()
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
      class="mb-4"
    >
      {{ actionError }}
    </v-alert>
    <v-alert
      v-if="notice"
      type="success"
      variant="tonal"
      density="comfortable"
      class="mb-4"
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
        </v-card>
      </v-col>
      <v-col cols="12" sm="6" md="4">
        <v-card class="pa-4 h-100">
          <div class="text-caption text-medium-emphasis">下载队列</div>
          <div class="text-h6">{{ status?.download_queue.queue_size ?? '—' }} 个待处理</div>
        </v-card>
      </v-col>
      <v-col cols="12" sm="6" md="4">
        <v-card class="pa-4 h-100">
          <div class="text-caption text-medium-emphasis">发送队列</div>
          <div class="text-h6">{{ status?.send_queue.queue_size ?? '—' }} 个待处理</div>
        </v-card>
      </v-col>
    </v-row>

    <v-dialog v-model="shutdownDialog" max-width="420">
      <v-card>
        <v-card-title>确认安全关闭？</v-card-title>
        <v-card-text>
          机器人将停止接收新请求并安全关闭 WebUI 与后台队列。关闭后需要手动重新启动。
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="shutdownDialog = false">取消</v-btn>
          <v-btn
            color="error"
            :loading="shuttingDown"
            @click="confirmShutdown"
          >
            确认关闭
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>
