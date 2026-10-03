/** 维护操作接口：扫描、修复与备份。 */

import { apiRequest } from './client'
import type { BackupRecord, PageResult, ScanResultView, VerifyResult } from '@/types/api'

export interface ScanOptions {
  dry_run: boolean
  enrich: boolean
}

export interface RepairResult {
  cleaned_count: number
  dry_run: boolean
  orphan_manga_ids: string[]
  orphan_tag_names: string[]
}

export function scanLibrary(options: ScanOptions): Promise<ScanResultView> {
  return apiRequest<ScanResultView>('/maintenance/scan', { method: 'POST', body: options })
}

export function repairLibrary(dryRun: boolean): Promise<RepairResult> {
  return apiRequest('/maintenance/repair', { method: 'POST', body: { dry_run: dryRun } })
}

export function verifyLibrary(mangaIds: string[] | null): Promise<VerifyResult> {
  return apiRequest('/maintenance/verify', { method: 'POST', body: { manga_ids: mangaIds } })
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
