<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDisplay } from 'vuetify'

import { errorMessage } from '@/api/client'
import { setFavorite } from '@/api/favorites'
import { batchDeleteMangas, deleteManga, listMangas } from '@/api/mangas'
import { requestDownloads } from '@/api/tasks'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import EmptyState from '@/components/EmptyState.vue'
import type { Manga } from '@/types/api'
import { formatDateTime, parseMangaIds } from '@/utils/format'
import {
  colorOf,
  labelOf,
  MANGA_STATUS_COLORS,
  MANGA_STATUS_LABELS,
} from '@/utils/labels'

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

const deleteTarget = ref<Manga | null>(null)
const deleteDialog = ref(false)
const deleteLoading = ref(false)

const batchDeleteDialog = ref(false)
const batchDeleteLoading = ref(false)

const downloadDialog = ref(false)
const downloadInput = ref('')
const downloadLoading = ref(false)

const selectedCount = computed(() => selected.value.length)

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
  filters.favoriteOnly = query.favorite_only === 'true'
  filters.status = typeof query.status === 'string' ? query.status : ''
  filters.sort = typeof query.sort === 'string' ? query.sort : 'downloaded_at_desc'
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
  if (ids.length > 20) {
    actionError.value = '单次最多请求 20 个漫画'
    return
  }
  downloadLoading.value = true
  try {
    const result = await requestDownloads(ids)
    const parts = [`已入队 ${result.queued_count} 个`]
    if (result.duplicate_count > 0) {
      const duplicates = result.items
        .filter((item) => item.status === 'duplicate')
        .map((item) => item.manga_id)
      parts.push(
        `${result.duplicate_count} 个已有活动任务（${duplicates.join('、')}）`,
      )
    }
    actionNotice.value = parts.join('，')
    downloadDialog.value = false
    downloadInput.value = ''
    selected.value = []
  } catch (err) {
    actionError.value = errorMessage(err)
  } finally {
    downloadLoading.value = false
  }
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
      <v-card-actions class="flex-wrap">
        <v-switch
          v-model="filters.favoriteOnly"
          label="仅看收藏"
          color="primary"
          hide-details
          density="compact"
          class="ml-2"
          @update:model-value="updateQuery({ favorite_only: filters.favoriteOnly ? 'true' : undefined, page: 1 })"
        />
        <span class="text-body-2 text-medium-emphasis ml-2">
          共 {{ total }} 条
          <template v-if="selectedCount > 0">，已选 {{ selectedCount }} 条</template>
        </span>
        <v-spacer />
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
          color="error"
          prepend-icon="mdi-delete-sweep"
          :disabled="selectedCount === 0"
          @click="batchDeleteDialog = true"
        >
          批量删除
        </v-btn>
        <v-btn
          color="primary"
          variant="tonal"
          prepend-icon="mdi-plus"
          @click="downloadDialog = true"
        >
          新建下载
        </v-btn>
        <v-btn icon="mdi-refresh" variant="text" aria-label="刷新" @click="load" />
      </v-card-actions>
    </v-card>

    <v-card>
      <v-progress-linear v-if="loading" indeterminate />

      <EmptyState
        v-if="!loading && mangas.length === 0"
        icon="mdi-bookshelf"
        title="没有找到漫画"
        description="调整筛选条件，或在任务页请求下载新漫画。"
      />

      <template v-else-if="!mobile">
        <v-table>
          <thead>
            <tr>
              <th style="width: 44px">
                <v-checkbox-btn
                  :model-value="selected.length === mangas.length && mangas.length > 0"
                  :indeterminate="selected.length > 0 && selected.length < mangas.length"
                  aria-label="全选"
                  @update:model-value="selected = $event ? mangas.map((m) => m.id) : []"
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
                  :color="colorOf(MANGA_STATUS_COLORS, manga.status)"
                >
                  {{ labelOf(MANGA_STATUS_LABELS, manga.status) }}
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
                  :disabled="favoriteBusy[manga.id]"
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
                  @click="askDelete(manga)"
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
                :color="colorOf(MANGA_STATUS_COLORS, manga.status)"
                class="mr-1"
              >
                {{ labelOf(MANGA_STATUS_LABELS, manga.status) }}
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
                  :disabled="favoriteBusy[manga.id]"
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
                  @click="askDelete(manga)"
                />
              </div>
            </template>
          </v-list-item>
        </v-list>
      </template>

      <v-divider v-if="pages > 1" />
      <div class="d-flex flex-wrap align-center justify-center pa-2">
        <v-pagination
          v-if="pages > 1"
          :model-value="filters.page"
          :length="pages"
          :total-visible="5"
          @update:model-value="updateQuery({ page: $event })"
        />
        <v-select
          :model-value="filters.pageSize"
          :items="pageSizeOptions"
          label="每页"
          hide-details
          density="compact"
          class="mt-2"
          style="max-width: 120px"
          @update:model-value="updateQuery({ page_size: $event, page: 1 })"
        />
      </div>
    </v-card>

    <ConfirmDialog
      v-model="deleteDialog"
      :title="`删除《${deleteTarget?.title ?? ''}》？`"
      text="将删除该漫画的数据库记录与全部章节文件，此操作不可撤销。"
      confirm-text="确认删除"
      :loading="deleteLoading"
      @confirm="confirmDelete"
    />

    <ConfirmDialog
      v-model="batchDeleteDialog"
      :title="`批量删除 ${selectedCount} 个漫画？`"
      :text="`将删除选中的 ${selectedCount} 个漫画及其全部章节文件，此操作不可撤销。`"
      confirm-text="确认批量删除"
      :loading="batchDeleteLoading"
      @confirm="confirmBatchDelete"
    />

    <v-dialog v-model="downloadDialog" max-width="480">
      <v-card>
        <v-card-title>新建下载请求</v-card-title>
        <v-card-text>
          <p class="text-body-2 text-medium-emphasis mb-2">
            输入一个或多个漫画 ID，用逗号、句号或换行分隔，单次最多 20 个。
          </p>
          <v-textarea
            v-model="downloadInput"
            label="漫画 ID"
            rows="3"
            auto-grow
            placeholder="例如：350234, 422866"
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="downloadDialog = false">取消</v-btn>
          <v-btn
            color="primary"
            :loading="downloadLoading"
            @click="requestDownloadIds(parseMangaIds(downloadInput))"
          >
            请求下载
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>
