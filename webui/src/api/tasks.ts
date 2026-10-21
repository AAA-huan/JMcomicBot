/** 下载任务查询、创建与取消接口。 */

import { apiRequest } from './client'
import type {
  DownloadProgressSnapshot,
  DownloadRequestResult,
  OperationTask,
  PageResult,
} from '@/types/api'

export interface TaskListQuery {
  page?: number
  page_size?: number
  task_type?: string
  status?: string
  manga_id?: string
}

export function listTasks(query: TaskListQuery = {}): Promise<PageResult<OperationTask>> {
  return apiRequest<PageResult<OperationTask>>('/tasks', { query: { ...query } })
}

export function getTask(taskId: string): Promise<OperationTask> {
  return apiRequest<OperationTask>(`/tasks/${encodeURIComponent(taskId)}`)
}

export function requestDownloads(mangaIds: string[]): Promise<DownloadRequestResult> {
  return apiRequest<DownloadRequestResult>('/tasks/downloads', {
    method: 'POST',
    body: { manga_ids: mangaIds },
  })
}

export function getDownloadProgress(): Promise<{
  active: DownloadProgressSnapshot | null
}> {
  return apiRequest<{ active: DownloadProgressSnapshot | null }>('/downloads/progress')
}

export function cancelTask(taskId: string): Promise<{ cancelled: boolean }> {
  return apiRequest(`/tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' })
}

export function cancelQueuedTasks(): Promise<{ cancelled_count: number }> {
  return apiRequest('/tasks/cancel-queued', { method: 'POST' })
}

export interface BatchTaskItem {
  task_id: string
  status: string
  manga_id?: string | null
}

export interface BatchTaskResult {
  items: BatchTaskItem[]
  cancelled_count?: number
  requeued_count?: number
  failed_count: number
}

export function cancelTasks(taskIds: string[]): Promise<BatchTaskResult> {
  return apiRequest<BatchTaskResult>('/tasks/cancel', {
    method: 'POST',
    body: { task_ids: taskIds },
  })
}

export function retryTasks(taskIds: string[]): Promise<BatchTaskResult> {
  return apiRequest<BatchTaskResult>('/tasks/retry', {
    method: 'POST',
    body: { task_ids: taskIds },
  })
}
