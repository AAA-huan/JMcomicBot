/** 只读审计查询，使用服务端分页及精确筛选。 */
import { apiRequest } from './client'
import type { AuditEvent, PageResult } from '@/types/api'

export function listAuditEvents(query: {
  page: number
  page_size: number
  event_type?: string
  source?: string
}): Promise<PageResult<AuditEvent>> {
  return apiRequest('/audit-events', { query })
}
