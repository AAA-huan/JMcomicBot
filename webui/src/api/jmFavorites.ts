/** JM 账号临时登录与持久化收藏导入。 */
import { apiRequest } from './client'
import type { DownloadRequestResult, PageResult } from '@/types/api'

export interface JmAccount {
  connected: boolean
  username?: string
  expires_at?: string
  total?: number
  folders?: { id: string; name: string }[]
}

export interface JmImport {
  id: string
  username: string
  folder_ids: string[]
  status: 'running' | 'succeeded' | 'failed' | 'interrupted'
  pages_done: number
  imported_count: number
  duplicate_count: number
  local_count: number
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface JmFavorite {
  manga_id: string
  title: string
  username: string
  folders: Record<string, string>
  downloaded: boolean
  file_id: number | null
  imported_at: string
}

export const getJmAccount = (): Promise<JmAccount> => apiRequest('/jm-favorites/account')
export const loginJmAccount = (username: string, password: string): Promise<JmAccount> =>
  apiRequest('/jm-favorites/account/login', { method: 'POST', body: { username, password } })
export const logoutJmAccount = (): Promise<JmAccount> =>
  apiRequest('/jm-favorites/account/logout', { method: 'POST' })
export const startJmImport = (folderIds: string[]): Promise<JmImport> =>
  apiRequest('/jm-favorites/imports', { method: 'POST', body: { folder_ids: folderIds } })
export const listJmImports = (): Promise<{ items: JmImport[] }> => apiRequest('/jm-favorites/imports')
export const getJmImport = (id: string): Promise<JmImport> => apiRequest(`/jm-favorites/imports/${encodeURIComponent(id)}`)
export const requestJmDownloads = (mangaIds: string[]): Promise<DownloadRequestResult> =>
  apiRequest('/jm-favorites/downloads', { method: 'POST', body: { manga_ids: mangaIds } })
export const listJmFavorites = (query: {
  page: number; page_size: number; search: string; download_status: string
}): Promise<PageResult<JmFavorite>> => apiRequest('/jm-favorites', { query })
