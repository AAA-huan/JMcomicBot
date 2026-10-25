/** JM 远程作者搜索与漫画概要接口。 */

import { apiRequest } from './client'

export interface JmSearchAlbum {
  album_id: string
  title: string
  author: string
  tags: string[]
}

export interface JmAuthorSearchResult {
  results: JmSearchAlbum[]
  page: number
  page_count: number
  page_size: number
  total: number
}

export interface JmAlbumDetail {
  album_id: string
  title: string
  author: string
  tags: string[]
  page_count: number
  chapter_ids: string[]
}

/** 按作者搜索 JM 漫画，页码从 1 开始。 */
export function searchAuthorByAuthor(
  author: string,
  page = 1,
): Promise<JmAuthorSearchResult> {
  return apiRequest<JmAuthorSearchResult>('/jm/search/author', {
    query: { author, page },
  })
}

/** 读取远程漫画概要，不下载也不写入本地漫画库。 */
export function getJmAlbumDetail(albumId: string): Promise<JmAlbumDetail> {
  return apiRequest<JmAlbumDetail>(`/jm/album/${encodeURIComponent(albumId)}`)
}
