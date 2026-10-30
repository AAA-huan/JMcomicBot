<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDisplay } from 'vuetify'

import { errorMessage } from '@/api/client'
import {
  favoriteJmAlbums,
  getJmAlbumDetail,
  searchAuthorByAuthor,
} from '@/api/jmSearch'
import type { JmAlbumDetail, JmSearchAlbum } from '@/api/jmSearch'
import { requestDownloads } from '@/api/tasks'
import EmptyState from '@/components/EmptyState.vue'
import PaginationBar from '@/components/PaginationBar.vue'
import { copyText } from '@/utils/clipboard'

const route = useRoute()
const router = useRouter()
const { mobile } = useDisplay()

const albums = ref<JmSearchAlbum[]>([])
const selected = ref<string[]>([])
const page = ref(1)
const pageCount = ref(0)
const pageSize = ref(20)
const total = ref(0)
const loading = ref(false)
const favoriting = ref(false)
const error = ref('')
const actionError = ref('')
const actionNotice = ref('')

const detailDialog = ref(false)
const detailLoading = ref(false)
const detailError = ref('')
const detail = ref<JmAlbumDetail | null>(null)
const detailAlbumId = ref('')

/** 从路由查询参数读取字符串，数组和空值统一视为空串。 */
function queryString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

const author = computed(() => queryString(route.query.author))
const from = computed(() => queryString(route.query.from))
const selectedCount = computed(() => selected.value.length)
const allSelected = computed(
  () => albums.value.length > 0 && selected.value.length === albums.value.length,
)

/** 全选/取消全选当前页；翻页时清空选择，不跨页保留。 */
function toggleSelectAll(): void {
  selected.value = allSelected.value
    ? []
    : albums.value.map((album) => album.album_id)
}

/** 按作者加载指定页；空作者直接提示，不发起远程请求。 */
async function load(targetPage = page.value): Promise<void> {
  const currentAuthor = author.value
  selected.value = []
  if (!currentAuthor) {
    albums.value = []
    total.value = 0
    pageCount.value = 0
    page.value = 1
    error.value = '缺少作者参数，请从漫画详情页进入'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const result = await searchAuthorByAuthor(currentAuthor, targetPage)
    albums.value = result.results
    page.value = result.page
    pageCount.value = result.page_count
    pageSize.value = result.page_size
    total.value = result.total
  } catch (err) {
    error.value = errorMessage(err)
    albums.value = []
    total.value = 0
    pageCount.value = 0
  } finally {
    loading.value = false
  }
}

/** 下载远程漫画，复用任务管理页的批量下载接口。 */
async function requestDownloadIds(ids: string[]): Promise<void> {
  actionError.value = ''
  actionNotice.value = ''
  if (ids.length === 0) {
    actionError.value = '请选择至少一个漫画'
    return
  }
  if (ids.length > 100) {
    actionError.value = '单次最多请求 100 个漫画'
    return
  }
  try {
    const result = await requestDownloads(ids)
    const parts = [`已提交 ${result.queued_count} 个，正在加入队列`]
    if (result.skipped_blacklisted.length > 0) {
      parts.push(
        `${result.skipped_blacklisted.length} 个已被拉黑跳过（${result.skipped_blacklisted.join('、')}）`,
      )
    }
    if (result.skipped_downloaded.length > 0) {
      parts.push(
        `${result.skipped_downloaded.length} 个已下载跳过（${result.skipped_downloaded.join('、')}）`,
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

/** 收藏选中漫画：联网存入本地库并标记管理员收藏，不下载本体。 */
async function favoriteAlbums(ids: string[]): Promise<void> {
  actionError.value = ''
  actionNotice.value = ''
  if (ids.length === 0) {
    actionError.value = '请选择至少一个漫画'
    return
  }
  if (ids.length > 100) {
    actionError.value = '单次最多收藏 100 个漫画'
    return
  }
  favoriting.value = true
  try {
    const result = await favoriteJmAlbums(ids)
    const failedIds = new Set(result.failed.map((item) => item.album_id))
    // 只更新成功项，失败项保留原状态等待用户重试
    for (const album of albums.value) {
      if (!ids.includes(album.album_id) || failedIds.has(album.album_id)) continue
      album.local.exists = true
      album.local.favorited = true
      if (!album.local.status) album.local.status = 'favorited'
    }
    if (detail.value && ids.includes(detail.value.album_id) && !failedIds.has(detail.value.album_id)) {
      detail.value.local.exists = true
      detail.value.local.favorited = true
      if (!detail.value.local.status) detail.value.local.status = 'favorited'
    }
    const parts: string[] = []
    if (result.collected_count > 0) parts.push(`已收藏 ${result.collected_count} 本`)
    if (result.already_count > 0) parts.push(`${result.already_count} 本已在本地`)
    if (result.failed.length > 0) {
      parts.push(
        `${result.failed.length} 本收藏失败（${result.failed.map((item) => `${item.album_id}: ${item.error}`).join('；')}）`,
      )
    }
    actionNotice.value = parts.join('，') || '没有需要收藏的漫画'
    selected.value = []
  } catch (err) {
    actionError.value = errorMessage(err)
  } finally {
    favoriting.value = false
  }
}

/** 本地状态标签：已下载优先，文件丢失单独提示。 */
function localStatusLabel(local: JmSearchAlbum['local']): string | null {
  if (local.downloaded) return '已下载'
  if (local.status === 'missing_file' || local.status === 'downloaded') return '文件缺失'
  if (local.favorited || local.status === 'favorited') return '已收藏'
  if (local.exists) return '本地已有'
  return null
}

/** 关闭远程详情并跳转本地漫画详情页。 */
function openLocalDetail(): void {
  if (!detail.value) return
  const albumId = detail.value.album_id
  detailDialog.value = false
  void router.push({ name: 'manga-detail', params: { mangaId: albumId } })
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

/** 打开远程漫画详情对话框，失败时在对话框内展示中文错误。 */
async function openDetail(albumId: string): Promise<void> {
  detailAlbumId.value = albumId
  detail.value = null
  detailError.value = ''
  detailDialog.value = true
  detailLoading.value = true
  try {
    detail.value = await getJmAlbumDetail(albumId)
  } catch (err) {
    detailError.value = errorMessage(err)
  } finally {
    detailLoading.value = false
  }
}

async function downloadDetail(): Promise<void> {
  if (!detail.value) return
  await requestDownloadIds([detail.value.album_id])
}

watch(
  () => route.query.author,
  () => {
    page.value = 1
    void load(1)
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
        <v-btn v-if="author" size="small" variant="text" @click="load(page)">重试</v-btn>
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
        <div class="d-flex flex-wrap align-center ga-3">
          <div class="text-subtitle-1">查询作者：{{ author || '—' }}</div>
          <v-chip v-if="from" size="small" variant="outlined">
            来自漫画 ID {{ from }}
          </v-chip>
          <v-spacer />
          <v-btn
            variant="tonal"
            size="small"
            prepend-icon="mdi-arrow-left"
            @click="router.back()"
          >
            返回
          </v-btn>
        </div>
        <div class="text-body-2 text-medium-emphasis mt-1">
          共 {{ total }} 部作品
          <template v-if="selectedCount > 0">，已选 {{ selectedCount }} 部</template>
        </div>
      </v-card-text>
      <v-card-actions class="flex-wrap">
        <div class="action-scroll" :class="{ 'action-scroll--mobile': mobile }">
          <v-btn
            variant="tonal"
            :disabled="albums.length === 0"
            @click="toggleSelectAll"
          >
            {{ allSelected ? '取消全选' : '全选' }}
          </v-btn>
          <v-btn
            variant="tonal"
            prepend-icon="mdi-star"
            :disabled="selectedCount === 0 || favoriting"
            :loading="favoriting"
            @click="favoriteAlbums(selected)"
          >
            收藏选中
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
        </div>
      </v-card-actions>
    </v-card>

    <v-card>
      <v-progress-linear v-if="loading" indeterminate />

      <EmptyState
        v-if="!loading && albums.length === 0"
        icon="mdi-account-search"
        title="没有找到该作者的作品"
        description="请确认作者名是否正确，或稍后重试。"
      />

      <template v-else-if="!mobile">
        <v-table>
          <thead>
            <tr>
              <th style="width: 44px">
                <v-checkbox-btn
                  :model-value="allSelected"
                  :indeterminate="selected.length > 0 && !allSelected"
                  aria-label="全选"
                  @update:model-value="toggleSelectAll"
                />
              </th>
              <th>标题</th>
              <th class="text-no-wrap">漫画 ID</th>
              <th>标签</th>
              <th class="text-no-wrap">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="album in albums" :key="album.album_id">
              <td>
                <v-checkbox-btn
                  v-model="selected"
                  :value="album.album_id"
                  :aria-label="`选择 ${album.title}`"
                />
              </td>
              <td>
                <a
                  href="#"
                  class="text-primary text-decoration-none"
                  @click.prevent="openDetail(album.album_id)"
                >
                  {{ album.title }}
                </a>
                <v-chip
                  v-if="localStatusLabel(album.local)"
                  size="x-small"
                  class="ml-2"
                  :color="album.local.downloaded ? 'success' : 'warning'"
                  variant="tonal"
                >
                  {{ localStatusLabel(album.local) }}
                </v-chip>
              </td>
              <td class="text-no-wrap">{{ album.album_id }}</td>
              <td>
                <v-chip
                  v-for="tag in album.tags"
                  :key="tag"
                  size="x-small"
                  class="mr-1"
                  variant="tonal"
                >
                  {{ tag }}
                </v-chip>
                <span v-if="album.tags.length === 0">—</span>
              </td>
              <td class="text-no-wrap">
                <v-btn
                  size="small"
                  variant="text"
                  :prepend-icon="album.local.downloaded ? 'mdi-check' : 'mdi-download'"
                  :disabled="album.local.downloaded"
                  :aria-label="`下载 ${album.title}`"
                  @click="requestDownloadIds([album.album_id])"
                >
                  {{ album.local.downloaded ? '已下载' : '下载' }}
                </v-btn>
                <v-btn
                  size="small"
                  variant="text"
                  :prepend-icon="album.local.favorited ? 'mdi-star' : 'mdi-star-outline'"
                  :disabled="album.local.favorited"
                  :aria-label="`收藏 ${album.title}`"
                  @click="favoriteAlbums([album.album_id])"
                >
                  {{ album.local.favorited ? '已收藏' : '收藏' }}
                </v-btn>
                <v-btn
                  size="small"
                  variant="text"
                  prepend-icon="mdi-information-outline"
                  :aria-label="`查看 ${album.title} 的详情`"
                  @click="openDetail(album.album_id)"
                >
                  查看详情
                </v-btn>
              </td>
            </tr>
          </tbody>
        </v-table>
      </template>

      <template v-else>
        <v-list lines="two">
          <v-list-item v-for="album in albums" :key="album.album_id">
            <template #prepend>
              <v-checkbox-btn
                v-model="selected"
                :value="album.album_id"
                :aria-label="`选择 ${album.title}`"
              />
            </template>
            <v-list-item-title class="text-wrap">
              <a
                href="#"
                class="text-primary text-decoration-none"
                @click.prevent="openDetail(album.album_id)"
              >
                {{ album.title }}
              </a>
            </v-list-item-title>
            <v-list-item-subtitle class="text-wrap">
              ID {{ album.album_id }}
              <v-chip
                v-if="localStatusLabel(album.local)"
                size="x-small"
                class="ml-2"
                :color="album.local.downloaded ? 'success' : 'warning'"
                variant="tonal"
              >
                {{ localStatusLabel(album.local) }}
              </v-chip>
            </v-list-item-subtitle>
            <div class="mt-1">
              <v-chip
                v-for="tag in album.tags"
                :key="tag"
                size="x-small"
                class="mr-1"
                variant="outlined"
              >
                {{ tag }}
              </v-chip>
              <span v-if="album.tags.length === 0">—</span>
            </div>
            <template #append>
              <div class="d-flex flex-column">
                <v-btn
                  :icon="album.local.downloaded ? 'mdi-check' : 'mdi-download'"
                  size="small"
                  variant="text"
                  :disabled="album.local.downloaded"
                  :aria-label="`下载 ${album.title}`"
                  @click="requestDownloadIds([album.album_id])"
                />
                <v-btn
                  :icon="album.local.favorited ? 'mdi-star' : 'mdi-star-outline'"
                  size="small"
                  variant="text"
                  :disabled="album.local.favorited"
                  :aria-label="`收藏 ${album.title}`"
                  @click="favoriteAlbums([album.album_id])"
                />
                <v-btn
                  icon="mdi-information-outline"
                  size="small"
                  variant="text"
                  :aria-label="`查看 ${album.title} 的详情`"
                  @click="openDetail(album.album_id)"
                />
              </div>
            </template>
          </v-list-item>
        </v-list>
      </template>

      <v-divider v-if="pageCount > 1" />
      <PaginationBar
        :page="page"
        :pages="pageCount"
        :page-size="pageSize"
        :loading="loading"
        @update:page="load"
      />
    </v-card>

    <v-dialog v-model="detailDialog" max-width="640">
      <v-card>
        <v-card-title class="text-subtitle-1">远程漫画详情</v-card-title>
        <v-card-text>
          <v-progress-linear v-if="detailLoading" indeterminate class="mb-3" />
          <v-alert
            v-if="detailError"
            type="error"
            variant="tonal"
            density="comfortable"
          >
            {{ detailError }}
            <template #append>
              <v-btn
                size="small"
                variant="text"
                @click="openDetail(detailAlbumId)"
              >
                重试
              </v-btn>
            </template>
          </v-alert>
          <template v-else-if="detail">
            <v-row dense>
              <v-col cols="12" sm="6">
                <div class="text-caption text-medium-emphasis">标题</div>
                <div class="text-body-1">{{ detail.title }}</div>
              </v-col>
              <v-col cols="12" sm="6">
                <div class="text-caption text-medium-emphasis">作者</div>
                <div class="text-body-1">{{ detail.author || '—' }}</div>
              </v-col>
              <v-col cols="12" sm="6">
                <div class="text-caption text-medium-emphasis">漫画 ID</div>
                <div class="text-body-1">{{ detail.album_id }}</div>
              </v-col>
              <v-col cols="12" sm="6">
                <div class="text-caption text-medium-emphasis">总页数</div>
                <div class="text-body-1">{{ detail.page_count }}</div>
              </v-col>
              <v-col v-if="localStatusLabel(detail.local)" cols="12">
                <div class="text-caption text-medium-emphasis">本地状态</div>
                <v-chip
                  size="small"
                  :color="detail.local.downloaded ? 'success' : 'warning'"
                  variant="tonal"
                >
                  {{ localStatusLabel(detail.local) }}
                </v-chip>
              </v-col>
              <v-col cols="12">
                <div class="text-caption text-medium-emphasis">标签</div>
                <div>
                  <v-chip
                    v-for="tag in detail.tags"
                    :key="tag"
                    size="x-small"
                    variant="tonal"
                    class="mr-1"
                  >
                    {{ tag }}
                  </v-chip>
                  <span v-if="detail.tags.length === 0">—</span>
                </div>
              </v-col>
              <v-col cols="12">
                <div class="text-caption text-medium-emphasis">
                  章节（{{ detail.chapter_ids.length }}）
                </div>
                <div class="d-flex flex-wrap ga-1 mt-1">
                  <v-chip
                    v-for="chapterId in detail.chapter_ids"
                    :key="chapterId"
                    size="small"
                    variant="outlined"
                  >
                    {{ chapterId }}
                  </v-chip>
                  <span v-if="detail.chapter_ids.length === 0">—</span>
                </div>
              </v-col>
            </v-row>
          </template>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="detailDialog = false">关闭</v-btn>
          <v-btn
            v-if="detail?.local.exists"
            variant="tonal"
            color="primary"
            prepend-icon="mdi-bookshelf"
            aria-label="查看本地详情"
            @click="openLocalDetail"
          >
            查看本地详情
          </v-btn>
          <v-btn
            variant="tonal"
            color="primary"
            :prepend-icon="detail?.local.downloaded ? 'mdi-check' : 'mdi-download'"
            :disabled="!detail || detail.local.downloaded"
            aria-label="下载详情漫画"
            @click="downloadDetail"
          >
            {{ detail?.local.downloaded ? '已下载' : '下载' }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>
