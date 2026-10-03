<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDisplay } from 'vuetify'

import { listAuditEvents } from '@/api/audit'
import { errorMessage } from '@/api/client'
import EmptyState from '@/components/EmptyState.vue'
import type { AuditEvent } from '@/types/api'
import { formatDateTime } from '@/utils/format'
import { labelOf, TASK_SOURCE_LABELS } from '@/utils/labels'

const route = useRoute()
const router = useRouter()
const { mobile } = useDisplay()
const items = ref<AuditEvent[]>([])
const page = ref(1)
const pages = ref(0)
const total = ref(0)
const eventType = ref('')
const source = ref('')
const loading = ref(false)
const error = ref('')
const resultLabels: Record<string, string> = {
  accepted: '已受理', succeeded: '成功', failed: '失败', cancelled: '已取消',
}
// 快速切换筛选时，只接受最新请求的结果。
let requestVersion = 0

async function load(): Promise<void> {
  const version = ++requestVersion
  loading.value = true
  error.value = ''
  try {
    const result = await listAuditEvents({
      page: page.value, page_size: 20,
      event_type: eventType.value || undefined, source: source.value || undefined,
    })
    if (version !== requestVersion) return
    items.value = result.items
    pages.value = result.pages
    total.value = result.total
  } catch (err) {
    if (version === requestVersion) error.value = errorMessage(err)
  } finally {
    if (version === requestVersion) loading.value = false
  }
}

function filter(): void {
  void router.push({ query: { event_type: eventType.value || undefined, source: source.value || undefined } })
}

watch(() => route.query, (query) => {
  eventType.value = typeof query.event_type === 'string' ? query.event_type : ''
  source.value = typeof query.source === 'string' ? query.source : ''
  const value = Number(query.page ?? 1)
  page.value = Number.isInteger(value) && value > 0 ? value : 1
  void load()
}, { immediate: true })
</script>

<template>
  <div>
    <v-card class="mb-4 pa-4">
      <v-row dense>
        <v-col cols="12" md="6"><v-text-field v-model="eventType" label="事件类型（精确匹配）" placeholder="例如：manga.deleted" hide-details maxlength="128" @keyup.enter="filter" /></v-col>
        <v-col cols="12" md="4"><v-select v-model="source" label="操作来源" :items="[{ title: '全部来源', value: '' }, { title: 'WebUI', value: 'web' }, { title: 'QQ', value: 'qq' }, { title: '系统', value: 'system' }]" hide-details /></v-col>
        <v-col cols="12" md="2" class="d-flex align-center"><v-btn color="primary" block @click="filter">筛选</v-btn></v-col>
      </v-row>
      <div class="d-flex align-center mt-3">共 {{ total }} 条审计记录<v-spacer /><v-btn aria-label="刷新审计" icon="mdi-refresh" variant="text" @click="load" /></div>
    </v-card>
    <v-alert v-if="error" type="error" variant="tonal" class="mb-4">{{ error }}</v-alert>
    <v-card>
      <v-progress-linear v-if="loading" indeterminate />
      <EmptyState v-if="!loading && !error && items.length === 0" title="没有审计记录" description="请调整筛选条件或执行管理操作。" />
      <v-table v-if="!mobile && items.length">
        <thead><tr><th>时间</th><th>事件类型</th><th>来源</th><th>操作者 / IP</th><th>目标</th><th>结果</th></tr></thead>
        <tbody>
          <tr v-for="item in items" :key="item.id">
            <td>{{ formatDateTime(item.created_at) }}</td><td>{{ item.event_type }}</td><td>{{ labelOf(TASK_SOURCE_LABELS, item.source) }}</td>
            <td>{{ item.actor_user_id ?? '—' }} / {{ item.client_ip ?? '—' }}</td><td>{{ item.target_id ?? item.target_type ?? '—' }}</td>
            <td>{{ labelOf(resultLabels, item.result) }}<span v-if="item.error_code">（{{ item.error_code }}）</span></td>
          </tr>
        </tbody>
      </v-table>
      <v-list v-else-if="mobile" lines="three">
        <v-list-item v-for="item in items" :key="item.id">
          <v-list-item-title class="text-wrap">{{ item.event_type }}</v-list-item-title>
          <div class="text-body-2 audit-details">{{ formatDateTime(item.created_at) }} · {{ labelOf(TASK_SOURCE_LABELS, item.source) }} · {{ labelOf(resultLabels, item.result) }}<br>操作者 {{ item.actor_user_id ?? '—' }} · IP {{ item.client_ip ?? '—' }}<br>目标 {{ item.target_id ?? item.target_type ?? '—' }}<span v-if="item.error_code"> · {{ item.error_code }}</span></div>
        </v-list-item>
      </v-list>
      <v-pagination v-if="pages > 1" :model-value="page" :length="pages" :total-visible="5" @update:model-value="router.push({ query: { ...route.query, page: $event } })" />
    </v-card>
  </div>
</template>

<style scoped>
.audit-details { overflow-wrap: anywhere; }
</style>
