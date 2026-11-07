/** 本地自定义漫画文件夹接口。 */

import { apiRequest } from './client'
import type { Folder } from '@/types/api'

export interface FolderMembersResult {
  folder_id: number
  added: string[]
  unchanged_count: number
}

export interface FolderRemoveResult {
  folder_id: number
  removed_count: number
}

export function listFolders(): Promise<Folder[]> {
  return apiRequest<Folder[]>('/folders')
}

export function createFolder(name: string): Promise<Folder> {
  return apiRequest<Folder>('/folders', { method: 'POST', body: { name } })
}

export function renameFolder(folderId: number, name: string): Promise<Folder> {
  return apiRequest<Folder>(`/folders/${folderId}`, { method: 'PATCH', body: { name } })
}

export function deleteFolder(folderId: number): Promise<{ folder_id: number; deleted: boolean }> {
  return apiRequest(`/folders/${folderId}`, { method: 'DELETE' })
}

export function addFolderMangas(folderId: number, mangaIds: string[]): Promise<FolderMembersResult> {
  return apiRequest<FolderMembersResult>(`/folders/${folderId}/mangas`, {
    method: 'POST',
    body: { manga_ids: mangaIds },
  })
}

export function removeFolderMangas(
  folderId: number,
  mangaIds: string[],
): Promise<FolderRemoveResult> {
  return apiRequest<FolderRemoveResult>(`/folders/${folderId}/mangas`, {
    method: 'DELETE',
    body: { manga_ids: mangaIds },
  })
}
