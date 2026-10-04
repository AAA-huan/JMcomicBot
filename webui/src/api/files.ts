/** PDF 文件流与阅读进度接口。 */

import { apiRequest } from './client'
import type { ReadingProgress } from '@/types/api'

/** 在线阅读的 PDF 流地址：同源、inline，由浏览器与 PDF.js 按 Range 拉取。 */
export function fileContentUrl(fileId: number): string {
  return `/api/v1/files/${fileId}/content?disposition=inline`
}

/** PDF 附件下载地址。 */
export function fileDownloadUrl(fileId: number): string {
  return `/api/v1/files/${fileId}/content`
}

export function getReadingProgress(fileId: number): Promise<ReadingProgress> {
  return apiRequest<ReadingProgress>(`/files/${fileId}/progress`)
}

export function updateReadingProgress(
  fileId: number,
  pageNumber: number,
  pageCount: number,
): Promise<ReadingProgress> {
  return apiRequest<ReadingProgress>(`/files/${fileId}/progress`, {
    method: 'PUT',
    body: { page_number: pageNumber, page_count: pageCount },
  })
}

/** 单独同步实际页数，打开首页时也能更新，且不覆盖阅读位置。 */
export function updateFilePageCount(fileId: number, pageCount: number): Promise<void> {
  return apiRequest(`/files/${fileId}/page-count`, {
    method: 'PUT', body: { page_count: pageCount },
  })
}
