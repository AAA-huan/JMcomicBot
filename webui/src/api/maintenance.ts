/** 维护操作接口：扫描、修复、备份与数据迁移。 */

import { apiDownload, apiRequest, apiUpload } from './client'
import type { DownloadedFile } from './client'
import type { BackupRecord, PageResult, ScanResultView, VerifyResult } from '@/types/api'

export interface ScanOptions {
  dry_run: boolean
  enrich: boolean
  read_pages: boolean
  check_chapters: boolean
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

export interface ImportPreview {
  format_version: number
  schema_revision: string
  exported_at: string
  db_filename: string
  db_sha256: string
  table_counts: Record<string, number>
  export_env: Record<string, string>
  current_schema_revision: string
  path_warnings: string[]
}

export function exportData(): Promise<DownloadedFile> {
  return apiDownload('/maintenance/data-export', 'POST')
}

export function validateDataImport(file: File): Promise<ImportPreview> {
  const formData = new FormData()
  formData.append('file', file, file.name)
  return apiUpload<ImportPreview>('/maintenance/data-import/validate', formData)
}

export function applyDataImport(file: File): Promise<{ restart: boolean }> {
  const formData = new FormData()
  formData.append('file', file, file.name)
  return apiUpload<{ restart: boolean }>(
    '/maintenance/data-import?confirm=1',
    formData,
  )
}
