/** 漫画查询、元数据修改与删除接口。 */

import { apiRequest } from './client'
import type { Manga, MangaFile, PageResult } from '@/types/api'

export interface MangaListQuery {
  favorite_only?: boolean
  page?: number
  page_size?: number
  search?: string
  status?: string
  tag?: string
  sort?: string
}

export function listMangas(query: MangaListQuery = {}): Promise<PageResult<Manga>> {
  return apiRequest<PageResult<Manga>>('/mangas', { query: { ...query } })
}

export function getManga(mangaId: string): Promise<Manga> {
  return apiRequest<Manga>(`/mangas/${encodeURIComponent(mangaId)}`)
}

export function listMangaFiles(mangaId: string): Promise<MangaFile[]> {
  return apiRequest<MangaFile[]>(`/mangas/${encodeURIComponent(mangaId)}/files`)
}

export interface MangaMetadataPatch {
  title?: string
  author?: string
  tags?: string[]
}

export function patchManga(mangaId: string, fields: MangaMetadataPatch): Promise<Manga> {
  return apiRequest<Manga>(`/mangas/${encodeURIComponent(mangaId)}`, {
    method: 'PATCH',
    body: fields,
  })
}

export interface MangaDeleteResult {
  task_id: string
  manga_id: string
  deleted: boolean
  deleted_file_count: number
}

export function deleteManga(mangaId: string): Promise<MangaDeleteResult> {
  return apiRequest(`/mangas/${encodeURIComponent(mangaId)}`, { method: 'DELETE' })
}

export interface BatchDeleteResult {
  task_id: string
  items: {
    manga_id: string
    succeeded: boolean
    error_code: string | null
    error_message?: string | null
    deleted_file_count: number
  }[]
  succeeded_count: number
  failed_count: number
}

export function batchDeleteMangas(mangaIds: string[]): Promise<BatchDeleteResult> {
  return apiRequest<BatchDeleteResult>('/mangas/batch-delete', {
    method: 'POST',
    body: { manga_ids: mangaIds },
  })
}
