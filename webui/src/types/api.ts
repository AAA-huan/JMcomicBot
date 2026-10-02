/** 后端 API 的 TypeScript 类型定义，与 FastAPI 返回结构保持一致。 */

export interface PageResult<T> {
  items: T[]
  page: number
  page_size: number
  total: number
  pages: number
}

export interface MangaFile {
  id: number
  display_name: string
  file_size_bytes: number
  page_count: number
  status: string
}

export interface Manga {
  id: string
  title: string
  author: string
  description: string | null
  chapter_count: number
  page_count: number
  status: string
  downloaded_at: string
  updated_at: string
  tags: string[]
  files: MangaFile[]
}

export interface OperationTask {
  id: string
  task_type: string
  source: string
  status: string
  stage: string
  progress: number | null
  manga_id: string | null
  summary: string
  error_code: string | null
  error_message: string | null
  created_at: string
  started_at: string | null
  updated_at: string
  finished_at: string | null
}

export interface QueueStatus {
  running: boolean
  queue_size: number
  pending_count?: number
  current_file?: string | null
  current_manga_id?: string | null
}

export interface SystemStatus {
  version: string
  uptime_seconds: number
  napcat_connected: boolean
  manga_count: number
  download_queue: QueueStatus
  send_queue: QueueStatus
}

export interface AuthStatus {
  initialized: boolean
  authenticated: boolean
}

export interface AdminInfo {
  id: number
  created_at: string
  updated_at: string
  last_login_at: string | null
  session_expires_at: string
}

export interface CachedUser {
  id: string
  nickname: string
  last_seen_at: string
}

export interface CachedGroup {
  id: string
  group_name: string
  last_seen_at: string
}

export interface PermissionData {
  scopes: Record<string, string[]>
  cached_users: CachedUser[]
  cached_groups: CachedGroup[]
}

export type SettingValue = string | number | boolean | null

export interface SettingView {
  key: string
  title: string
  value_type: string
  group: string
  editable: boolean
  sensitive: boolean
  effect: string
  apply_target: string
  value: SettingValue
  is_set: boolean
}

export interface BackupRecord {
  id: number
  filename: string
  file_size_bytes: number
  sha256: string | null
  schema_version: string
  status: string
  created_at: string
  updated_at: string
  deleted_at: string | null
}

export interface DownloadRequestItem {
  manga_id: string
  status: 'queued' | 'duplicate'
  task_id: string | null
}

export interface DownloadRequestResult {
  items: DownloadRequestItem[]
  queued_count: number
  duplicate_count: number
}

export interface ReadingProgress {
  file_id: number
  page_number: number
  page_count: number
  percent: number
  updated_at: string | null
}

export interface ScanResultView {
  task_id: string | null
  scanned_files: number
  manga_count: number
  new_count: number
  updated_count: number
  marked_missing_count: number
}

export interface EventEnvelope<T = unknown> {
  type: string
  occurred_at: string
  data: T
}
