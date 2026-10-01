/** 维护操作接口：扫描、修复与备份。 */

import { apiRequest } from './client'
import type { BackupRecord, PageResult, ScanResultView } from '@/types/api'

export function scanLibrary(): Promise<ScanResultView> {
  return apiRequest<ScanResultView>('/maintenance/scan', { method: 'POST' })
}

export function repairLibrary(): Promise<{ cleaned_count: number }> {
  return apiRequest('/maintenance/repair', { method: 'POST' })
}

export interface BackupListQuery {
  page?: number
  page_size?: number
  status?: string
}

export function listBackups(
  query: BackupListQuery = {},
): Promise<PageResult<BackupRecord>> {
  return apiRequest<PageResult<BackupRecord>>('/maintenance/backups', {
    query: { ...query },
  })
}

export interface CreatedBackup {
  task_id: string
  backup_id: number
  filename: string
  file_size_bytes: number
}

export function createBackup(): Promise<CreatedBackup> {
  return apiRequest<CreatedBackup>('/maintenance/backups', { method: 'POST' })
}
