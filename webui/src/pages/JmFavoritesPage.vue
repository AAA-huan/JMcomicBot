<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDisplay } from 'vuetify'

import { errorMessage } from '@/api/client'
import {
  getJmAccount, getJmImport, listJmFavorites, listJmImports,
  loginJmAccount, logoutJmAccount, requestJmDownloads, startJmImport,
} from '@/api/jmFavorites'
import type { JmAccount, JmFavorite, JmImport } from '@/api/jmFavorites'
import EmptyState from '@/components/EmptyState.vue'
import PaginationBar from '@/components/PaginationBar.vue'
import { copyText } from '@/utils/clipboard'
import { formatDateTime } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const { mobile } = useDisplay()
const pageSizeOptions = [20, 50, 100]
const account = ref<JmAccount>({ connected: false })
const username = ref('')
const password = ref('')
const selectedFolders = ref<string[]>(['0'])
const jobs = ref<JmImport[]>([])
const items = ref<JmFavorite[]>([])
const selected = ref<string[]>([])
const page = ref(1)
const pages = ref(0)
const total = ref(0)
const pageSize = ref(20)
const search = ref<string | null>('')
const downloadStatus = ref('')
const loading = ref(false)
const busy = ref(false)
const downloading = ref(false)
const error = ref('')
const notice = ref('')
const running = computed(() => jobs.value.some((job) => job.status === 'running'))
const selectedIds = computed(() => [...new Set(selected.value)])
// 当前页可勾选项：未下载项的漫画 ID 去重
const selectableIds = computed(() => [
  ...new Set(items.value.filter((item) => !item.downloaded).map((item) => item.manga_id)),
])
const allSelectableSelected = computed(
  () => selectableIds.value.length > 0
    && selectableIds.value.every((id) => selected.value.includes(id)),
)
const downloadOptions = [
  { title: '全部下载状态', value: '' },
  { title: '未下载', value: 'not_downloaded' },
  { title: '已下载', value: 'downloaded' },
]
const statusLabels = { running: '导入中', succeeded: '已完成', failed: '失败', interrupted: '已中断' }
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
let listRequest = 0

/** 完成导入后刷新列表；重新进入页面会继续显示服务端任务进度。 */
async function pollImport(): Promise<void> {
  timer = undefined
  if (disposed) return
  const active = jobs.value.find((job) => job.status === 'running')
  if (!active) return
  try {
    const result = await getJmImport(active.id)
    if (disposed) return
    jobs.value = jobs.value.map((job) => job.id === result.id ? result : job)
    if (result.status !== 'running') {
      if (result.error_message) error.value = result.error_message
      await Promise.all([loadFavorites(), refreshAccount()])
    }
  } catch (err) {
    if (!disposed) error.value = errorMessage(err)
  } finally {
    schedulePoll()
  }
}

function schedulePoll(): void {
  if (!disposed && running.value && timer === undefined) timer = setTimeout(() => void pollImport(), 1500)
}

async function refreshAccount(): Promise<void> {
  account.value = await getJmAccount()
}

/** 从 URL 恢复页码和每页数量，刷新页面后保持当前分页视图。 */
function readQuery(): void {
  const query = route.query
  const pageValue = Number.parseInt(
    typeof query.page === 'string' ? query.page : '1',
    10,
  )
  page.value = Number.isFinite(pageValue) && pageValue > 0 ? pageValue : 1
  const size = Number.parseInt(
    typeof query.page_size === 'string' ? query.page_size : '20',
    10,
  )
  pageSize.value = pageSizeOptions.includes(size) ? size : 20
}

/** 把分页参数写回 URL，空值不保留。 */
function updateQuery(patch: Record<string, string | number | undefined>): void {
  const query: Record<string, string> = {}
  for (const [key, value] of Object.entries({ ...route.query, ...patch })) {
    if (value === undefined || value === null || value === '') continue
    query[key] = String(value)
  }
  void router.push({ query })
}

/** 翻页并同步 URL，随后加载对应页数据。 */
function changePage(value: number): void {
  page.value = value
  updateQuery({ page: value > 1 ? value : undefined })
  void loadFavorites()
}

/** 切换每页数量时回到第一页，同步 URL 后重新加载。 */
function changePageSize(value: number): void {
  pageSize.value = value
  page.value = 1
  updateQuery({ page_size: value, page: undefined })
  void loadFavorites()
}

async function loadFavorites(): Promise<void> {
  const request = ++listRequest
  loading.value = true
  selected.value = []
  try {
    const result = await listJmFavorites({ page: page.value, page_size: pageSize.value, search: (search.value ?? '').trim(), download_status: downloadStatus.value })
    if (disposed || request !== listRequest) return
    items.value = result.items
    total.value = result.total
    pages.value = result.pages
    if (page.value > Math.max(result.pages, 1)) {
      page.value = Math.max(result.pages, 1)
      updateQuery({ page: page.value > 1 ? page.value : undefined })
      await loadFavorites()
    }
  } catch (err) {
    if (!disposed && request === listRequest) error.value = errorMessage(err)
  } finally {
    if (request === listRequest) loading.value = false
  }
}

async function initialize(): Promise<void> {
  error.value = ''
  readQuery()
  try {
    await Promise.all([
      refreshAccount(), loadFavorites(),
      listJmImports().then((result) => { jobs.value = result.items }),
    ])
    schedulePoll()
  } catch (err) {
    error.value = errorMessage(err)
  }
}

async function login(): Promise<void> {
  if (busy.value) return
  busy.value = true
  error.value = ''
  account.value = { connected: false }
  try {
    account.value = await loginJmAccount(username.value.trim(), password.value)
    selectedFolders.value = ['0']
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    password.value = ''
    busy.value = false
  }
}

async function logout(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    account.value = await logoutJmAccount()
    password.value = ''
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    busy.value = false
  }
}

async function importFavorites(): Promise<void> {
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const job = await startJmImport(selectedFolders.value)
    jobs.value = [job, ...jobs.value].slice(0, 20)
    schedulePoll()
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    busy.value = false
  }
}

async function download(): Promise<void> {
  downloading.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await requestJmDownloads(selectedIds.value)
    const skipped = result.skipped_blacklisted.length > 0
      ? `，${result.skipped_blacklisted.length} 本已被拉黑跳过`
      : ''
    notice.value = `已加入下载队列 ${result.queued_count} 本，已有任务 ${result.duplicate_count} 本${skipped}。可在任务管理页查看进度，完成后刷新本页。`
    selected.value = []
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    downloading.value = false
  }
}

function toggleSelectAll(): void {
  if (allSelectableSelected.value) {
    // 取消全选：移除当前页可选 ID
    const removable = new Set(selectableIds.value)
    selected.value = selected.value.filter((id) => !removable.has(id))
  } else {
    // 全选：合并当前页可选 ID（保留其他页已选）
    const merged = new Set([...selected.value, ...selectableIds.value])
    selected.value = [...merged]
  }
}

async function copySelectedIds(): Promise<void> {
  const ids = selectedIds.value.join(',')
  if (!ids) return
  const ok = await copyText(ids)
  notice.value = ok
    ? `已复制 ${selectedIds.value.length} 个漫画 ID`
    : '复制失败，请手动选择并复制'
  error.value = ''
}

function applyFilters(): void {
  page.value = 1
  updateQuery({ page: undefined })
  void loadFavorites()
}

onMounted(initialize)
onBeforeUnmount(() => { disposed = true; if (timer !== undefined) clearTimeout(timer); password.value = '' })
</script>

<template>
  <div>
    <div class="d-flex align-center flex-wrap ga-2 mb-4">
      <h1 class="text-h5">JM 收藏导入</h1>
      <v-spacer />
      <v-btn variant="text" prepend-icon="mdi-refresh" :disabled="loading" @click="initialize">刷新</v-btn>
      <v-btn variant="text" to="/library">漫画库</v-btn>
    </div>
    <v-alert v-if="error" type="error" variant="tonal" closable class="mb-4" @click:close="error = ''">{{ error }}</v-alert>
    <v-alert v-if="notice" type="success" variant="tonal" closable class="mb-4" @click:close="notice = ''">{{ notice }}</v-alert>

    <v-card class="mb-4">
      <v-card-title>登录 JM 天堂账号</v-card-title>
      <v-card-text>
        <p class="text-body-2 text-medium-emphasis mb-4">导入账号收藏列表，之后可选择下载漫画。账号密码不保存，登录最长保持 30 分钟；退出控制台或服务重启后需重新登录。</p>
        <v-form v-if="!account.connected" @submit.prevent="login">
          <v-row>
            <v-col cols="12" md="4"><v-text-field v-model="username" label="JM 用户名" autocomplete="off" :disabled="busy" hide-details /></v-col>
            <v-col cols="12" md="4"><v-text-field v-model="password" label="JM 密码" type="password" autocomplete="new-password" :disabled="busy" hide-details /></v-col>
            <v-col cols="12" md="4" class="d-flex align-center"><v-btn type="submit" color="primary" :loading="busy" :disabled="!username.trim() || !password || running" data-testid="jm-login">登录并读取收藏夹</v-btn></v-col>
          </v-row>
        </v-form>
        <template v-else>
          <div class="d-flex align-center flex-wrap ga-2 mb-4">
            <v-chip color="success">已登录：{{ account.username }}</v-chip>
            <span class="text-body-2">收藏共 {{ account.total }} 本 · 会话到期 {{ formatDateTime(account.expires_at ?? '') }}</span>
            <v-spacer />
            <v-btn variant="text" :loading="busy" @click="logout">退出 JM 账号</v-btn>
          </div>
          <v-select v-model="selectedFolders" :items="account.folders" item-title="name" item-value="id" label="选择收藏夹" multiple chips :disabled="busy || running" />
          <v-btn color="primary" prepend-icon="mdi-cloud-download-outline" :disabled="!selectedFolders.length || running" :loading="busy" data-testid="jm-import" @click="importFavorites">导入收藏列表</v-btn>
        </template>
      </v-card-text>
    </v-card>

    <v-card v-if="jobs.length" class="mb-4">
      <v-card-title>最近导入</v-card-title>
      <v-progress-linear v-if="running" indeterminate />
      <v-list>
        <v-list-item v-for="job in jobs.slice(0, 5)" :key="job.id" :title="`${job.username} · ${statusLabels[job.status]}`">
          <template #subtitle>
            <div>已处理 {{ job.pages_done }} 页 · 新增 {{ job.imported_count }} 本 · 已有 {{ job.duplicate_count }} 本 · 本地关联 {{ job.local_count }} 本</div>
            <div v-if="job.error_message" class="text-error">{{ job.error_message }}</div>
          </template>
        </v-list-item>
      </v-list>
    </v-card>

    <v-card>
      <v-card-title>已导入收藏（{{ total }}）</v-card-title>
      <v-card-text>
        <v-row>
          <v-col cols="12" md="6"><v-text-field v-model="search" label="搜索标题 / 漫画编号" prepend-inner-icon="mdi-magnify" hide-details clearable @keyup.enter="applyFilters" @click:clear="search = ''; applyFilters()" /></v-col>
          <v-col cols="12" md="3"><v-select v-model="downloadStatus" :items="downloadOptions" label="下载状态" hide-details @update:model-value="applyFilters" /></v-col>
          <v-col cols="12" md="3" class="d-flex align-center"><v-btn variant="tonal" :disabled="loading" @click="applyFilters">查询</v-btn></v-col>
        </v-row>
        <div class="d-flex align-center flex-wrap ga-2 mt-4">
          <div class="action-scroll" :class="{ 'action-scroll--block': mobile }">
            <v-btn variant="tonal" :disabled="selectableIds.length === 0" @click="toggleSelectAll">
              {{ allSelectableSelected ? '取消全选' : '全选' }}
            </v-btn>
            <v-btn color="primary" :loading="downloading" :disabled="selectedIds.length === 0 || selectedIds.length > 100" data-testid="jm-download" @click="download">下载所选（{{ selectedIds.length }}）</v-btn>
            <v-btn variant="tonal" prepend-icon="mdi-content-copy" :disabled="selectedIds.length === 0" @click="copySelectedIds">复制 ID</v-btn>
            <span class="text-caption text-medium-emphasis">每次最多 100 本，下载后自动关联管理员收藏。</span>
          </div>
          <v-spacer />
          <v-btn variant="text" to="/tasks">查看任务管理</v-btn>
        </div>
      </v-card-text>
      <v-progress-linear v-if="loading" indeterminate />
      <EmptyState v-if="!loading && !items.length" title="暂无导入收藏" description="登录账号后导入收藏，或调整查询条件。" icon="mdi-bookmark-outline" />
      <v-list v-else>
        <v-list-item v-for="item in items" :key="`${item.username}:${item.manga_id}`">
          <template #prepend><v-checkbox-btn v-if="!item.downloaded" v-model="selected" :value="item.manga_id" :aria-label="`选择漫画 ${item.manga_id}`" /></template>
          <v-list-item-title class="text-wrap">{{ item.title }} <span class="text-medium-emphasis">JM{{ item.manga_id }}</span></v-list-item-title>
          <v-list-item-subtitle class="text-wrap">{{ item.username }} · {{ Object.values(item.folders).join(' / ') }}</v-list-item-subtitle>
          <template #append>
            <v-btn v-if="item.downloaded" variant="text" :to="`/library/${item.manga_id}`">查看漫画</v-btn>
            <v-chip v-else size="small" variant="tonal">未下载</v-chip>
          </template>
        </v-list-item>
      </v-list>
      <PaginationBar
        :page="page"
        :pages="pages"
        :page-size="pageSize"
        :page-size-options="pageSizeOptions"
        :loading="loading"
        @update:page="changePage"
        @update:page-size="changePageSize"
      />
    </v-card>
  </div>
</template>
