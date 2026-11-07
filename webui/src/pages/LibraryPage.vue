<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDisplay } from 'vuetify'

import { errorMessage } from '@/api/client'
import { setFavorite } from '@/api/favorites'
import {
  addFolderMangas,
  createFolder,
  deleteFolder,
  listFolders,
  removeFolderMangas,
  renameFolder,
} from '@/api/folders'
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
import { useToast } from '@/stores/toast'
import type { Folder, Manga } from '@/types/api'
import { copyText } from '@/utils/clipboard'
import { formatDateTime } from '@/utils/format'
import {
  colorOf,
  labelOf,
  MANGA_STATUS_COLORS,
  MANGA_STATUS_LABELS,
} from '@/utils/labels'

const { coverPreview } = useCoverPreview()
const toast = useToast()
const route = useRoute()
const router = useRouter()
const { mobile } = useDisplay()

const pageSizeOptions = [20, 50, 100]
const statusOptions = [
  { value: '', title: '全部状态' },
  { value: 'downloaded', title: '已下载' },
  { value: 'downloaded_unfavorited', title: '已下载未收藏' },
  { value: 'favorited', title: '已收藏未下载' },
  { value: 'missing_file', title: '文件缺失' },
  { value: 'invalid', title: '无效记录' },
  { value: 'deleted', title: '已删除' },
]
const sortOptions = [
  { value: 'downloaded_at', title: '下载时间' },
  { value: 'read_at', title: '阅读时间' },
  { value: 'title', title: '标题' },
  { value: 'id', title: '漫画 ID' },
  { value: 'author', title: '作者' },
]

// 旧版把字段与方向合并成单一枚举值（如 downloaded_at_desc），兼容链接时拆分为新格式
const legacySortValues: Record<string, { sort: string; order: 'asc' | 'desc' }> = {
  read_at_desc: { sort: 'read_at', order: 'desc' },
  downloaded_at_desc: { sort: 'downloaded_at', order: 'desc' },
  downloaded_at_asc: { sort: 'downloaded_at', order: 'asc' },
  title_asc: { sort: 'title', order: 'asc' },
  title_desc: { sort: 'title', order: 'desc' },
  id_asc: { sort: 'id', order: 'asc' },
  id_desc: { sort: 'id', order: 'desc' },
}

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
  sort: 'downloaded_at',
  order: 'desc' as 'asc' | 'desc',
  page: 1,
  pageSize: 20,
  favoriteOnly: false,
  collection: 'local' as 'local' | 'favorites' | 'history' | 'blacklist_only' | 'folder',
  // 文件夹页签内的当前文件夹 ID；空字符串表示停留在文件夹网格视图
  folderId: '',
})

/** 文件夹页签的网格视图（未进入具体文件夹）。 */
const folderGridView = computed(
  () => filters.collection === 'folder' && filters.folderId === '',
)

/** 已进入具体文件夹：列表按 folder_id 筛选，批量区提供移出。 */
const insideFolder = computed(
  () => filters.collection === 'folder' && filters.folderId !== '',
)

/** 各分组的默认排序字段：历史按阅读时间，其余按下载时间。 */
function defaultSortField(collection: string): string {
  return collection === 'history' ? 'read_at' : 'downloaded_at'
}

/**
 * 状态下拉的实际选项：「已下载未收藏」与收藏筛选互斥，
 * 收藏分组下置灰禁止选择，其余选项原样。
 */
const statusItems = computed(() =>
  statusOptions.map((option) => ({
    ...option,
    disabled:
      option.value === 'downloaded_unfavorited' && filters.collection === 'favorites',
  })),
)

/**
 * 从 URL 解析排序字段与方向。
 *
 * 旧链接的组合值（如 downloaded_at_desc）拆分为新格式；
 * 未知值回落分组默认并标记需要规范化 URL，不向后端透传旧格式。
 */
function readSortQuery(query: Record<string, unknown>): boolean {
  const rawSort = typeof query.sort === 'string' ? query.sort : ''
  const legacy = legacySortValues[rawSort]
  if (legacy) {
    filters.sort = legacy.sort
    filters.order = legacy.order
    return true
  }
  const knownField = sortOptions.some((option) => option.value === rawSort)
  if (!rawSort || !knownField) {
    filters.sort = defaultSortField(filters.collection)
    filters.order = query.order === 'asc' ? 'asc' : 'desc'
    return rawSort !== '' && !knownField
  }
  filters.sort = rawSort
  filters.order = query.order === 'asc' ? 'asc' : 'desc'
  return false
}

/** 倒序开关：开=desc、关=asc，与排序字段分离。 */
const orderDesc = computed({
  get: () => filters.order === 'desc',
  set: (value: boolean) => { filters.order = value ? 'desc' : 'asc' },
})

function applyOrderChange(): void {
  updateQuery({ order: filters.order, page: 1 })
}

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

// ===== 本地自定义文件夹 =====
const folders = ref<Folder[]>([])
const foldersLoading = ref(false)

// 新建/重命名共用弹窗：folderRenamingId 为 null 表示新建，否则为被重命名的文件夹 ID
const folderFormDialog = ref(false)
const folderRenamingId = ref<number | null>(null)
const folderNameInput = ref('')
const folderFormLoading = ref(false)

const folderDeleteTarget = ref<Folder | null>(null)
const folderDeleteDialog = ref(false)
const folderDeleteLoading = ref(false)

// 批量加入文件夹弹窗
const batchAddFolderDialog = ref(false)
const batchAddFolderLoading = ref(false)
const batchAddFolderIds = ref<number[]>([])

/** 单独拉取文件夹清单；静默模式下失败不打断主视图。 */
async function loadFolders(options: { silent?: boolean } = {}): Promise<void> {
  const silent = options.silent === true
  if (!silent) foldersLoading.value = true
  error.value = ''
  try {
    folders.value = await listFolders()
  } catch (err) {
    if (!silent) error.value = errorMessage(err)
  } finally {
    if (!silent) foldersLoading.value = false
  }
}

function openCreateFolder(): void {
  folderRenamingId.value = null
  folderNameInput.value = ''
  folderFormDialog.value = true
}

function openRenameFolder(folder: Folder): void {
  folderRenamingId.value = folder.id
  folderNameInput.value = folder.name
  folderFormDialog.value = true
}

/** 提交新建/重命名：重名由后端返回 409 并提示，不做本地猜测。 */
async function confirmFolderForm(): Promise<void> {
  const name = folderNameInput.value.trim()
  if (!name) {
    toast.error('请输入文件夹名称')
    return
  }
  if (name.length > 64) {
    toast.error('文件夹名称不能超过 64 个字符')
    return
  }
  folderFormLoading.value = true
  try {
    if (folderRenamingId.value === null) {
      const created = await createFolder(name)
      toast.success(`已新建文件夹「${created.name}」`)
    } else {
      await renameFolder(folderRenamingId.value, name)
      toast.success(`已重命名为「${name}」`)
    }
    folderFormDialog.value = false
    await loadFolders()
  } catch (err) {
    toast.error(errorMessage(err))
  } finally {
    folderFormLoading.value = false
  }
}

function askDeleteFolder(folder: Folder): void {
  folderDeleteTarget.value = folder
  folderDeleteDialog.value = true
}

/** 删除文件夹只解除分组关系，不删除漫画本体。 */
async function confirmDeleteFolder(): Promise<void> {
  const target = folderDeleteTarget.value
  if (!target) return
  folderDeleteLoading.value = true
  try {
    await deleteFolder(target.id)
    toast.success(`已删除文件夹「${target.name}」，漫画未删除`)
    folderDeleteDialog.value = false
    await loadFolders()
  } catch (err) {
    toast.error(errorMessage(err))
    folderDeleteDialog.value = false
  } finally {
    folderDeleteLoading.value = false
  }
}

/** 进入具体文件夹：URL 同时写 collection 与 folder_id，列表复用漫画视图。 */
function openFolder(folder: Folder): void {
  updateQuery({ collection: 'folder', folder_id: folder.id, page: 1 })
}

function exitFolder(): void {
  updateQuery({ collection: 'folder', folder_id: undefined, page: 1 })
}

const currentFolder = computed(
  () => folders.value.find((folder) => String(folder.id) === filters.folderId) ?? null,
)

async function openBatchAddFolder(): Promise<void> {
  if (selectedCount.value === 0) return
  batchAddFolderIds.value = []
  batchAddFolderDialog.value = true
  // 弹窗需要最新文件夹清单，其他页签首次进入时列表可能尚未加载
  await loadFolders({ silent: true })
}

/** 批量加入：对所选文件夹逐个提交，汇总新增数量。 */
async function confirmBatchAddFolder(): Promise<void> {
  const ids = [...selected.value]
  if (ids.length === 0) {
    batchAddFolderDialog.value = false
    return
  }
  if (batchAddFolderIds.value.length === 0) {
    toast.error('请至少选择一个文件夹')
    return
  }
  batchAddFolderLoading.value = true
  try {
    let addedCount = 0
    for (const folderId of batchAddFolderIds.value) {
      const result = await addFolderMangas(folderId, ids)
      addedCount += result.added.length
    }
    toast.success(
      addedCount > 0
        ? `已将 ${addedCount} 个漫画加入文件夹`
        : '选中的漫画已在目标文件夹中',
    )
    batchAddFolderDialog.value = false
  } catch (err) {
    toast.error(errorMessage(err))
  } finally {
    batchAddFolderLoading.value = false
  }
}

/** 文件夹视图内批量移出：操作可逆，与收藏一致不弹确认框。 */
async function batchRemoveFromFolder(): Promise<void> {
  const folderId = Number(filters.folderId)
  if (!Number.isFinite(folderId) || selectedCount.value === 0) return
  try {
    const result = await removeFolderMangas(folderId, [...selected.value])
    toast.success(`已移出 ${result.removed_count} 个漫画`)
    await load()
  } catch (err) {
    toast.error(errorMessage(err))
  }
}

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

/** 从 URL 查询参数恢复筛选条件，保证刷新后视图不丢失；返回排序参数是否需要规范化。 */
function readQuery(): boolean {
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
    : query.collection === 'folder' ? 'folder'
    : query.collection === 'favorites' || query.favorite_only === 'true' ? 'favorites' : 'local'
  filters.favoriteOnly = filters.collection === 'favorites'
  // folder_id 仅在文件夹页签内生效，其他页签携带时忽略
  const rawFolderId = Number.parseInt(
    typeof query.folder_id === 'string' ? query.folder_id : '',
    10,
  )
  filters.folderId =
    filters.collection === 'folder' && Number.isFinite(rawFolderId) && rawFolderId >= 1
      ? String(rawFolderId)
      : ''
  filters.status = typeof query.status === 'string' ? query.status : ''
  // 手拼链接可能同时带上收藏分组与「已下载未收藏」，两者互斥：
  // 状态回落为全部并标记规范化，不向后端透传互斥组合。
  const statusNeedsNormalize =
    filters.favoriteOnly && filters.status === 'downloaded_unfavorited'
  if (statusNeedsNormalize) {
    filters.status = ''
  }
  const sortNeedsNormalize = readSortQuery(query)
  const page = Number.parseInt(typeof query.page === 'string' ? query.page : '1', 10)
  filters.page = Number.isFinite(page) && page > 0 ? page : 1
  const size = Number.parseInt(
    typeof query.page_size === 'string' ? query.page_size : '20',
    10,
  )
  filters.pageSize = pageSizeOptions.includes(size) ? size : 20
  return sortNeedsNormalize || statusNeedsNormalize
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
  // 文件夹网格视图不加载漫画列表
  if (folderGridView.value) {
    await loadFolders(options)
    return
  }
  if (!silent) loading.value = true
  error.value = ''
  try {
    // 进入具体文件夹时顺带拉取文件夹清单，用于横幅名称与批量加入弹窗；失败不阻塞列表
    if (insideFolder.value) void loadFolders({ silent: true })
    const result = await listMangas({
      page: filters.page,
      page_size: filters.pageSize,
      search: filters.scope === 'tag' ? undefined : filters.keyword || undefined,
      status: filters.status || undefined,
      tag: filters.scope === 'tag' ? filters.keyword || undefined : undefined,
      sort: filters.sort,
      order: filters.order,
      favorite_only: filters.favoriteOnly || undefined,
      history_only: filters.collection === 'history' || undefined,
      blacklist_only: filters.collection === 'blacklist_only' || undefined,
      folder_id: insideFolder.value ? Number(filters.folderId) : undefined,
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
  collection: 'local' | 'favorites' | 'history' | 'blacklist_only' | 'folder',
): void {
  updateQuery({
    collection: collection === 'local' ? undefined : collection,
    favorite_only: undefined,
    folder_id: undefined,
    sort: defaultSortField(collection),
    order: 'desc',
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
  if (ids.length === 0) {
    toast.error('请输入至少一个漫画 ID')
    return
  }
  if (ids.length > 100) {
    toast.error('单次最多请求 100 个漫画')
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
    toast.success(parts.join('，'))
    selected.value = []
  } catch (err) {
    toast.error(errorMessage(err))
  }
}

async function copySelectedIds(): Promise<void> {
  if (selectedCount.value === 0) return
  const ids = [...new Set(selected.value)].join(',')
  const ok = await copyText(ids)
  if (ok) toast.success(`已复制 ${selectedCount.value} 个漫画 ID`)
  else toast.error('复制失败，请手动选择并复制')
}

/** 服务端确认成功后更新状态，失败时保留原收藏状态。 */
async function toggleFavorite(manga: Manga): Promise<void> {
  if (favoriteBusy[manga.id]) return
  favoriteBusy[manga.id] = true
  try {
    const result = await setFavorite(manga.id, !manga.is_favorite)
    manga.is_favorite = result.is_favorite
    toast.success(result.is_favorite ? `已收藏《${manga.title}》` : `已取消收藏《${manga.title}》`)
    if (filters.favoriteOnly && !result.is_favorite) {
      if (mangas.value.length === 1 && filters.page > 1) updateQuery({ page: filters.page - 1 })
      else await load()
    }
  } catch (err) {
    toast.error(errorMessage(err))
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
  try {
    const result = blacklistMode.value === 'add'
      ? await blacklistManga(target.id)
      : await unblacklistManga(target.id)
    if (result.changed) {
      toast.success(blacklistMode.value === 'add'
        ? `已将《${target.title}》加入黑名单`
        : `已将《${target.title}》移出黑名单`)
    } else {
      toast.success(blacklistMode.value === 'add'
        ? `《${target.title}》已在黑名单中`
        : `《${target.title}》不在黑名单中`)
    }
    blacklistDialog.value = false
    await load()
  } catch (err) {
    toast.error(errorMessage(err))
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
    toast.error('选中的漫画中没有已拉黑项')
    batchBlacklistDialog.value = false
    return
  }
  if (ids.length > 100) {
    toast.error('单次最多操作 100 个漫画')
    batchBlacklistDialog.value = false
    return
  }
  batchBlacklistLoading.value = true
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
    toast.success(notice)
    batchBlacklistDialog.value = false
    await load()
  } catch (err) {
    toast.error(errorMessage(err))
    batchBlacklistDialog.value = false
  } finally {
    batchBlacklistLoading.value = false
  }
}

async function confirmDelete(): Promise<void> {
  const target = deleteTarget.value
  if (!target) return
  deleteLoading.value = true
  try {
    const result = await deleteManga(target.id)
    toast.success(`已删除《${target.title}》及 ${result.deleted_file_count} 个文件`)
    deleteDialog.value = false
    await load()
  } catch (err) {
    toast.error(errorMessage(err))
    deleteDialog.value = false
  } finally {
    deleteLoading.value = false
  }
}

async function confirmBatchDelete(): Promise<void> {
  if (selectedCount.value === 0) return
  if (selectedCount.value > 100) {
    toast.error('单次最多删除 100 个漫画')
    batchDeleteDialog.value = false
    return
  }
  batchDeleteLoading.value = true
  try {
    const result = await batchDeleteMangas(selected.value)
    if (result.failed_count > 0) {
      const failed = result.items
        .filter((item) => !item.succeeded)
        .map((item) => `${item.manga_id}（${item.error_message ?? item.error_code ?? '未知错误'}）`)
        .join('、')
      toast.error(`批量删除完成：成功 ${result.succeeded_count} 个，失败 ${result.failed_count} 个：${failed}`)
    } else {
      toast.success(`已删除 ${result.succeeded_count} 个漫画`)
    }
    batchDeleteDialog.value = false
    await load()
  } catch (err) {
    toast.error(errorMessage(err))
    batchDeleteDialog.value = false
  } finally {
    batchDeleteLoading.value = false
  }
}

watch(
  () => route.query,
  () => {
    if (readQuery()) {
      // 旧格式排序或互斥状态参数：先规范化 URL（不向后端透传非法值），下一轮再正常加载
      updateQuery({
        sort: filters.sort,
        order: filters.order,
        status: filters.status || undefined,
      })
      return
    }
    if (!folderGridView.value && libraryListCache.key !== '' && libraryListCache.key === queryKey()) {
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

    <v-card class="mb-4">
      <v-card-text v-if="!folderGridView" class="pb-2">
        <v-row dense>
          <v-col cols="12" md="3">
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
              :items="statusItems"
              label="状态"
              hide-details
              @update:model-value="updateQuery({ status: filters.status || undefined, page: 1 })"
            />
          </v-col>
          <v-col cols="12" md="3" class="d-flex align-center ga-2">
            <v-select
              v-model="filters.sort"
              :items="sortOptions"
              label="排序"
              hide-details
              class="flex-grow-1"
              style="min-width: 0"
              @update:model-value="updateQuery({ sort: filters.sort, order: filters.order, page: 1 })"
            />
            <v-switch
              v-model="orderDesc"
              label="倒序"
              color="primary"
              density="compact"
              hide-details
              class="flex-shrink-0"
              @update:model-value="applyOrderChange"
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
        @update:model-value="switchCollection($event as 'local' | 'favorites' | 'history' | 'blacklist_only' | 'folder')"
      >
        <v-tab value="local" prepend-icon="mdi-folder-outline">本地</v-tab>
        <v-tab value="favorites" prepend-icon="mdi-star-outline">收藏</v-tab>
        <v-tab value="history" prepend-icon="mdi-history">历史</v-tab>
        <v-tab value="blacklist_only" prepend-icon="mdi-lock">黑名单</v-tab>
        <v-tab value="folder" prepend-icon="mdi-folder-multiple-outline">文件夹</v-tab>
      </v-tabs>
      <v-card-actions v-if="!folderGridView" class="flex-wrap">
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
        <div class="action-scroll" :class="{ 'action-scroll--mobile': mobile }">
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
            prepend-icon="mdi-folder-plus-outline"
            :disabled="selectedCount === 0"
            @click="openBatchAddFolder"
          >
            加入文件夹
          </v-btn>
          <v-btn
            v-if="insideFolder"
            variant="tonal"
            color="warning"
            prepend-icon="mdi-folder-remove-outline"
            :disabled="selectedCount === 0"
            @click="batchRemoveFromFolder"
          >
            移出文件夹
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

    <v-card v-if="folderGridView">
      <v-progress-linear v-if="foldersLoading" indeterminate />
      <v-card-title class="d-flex align-center">
        文件夹
        <v-spacer />
        <v-btn
          color="primary"
          size="small"
          prepend-icon="mdi-plus"
          class="mr-2"
          @click="openCreateFolder"
        >
          新建文件夹
        </v-btn>
        <v-btn icon="mdi-refresh" variant="text" size="small" aria-label="刷新" @click="loadFolders({})" />
      </v-card-title>
      <v-divider />
      <EmptyState
        v-if="!foldersLoading && folders.length === 0"
        icon="mdi-folder-plus-outline"
        title="还没有文件夹"
        description="新建文件夹后，可在漫画列表勾选批量加入，或在详情页把漫画加入分组。"
      />
      <v-card-text v-else>
        <v-row dense>
          <v-col
            v-for="folder in folders"
            :key="folder.id"
            cols="12"
            sm="6"
            md="4"
            lg="3"
          >
            <v-card variant="outlined" class="pa-3">
              <v-card-title class="text-wrap pa-0">
                <v-btn
                  variant="text"
                  color="primary"
                  class="text-none pa-2"
                  prepend-icon="mdi-folder-outline"
                  :aria-label="`打开文件夹 ${folder.name}`"
                  @click="openFolder(folder)"
                >
                  {{ folder.name }}
                </v-btn>
              </v-card-title>
              <v-card-subtitle class="pa-0 text-body-2 mt-1">
                共 {{ folder.manga_count }} 本 · 更新于
                {{ formatDateTime(folder.updated_at) }}
              </v-card-subtitle>
              <div class="d-flex justify-end mt-2">
                <v-btn
                  size="small"
                  variant="text"
                  prepend-icon="mdi-pencil-outline"
                  aria-label="重命名文件夹"
                  @click="openRenameFolder(folder)"
                >
                  重命名
                </v-btn>
                <v-btn
                  size="small"
                  variant="text"
                  color="error"
                  prepend-icon="mdi-delete-outline"
                  aria-label="删除文件夹"
                  @click="askDeleteFolder(folder)"
                >
                  删除
                </v-btn>
              </div>
            </v-card>
          </v-col>
        </v-row>
      </v-card-text>
    </v-card>

    <v-card v-else>
      <v-progress-linear v-if="loading" indeterminate />

      <v-sheet v-if="insideFolder" class="pa-3 d-flex align-center ga-2" color="surface-variant">
        <v-icon icon="mdi-folder-open-outline" color="primary" />
        <span class="text-body-1">
          {{ currentFolder ? `文件夹「${currentFolder.name}」` : `文件夹 #${filters.folderId}` }}
        </span>
        <v-spacer />
        <v-btn size="small" variant="text" prepend-icon="mdi-arrow-left" @click="exitFolder">
          返回文件夹列表
        </v-btn>
      </v-sheet>

      <EmptyState
        v-if="!loading && mangas.length === 0"
        icon="mdi-bookshelf"
        :title="insideFolder ? '这个文件夹还没有漫画' : '没有找到漫画'"
        :description="insideFolder
          ? '返回漫画列表勾选漫画后，使用「加入文件夹」放入分组。'
          : '调整筛选条件，或前往漫画下载页请求下载新漫画。'"
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
              <th class="text-no-wrap">下载/入库时间</th>
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
                  v-else-if="manga.status === 'favorited'"
                  size="small"
                  variant="text"
                  prepend-icon="mdi-download"
                  aria-label="下载漫画"
                  @click="requestDownloadIds([manga.id])"
                >
                  下载
                </v-btn>
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
                  v-else-if="manga.status === 'favorited'"
                  size="small"
                  variant="text"
                  prepend-icon="mdi-download"
                  aria-label="下载漫画"
                  @click="requestDownloadIds([manga.id])"
                >
                  下载
                </v-btn>
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

    <v-dialog v-model="folderFormDialog" max-width="440">
      <v-card>
        <v-card-title>{{ folderRenamingId === null ? '新建文件夹' : '重命名文件夹' }}</v-card-title>
        <v-card-text>
          <v-text-field
            v-model="folderNameInput"
            label="文件夹名称"
            :counter="64"
            @keyup.enter="confirmFolderForm"
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="folderFormDialog = false">取消</v-btn>
          <v-btn color="primary" :loading="folderFormLoading" @click="confirmFolderForm">
            保存
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <ConfirmDialog
      v-model="folderDeleteDialog"
      :title="`删除文件夹「${folderDeleteTarget?.name ?? ''}」？`"
      text="只删除分组关系，夹内漫画不会被删除，漫画库仍可找到它们。"
      confirm-text="确认删除"
      :loading="folderDeleteLoading"
      @confirm="confirmDeleteFolder"
    />

    <ConfirmDialog
      v-model="batchAddFolderDialog"
      :title="`把 ${selectedCount} 个漫画加入文件夹`"
      confirm-text="确认加入"
      :loading="batchAddFolderLoading"
      @confirm="confirmBatchAddFolder"
    >
      <div v-if="folders.length === 0" class="text-body-2">
        还没有文件夹，请先切换到「文件夹」页签新建。
      </div>
      <div v-else class="d-flex flex-column" style="max-height: 260px; overflow-y: auto">
        <v-checkbox
          v-for="folder in folders"
          :key="folder.id"
          v-model="batchAddFolderIds"
          :value="folder.id"
          :label="folder.name"
          density="compact"
          hide-details
        />
      </div>
    </ConfirmDialog>
  </div>
</template>
