<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDisplay } from 'vuetify'

import { errorMessage } from '@/api/client'
import { setFavorite } from '@/api/favorites'
import {
  batchBlacklistMangas,
  batchDeleteMangas,
  batchUnblacklistMangas,
  blacklistManga,
  deleteManga,
  listMangas,
  unblacklistManga,
} from '@/api/mangas'
import { requestDownloads } from '@/api/tasks'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import EmptyState from '@/components/EmptyState.vue'
import PaginationBar from '@/components/PaginationBar.vue'
import { useCoverPreview } from '@/stores/coverPreview'
import type { Manga } from '@/types/api'
import { copyText } from '@/utils/clipboard'
import { formatDateTime } from '@/utils/format'
import {
  colorOf,
  labelOf,
  MANGA_STATUS_COLORS,
  MANGA_STATUS_LABELS,
} from '@/utils/labels'

const { coverPreview } = useCoverPreview()
const route = useRoute()
const router = useRouter()
const { mobile } = useDisplay()

const pageSizeOptions = [20, 50, 100]
const statusOptions = [
  { value: '', title: '全部状态' },
  { value: 'downloaded', title: '已下载' },
  { value: 'missing_file', title: '文件缺失' },
  { value: 'invalid', title: '无效记录' },
  { value: 'deleted', title: '已删除' },
]
const sortOptions = [
  { value: 'read_at_desc', title: '阅读时间（新→旧）' },
  { value: 'downloaded_at_desc', title: '下载时间（新→旧）' },
  { value: 'downloaded_at_asc', title: '下载时间（旧→新）' },
  { value: 'title_asc', title: '标题（A→Z）' },
  { value: 'title_desc', title: '标题（Z→A）' },
  { value: 'id_asc', title: '漫画 ID（升序）' },
  { value: 'id_desc', title: '漫画 ID（降序）' },
]

const mangas = ref<Manga[]>([])
const total = ref(0)
const pages = ref(0)
const loading = ref(false)
const error = ref('')
const selected = ref<string[]>([])

const scopeOptions = [
  { value: 'keyword', title: '标题 / 作者' },
  { value: 'tag', title: '标签' },
  { value: 'id', title: '漫画 ID' },
]

type SearchScope = 'keyword' | 'tag' | 'id'

const filters = reactive({
  keyword: '',
  scope: 'keyword' as SearchScope,
  status: '',
  sort: 'downloaded_at_desc',
  page: 1,
  pageSize: 20,
  favoriteOnly: false,
  collection: 'local' as 'local' | 'favorites' | 'history' | 'blacklist_only',
})

interface LibraryListCache {
  key: string
  items: Manga[]
  total: number
  pages: number
}

// 模块级列表缓存：从详情页返回时先展示缓存再后台刷新，避免重复等待
const libraryListCache: LibraryListCache = {
  key: '',
  items: [],
  total: 0,
  pages: 0,
}

const actionError = ref('')
const actionNotice = ref('')
const favoriteBusy = reactive<Record<string, boolean>>({})
const blacklistBusy = reactive<Record<string, boolean>>({})

const deleteTarget = ref<Manga | null>(null)
const deleteDialog = ref(false)
const deleteLoading = ref(false)

const batchDeleteDialog = ref(false)
const batchDeleteLoading = ref(false)

const blacklistTarget = ref<Manga | null>(null)
const blacklistDialog = ref(false)
const blacklistLoading = ref(false)
const blacklistMode = ref<'add' | 'remove'>('add')

const batchBlacklistDialog = ref(false)
const batchBlacklistLoading = ref(false)
const batchBlacklistMode = ref<'add' | 'remove'>('add')

const selectedCount = computed(() => selected.value.length)

/** 选中项中已拉黑的 ID，批量解除只提交这些漫画。 */
const selectedBlacklistedIds = computed(() =>
  mangas.value
    .filter((manga) => selected.value.includes(manga.id) && manga.is_blacklisted)
    .map((manga) => manga.id),
)

const hasSelectedBlacklisted = computed(() => selectedBlacklistedIds.value.length > 0)

/** 状态列优先展示黑名单标签，覆盖底层下载状态。 */
function mangaStatusKey(manga: Manga): string {
  return manga.is_blacklisted ? 'blacklisted' : manga.status
}

/** 当前页是否已全部选中；分页加载时会清空选择，因此只比较当前页数据。 */
const allSelectableSelected = computed(
  () => mangas.value.length > 0 && selected.value.length === mangas.value.length,
)

/** 全选/取消全选当前页；与任务管理页保持一致，不跨页保留选择。 */
function toggleSelectAll(): void {
  selected.value = allSelectableSelected.value
    ? []
    : mangas.value.map((manga) => manga.id)
}

/** 从 URL 查询参数恢复筛选条件，保证刷新后视图不丢失。 */
function readQuery(): void {
  const query = route.query
  const rawTag = typeof query.tag === 'string' ? query.tag : ''
  const rawSearch = typeof query.search === 'string' ? query.search : ''
  if (query.scope === 'tag' || query.scope === 'id') {
    filters.scope = query.scope
  } else {
    // 兼容旧链接：只有 tag 参数时按标签范围处理
    filters.scope = rawTag ? 'tag' : 'keyword'
  }
  filters.keyword = rawTag || rawSearch
  filters.collection = query.collection === 'blacklist_only' ? 'blacklist_only'
    : query.collection === 'history' ? 'history'
    : query.collection === 'favorites' || query.favorite_only === 'true' ? 'favorites' : 'local'
  filters.favoriteOnly = filters.collection === 'favorites'
  filters.status = typeof query.status === 'string' ? query.status : ''
  filters.sort = typeof query.sort === 'string' ? query.sort
    : filters.collection === 'history' ? 'read_at_desc' : 'downloaded_at_desc'
  const page = Number.parseInt(typeof query.page === 'string' ? query.page : '1', 10)
  filters.page = Number.isFinite(page) && page > 0 ? page : 1
  const size = Number.parseInt(
    typeof query.page_size === 'string' ? query.page_size : '20',
    10,
  )
  filters.pageSize = pageSizeOptions.includes(size) ? size : 20
}

/** 当前查询参数的稳定字符串，用于判断模块级缓存是否可复用。 */
function queryKey(): string {
  return Object.entries(route.query)
    .map(([key, value]) => `${key}=${String(value)}`)
    .sort()
    .join('&')
}

async function load(options: { silent?: boolean } = {}): Promise<void> {
  const silent = options.silent === true
  if (!silent) loading.value = true
  error.value = ''
  try {
    const result = await listMangas({
      page: filters.page,
      page_size: filters.pageSize,
      search: filters.scope === 'tag' ? undefined : filters.keyword || undefined,
      status: filters.status || undefined,
      tag: filters.scope === 'tag' ? filters.keyword || undefined : undefined,
      sort: filters.sort,
      favorite_only: filters.favoriteOnly || undefined,
      history_only: filters.collection === 'history' || undefined,
      blacklist_only: filters.collection === 'blacklist_only' || undefined,
    })
    mangas.value = result.items
    total.value = result.total
    pages.value = result.pages
    selected.value = []
    libraryListCache.key = queryKey()
    libraryListCache.items = result.items
    libraryListCache.total = result.total
    libraryListCache.pages = result.pages
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    if (!silent) loading.value = false
  }
}

/** 把筛选写回 URL 查询参数；空值移除。 */
function updateQuery(patch: Record<string, string | number | undefined>): void {
  const query: Record<string, string> = {}
  for (const [key, value] of Object.entries({ ...route.query, ...patch })) {
    if (value === undefined || value === null || value === '') continue
    query[key] = String(value)
  }
  void router.push({ query })
}

/** 切换分组时恢复默认排序并回到第一页。 */
function switchCollection(
  collection: 'local' | 'favorites' | 'history' | 'blacklist_only',
): void {
  updateQuery({
    collection: collection === 'local' ? undefined : collection,
    favorite_only: undefined,
    sort: collection === 'history' ? 'read_at_desc' : 'downloaded_at_desc',
    page: 1,
  })
}

function fileDownloadUrl(fileId: number): string {
  return `/api/v1/files/${fileId}/content`
}

function applySearch(): void {
  const keyword = filters.keyword.trim()
  if (filters.scope === 'tag') {
    updateQuery({
      tag: keyword || undefined,
      search: undefined,
      scope: 'tag',
      page: 1,
    })
    return
  }
  if (filters.scope === 'id') {
    updateQuery({
      search: keyword || undefined,
      tag: undefined,
      scope: 'id',
      page: 1,
    })
    return
  }
  updateQuery({ search: keyword || undefined, tag: undefined, scope: undefined, page: 1 })
}

function clearSearch(): void {
  filters.keyword = ''
  applySearch()
}

async function requestDownloadIds(ids: string[]): Promise<void> {
  actionError.value = ''
  actionNotice.value = ''
  if (ids.length === 0) {
    actionError.value = '请输入至少一个漫画 ID'
    return
  }
  if (ids.length > 100) {
    actionError.value = '单次最多请求 100 个漫画'
    return
  }
  try {
    const result = await requestDownloads(ids)
    const parts = [`已入队 ${result.queued_count} 个`]
    if (result.skipped_blacklisted.length > 0) {
      parts.push(
        `${result.skipped_blacklisted.length} 个已被拉黑跳过（${result.skipped_blacklisted.join('、')}）`,
      )
    }
    if (result.duplicate_count > 0) {
      const duplicates = result.items
        .filter((item) => item.status === 'duplicate')
        .map((item) => item.manga_id)
      parts.push(
        `${result.duplicate_count} 个已有活动任务（${duplicates.join('、')}）`,
      )
    }
    actionNotice.value = parts.join('，')
    selected.value = []
  } catch (err) {
    actionError.value = errorMessage(err)
  }
}

async function copySelectedIds(): Promise<void> {
  if (selectedCount.value === 0) return
  const ids = [...new Set(selected.value)].join(',')
  const ok = await copyText(ids)
  actionError.value = ''
  actionNotice.value = ok
    ? `已复制 ${selectedCount.value} 个漫画 ID`
    : '复制失败，请手动选择并复制'
}

/** 服务端确认成功后更新状态，失败时保留原收藏状态。 */
async function toggleFavorite(manga: Manga): Promise<void> {
  if (favoriteBusy[manga.id]) return
  favoriteBusy[manga.id] = true
  actionError.value = ''
  actionNotice.value = ''
  try {
    const result = await setFavorite(manga.id, !manga.is_favorite)
    manga.is_favorite = result.is_favorite
    actionNotice.value = result.is_favorite ? `已收藏《${manga.title}》` : `已取消收藏《${manga.title}》`
    if (filters.favoriteOnly && !result.is_favorite) {
      if (mangas.value.length === 1 && filters.page > 1) updateQuery({ page: filters.page - 1 })
      else await load()
    }
  } catch (err) {
    actionError.value = errorMessage(err)
  } finally {
    favoriteBusy[manga.id] = false
  }
}

function askDelete(manga: Manga): void {
  deleteTarget.value = manga
  deleteDialog.value = true
}

function askBlacklist(manga: Manga): void {
  blacklistTarget.value = manga
  blacklistMode.value = 'add'
  blacklistDialog.value = true
}

function askUnblacklist(manga: Manga): void {
  blacklistTarget.value = manga
  blacklistMode.value = 'remove'
  blacklistDialog.value = true
}

/** 单个拉黑/解除提交，成功后刷新列表以同步黑名单筛选与状态。 */
async function confirmBlacklist(): Promise<void> {
  const target = blacklistTarget.value
  if (!target || blacklistBusy[target.id]) return
  blacklistLoading.value = true
  blacklistBusy[target.id] = true
  actionError.value = ''
  actionNotice.value = ''
  try {
    const result = blacklistMode.value === 'add'
      ? await blacklistManga(target.id)
      : await unblacklistManga(target.id)
    if (result.changed) {
      actionNotice.value = blacklistMode.value === 'add'
        ? `已将《${target.title}》加入黑名单`
        : `已将《${target.title}》移出黑名单`
    } else {
      actionNotice.value = blacklistMode.value === 'add'
        ? `《${target.title}》已在黑名单中`
        : `《${target.title}》不在黑名单中`
    }
    blacklistDialog.value = false
    await load()
  } catch (err) {
    actionError.value = errorMessage(err)
    blacklistDialog.value = false
  } finally {
    blacklistLoading.value = false
    blacklistBusy[target.id] = false
  }
}

function openBatchBlacklist(mode: 'add' | 'remove'): void {
  batchBlacklistMode.value = mode
  batchBlacklistDialog.value = true
}

/** 批量拉黑提交；批量解除只处理选中项中已拉黑的漫画。 */
async function confirmBatchBlacklist(): Promise<void> {
  if (selectedCount.value === 0) return
  const ids = batchBlacklistMode.value === 'remove'
    ? selectedBlacklistedIds.value
    : [...selected.value]
  if (ids.length === 0) {
    actionError.value = '选中的漫画中没有已拉黑项'
    batchBlacklistDialog.value = false
    return
  }
  if (ids.length > 100) {
    actionError.value = '单次最多操作 100 个漫画'
    batchBlacklistDialog.value = false
    return
  }
  batchBlacklistLoading.value = true
  actionError.value = ''
  actionNotice.value = ''
  try {
    const result = batchBlacklistMode.value === 'add'
      ? await batchBlacklistMangas(ids)
      : await batchUnblacklistMangas(ids)
    const action = batchBlacklistMode.value === 'add' ? '拉黑' : '解除拉黑'
    let notice = `已${action} ${result.changed_count} 个漫画`
    if (result.unchanged_count > 0) {
      notice += batchBlacklistMode.value === 'add'
        ? `，${result.unchanged_count} 个已在黑名单`
        : `，${result.unchanged_count} 个不在黑名单`
    }
    actionNotice.value = notice
    batchBlacklistDialog.value = false
    await load()
  } catch (err) {
    actionError.value = errorMessage(err)
    batchBlacklistDialog.value = false
  } finally {
    batchBlacklistLoading.value = false
  }
}

async function confirmDelete(): Promise<void> {
  const target = deleteTarget.value
  if (!target) return
  deleteLoading.value = true
  actionError.value = ''
  actionNotice.value = ''
  try {
    const result = await deleteManga(target.id)
    actionNotice.value = `已删除《${target.title}》及 ${result.deleted_file_count} 个文件`
    deleteDialog.value = false
    await load()
  } catch (err) {
    actionError.value = errorMessage(err)
    deleteDialog.value = false
  } finally {
    deleteLoading.value = false
  }
}

async function confirmBatchDelete(): Promise<void> {
  if (selectedCount.value === 0) return
  if (selectedCount.value > 100) {
    actionError.value = '单次最多删除 100 个漫画'
    batchDeleteDialog.value = false
    return
  }
  batchDeleteLoading.value = true
  actionError.value = ''
  actionNotice.value = ''
  try {
    const result = await batchDeleteMangas(selected.value)
    if (result.failed_count > 0) {
      const failed = result.items
        .filter((item) => !item.succeeded)
        .map((item) => `${item.manga_id}（${item.error_message ?? item.error_code ?? '未知错误'}）`)
        .join('、')
      actionError.value = `批量删除完成：成功 ${result.succeeded_count} 个，失败 ${result.failed_count} 个：${failed}`
    } else {
      actionNotice.value = `已删除 ${result.succeeded_count} 个漫画`
    }
    batchDeleteDialog.value = false
    await load()
  } catch (err) {
    actionError.value = errorMessage(err)
    batchDeleteDialog.value = false
  } finally {
    batchDeleteLoading.value = false
  }
}

watch(
  () => route.query,
  () => {
    readQuery()
    if (libraryListCache.key !== '' && libraryListCache.key === queryKey()) {
      // 缓存命中：先渲染旧数据消除等待感，再后台刷新保持一致
      mangas.value = libraryListCache.items
      total.value = libraryListCache.total
      pages.value = libraryListCache.pages
      void load({ silent: true })
      return
    }
    mangas.value = []
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

    <v-card class="mb-4">
      <v-card-text class="pb-2">
        <v-row dense>
          <v-col cols="12" md="4">
            <v-text-field
              v-model="filters.keyword"
              label="搜索关键字"
              prepend-inner-icon="mdi-magnify"
              clearable
              hide-details
              @keyup.enter="applySearch"
              @click:clear="clearSearch"
            />
          </v-col>
          <v-col cols="6" md="2">
            <v-select
              v-model="filters.scope"
              :items="scopeOptions"
              label="搜索范围"
              hide-details
            />
          </v-col>
          <v-col cols="6" md="2">
            <v-select
              v-model="filters.status"
              :items="statusOptions"
              label="状态"
              hide-details
              @update:model-value="updateQuery({ status: filters.status || undefined, page: 1 })"
            />
          </v-col>
          <v-col cols="6" md="2">
            <v-select
              v-model="filters.sort"
              :items="sortOptions"
              label="排序"
              hide-details
              @update:model-value="updateQuery({ sort: filters.sort, page: 1 })"
            />
          </v-col>
          <v-col cols="6" md="2" class="d-flex ga-2 align-center">
            <v-btn color="primary" block prepend-icon="mdi-magnify" @click="applySearch">
              搜索
            </v-btn>
          </v-col>
        </v-row>
      </v-card-text>
      <v-divider />
      <v-tabs
        :model-value="filters.collection"
        color="primary"
        aria-label="漫画库分组"
        @update:model-value="switchCollection($event as 'local' | 'favorites' | 'history' | 'blacklist_only')"
      >
        <v-tab value="local" prepend-icon="mdi-folder-outline">本地</v-tab>
        <v-tab value="favorites" prepend-icon="mdi-star-outline">收藏</v-tab>
        <v-tab value="history" prepend-icon="mdi-history">历史</v-tab>
        <v-tab value="blacklist_only" prepend-icon="mdi-lock">黑名单</v-tab>
      </v-tabs>
      <v-card-actions class="flex-wrap">
        <v-switch
          v-model="coverPreview"
          label="封面预览"
          color="primary"
          hide-details
          density="compact"
          class="ml-2"
        />
        <span class="text-body-2 text-medium-emphasis ml-2">
          共 {{ total }} 条
          <template v-if="selectedCount > 0">，已选 {{ selectedCount }} 条</template>
        </span>
        <v-spacer />
        <div class="action-scroll" :class="{ 'action-scroll--block': mobile }">
          <v-btn
            variant="tonal"
            :disabled="mangas.length === 0"
            @click="toggleSelectAll"
          >
            {{ allSelectableSelected ? '取消全选' : '全选' }}
          </v-btn>
          <v-btn
            variant="tonal"
            prepend-icon="mdi-download"
            :disabled="selectedCount === 0"
            @click="requestDownloadIds(selected)"
          >
            下载选中
          </v-btn>
          <v-btn
            variant="tonal"
            prepend-icon="mdi-content-copy"
            :disabled="selectedCount === 0"
            @click="copySelectedIds"
          >
            复制 ID
          </v-btn>
          <v-btn
            variant="tonal"
            color="error"
            prepend-icon="mdi-delete-sweep"
            :disabled="selectedCount === 0"
            @click="batchDeleteDialog = true"
          >
            批量删除
          </v-btn>
          <v-btn
            variant="tonal"
            color="warning"
            prepend-icon="mdi-lock"
            :disabled="selectedCount === 0"
            @click="openBatchBlacklist('add')"
          >
            批量拉黑
          </v-btn>
          <v-btn
            variant="tonal"
            color="warning"
            prepend-icon="mdi-lock-off"
            :disabled="!hasSelectedBlacklisted"
            @click="openBatchBlacklist('remove')"
          >
            批量解除
          </v-btn>
          <v-btn icon="mdi-refresh" variant="text" aria-label="刷新" @click="load" />
        </div>
      </v-card-actions>
    </v-card>

    <v-card>
      <v-progress-linear v-if="loading" indeterminate />

      <EmptyState
        v-if="!loading && mangas.length === 0"
        icon="mdi-bookshelf"
        title="没有找到漫画"
        description="调整筛选条件，或前往漫画下载页请求下载新漫画。"
      />

      <template v-else-if="!mobile">
        <v-table>
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
              <th>标题</th>
              <th class="text-no-wrap">漫画 ID</th>
              <th class="text-no-wrap">章节 / 页数</th>
              <th>标签</th>
              <th>状态</th>
              <th class="text-no-wrap">下载时间</th>
              <th class="text-no-wrap">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="manga in mangas" :key="manga.id">
              <td>
                <v-checkbox-btn
                  v-model="selected"
                  :value="manga.id"
                  :aria-label="`选择 ${manga.title}`"
                />
              </td>
              <td>
                <router-link
                  class="text-primary text-decoration-none"
                  :to="{
                    name: 'manga-detail',
                    params: { mangaId: manga.id },
                    query: route.query,
                  }"
                >
                  {{ manga.title }}
                </router-link>
              </td>
              <td class="text-no-wrap">{{ manga.id }}</td>
              <td class="text-no-wrap">{{ manga.chapter_count }} / {{ manga.page_count }}</td>
              <td>
                <v-chip
                  v-for="tag in manga.tags"
                  :key="tag"
                  size="x-small"
                  class="mr-1"
                  variant="tonal"
                >
                  {{ tag }}
                </v-chip>
                <span v-if="manga.tags.length === 0">—</span>
              </td>
              <td>
                <v-chip
                  size="small"
                  variant="tonal"
                  :color="colorOf(MANGA_STATUS_COLORS, mangaStatusKey(manga))"
                >
                  {{ labelOf(MANGA_STATUS_LABELS, mangaStatusKey(manga)) }}
                </v-chip>
              </td>
              <td class="text-no-wrap">{{ formatDateTime(manga.downloaded_at) }}</td>
              <td class="text-no-wrap">
                <v-btn
                  v-if="manga.files.length > 0"
                  icon="mdi-file-download-outline"
                  size="small"
                  variant="text"
                  :href="fileDownloadUrl(manga.files[0].id)"
                  aria-label="下载 PDF"
                />
                <v-btn
                  v-else
                  icon="mdi-file-download-outline"
                  size="small"
                  variant="text"
                  disabled
                  aria-label="没有可下载的文件"
                />
                <v-btn
                  :icon="manga.is_favorite ? 'mdi-star' : 'mdi-star-outline'"
                  :color="manga.is_favorite ? 'warning' : undefined"
                  size="small"
                  variant="text"
                  :loading="favoriteBusy[manga.id]"
                  :disabled="favoriteBusy[manga.id] || manga.status === 'deleted'"
                  :aria-label="manga.is_favorite ? '取消收藏' : '收藏'"
                  :aria-pressed="manga.is_favorite"
                  @click="toggleFavorite(manga)"
                />
                <v-btn
                  icon="mdi-delete"
                  size="small"
                  variant="text"
                  color="error"
                  aria-label="删除"
                  :disabled="manga.status === 'deleted'"
                  @click="askDelete(manga)"
                />
                <v-btn
                  :icon="manga.is_blacklisted ? 'mdi-lock-off' : 'mdi-lock'"
                  :color="manga.is_blacklisted ? 'warning' : undefined"
                  size="small"
                  variant="text"
                  :loading="blacklistBusy[manga.id]"
                  :disabled="blacklistBusy[manga.id] || manga.status === 'deleted'"
                  :aria-label="manga.is_blacklisted ? '解除拉黑' : '加入黑名单'"
                  :aria-pressed="manga.is_blacklisted"
                  @click="manga.is_blacklisted ? askUnblacklist(manga) : askBlacklist(manga)"
                />
              </td>
            </tr>
          </tbody>
        </v-table>
      </template>

      <template v-else>
        <v-list lines="two">
          <v-list-item v-for="manga in mangas" :key="manga.id">
            <template #prepend>
              <v-checkbox-btn
                v-model="selected"
                :value="manga.id"
                :aria-label="`选择 ${manga.title}`"
              />
            </template>
            <v-list-item-title class="text-wrap">{{ manga.title }}</v-list-item-title>
            <v-list-item-subtitle class="text-wrap">
              ID {{ manga.id }} · {{ manga.chapter_count }} 章 ·
              {{ manga.page_count }} 页 · {{ formatDateTime(manga.downloaded_at) }}
            </v-list-item-subtitle>
            <div class="mt-1">
              <v-chip
                size="x-small"
                variant="tonal"
                :color="colorOf(MANGA_STATUS_COLORS, mangaStatusKey(manga))"
                class="mr-1"
              >
                {{ labelOf(MANGA_STATUS_LABELS, mangaStatusKey(manga)) }}
              </v-chip>
              <v-chip
                v-for="tag in manga.tags"
                :key="tag"
                size="x-small"
                class="mr-1"
                variant="outlined"
              >
                {{ tag }}
              </v-chip>
            </div>
            <template #append>
              <div class="d-flex flex-column">
                <v-btn
                  icon="mdi-chevron-right"
                  size="small"
                  variant="text"
                  :to="{
                    name: 'manga-detail',
                    params: { mangaId: manga.id },
                    query: route.query,
                  }"
                  aria-label="查看详情"
                />
                <v-btn
                  v-if="manga.files.length > 0"
                  icon="mdi-file-download-outline"
                  size="small"
                  variant="text"
                  :href="fileDownloadUrl(manga.files[0].id)"
                  aria-label="下载 PDF"
                />
                <v-btn
                  v-else
                  icon="mdi-file-download-outline"
                  size="small"
                  variant="text"
                  disabled
                  aria-label="没有可下载的文件"
                />
                <v-btn
                  :icon="manga.is_favorite ? 'mdi-star' : 'mdi-star-outline'"
                  :color="manga.is_favorite ? 'warning' : undefined"
                  size="small"
                  variant="text"
                  :loading="favoriteBusy[manga.id]"
                  :disabled="favoriteBusy[manga.id] || manga.status === 'deleted'"
                  :aria-label="manga.is_favorite ? '取消收藏' : '收藏'"
                  :aria-pressed="manga.is_favorite"
                  @click="toggleFavorite(manga)"
                />
                <v-btn
                  icon="mdi-delete"
                  size="small"
                  variant="text"
                  color="error"
                  aria-label="删除"
                  :disabled="manga.status === 'deleted'"
                  @click="askDelete(manga)"
                />
                <v-btn
                  :icon="manga.is_blacklisted ? 'mdi-lock-off' : 'mdi-lock'"
                  :color="manga.is_blacklisted ? 'warning' : undefined"
                  size="small"
                  variant="text"
                  :loading="blacklistBusy[manga.id]"
                  :disabled="blacklistBusy[manga.id] || manga.status === 'deleted'"
                  :aria-label="manga.is_blacklisted ? '解除拉黑' : '加入黑名单'"
                  :aria-pressed="manga.is_blacklisted"
                  @click="manga.is_blacklisted ? askUnblacklist(manga) : askBlacklist(manga)"
                />
              </div>
            </template>
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
      v-model="deleteDialog"
      :title="`删除《${deleteTarget?.title ?? ''}》？`"
      text="将删除全部章节文件和关联记录，保留已删除漫画的元数据供查询，此操作不可撤销。"
      confirm-text="确认删除"
      :loading="deleteLoading"
      @confirm="confirmDelete"
    />

    <ConfirmDialog
      v-model="batchDeleteDialog"
      :title="`批量删除 ${selectedCount} 个漫画？`"
      :text="`将删除选中的 ${selectedCount} 个漫画的全部章节文件和关联记录，保留已删除漫画的元数据供查询，此操作不可撤销。`"
      confirm-text="确认批量删除"
      :loading="batchDeleteLoading"
      @confirm="confirmBatchDelete"
    />

    <ConfirmDialog
      v-model="blacklistDialog"
      :title="blacklistMode === 'add'
        ? `拉黑《${blacklistTarget?.title ?? ''}》？`
        : `解除拉黑《${blacklistTarget?.title ?? ''}》？`"
      :text="blacklistMode === 'add'
        ? '加入黑名单后，该漫画的下载请求将被跳过。默认不删除本地 PDF；若开启删除绑定则会同时执行删除。'
        : '移出黑名单后，该漫画可重新下载。已经删除的漫画和 PDF 不会恢复。'"
      :confirm-text="blacklistMode === 'add' ? '确认拉黑' : '确认解除'"
      :loading="blacklistLoading"
      @confirm="confirmBlacklist"
    />

    <ConfirmDialog
      v-model="batchBlacklistDialog"
      :title="batchBlacklistMode === 'add'
        ? `批量拉黑 ${selectedCount} 个漫画？`
        : `批量解除 ${selectedBlacklistedIds.length} 个漫画？`"
      :text="batchBlacklistMode === 'add'
        ? '选中的漫画将加入黑名单，之后的下载请求会被跳过。默认不删除本地 PDF；若开启删除绑定则会同时执行删除。'
        : '仅会解除选中项中已拉黑的漫画。解除后这些漫画可重新下载，已经删除的内容不会恢复。'"
      :confirm-text="batchBlacklistMode === 'add' ? '确认批量拉黑' : '确认批量解除'"
      :loading="batchBlacklistLoading"
      @confirm="confirmBatchBlacklist"
    />
  </div>
</template>
