/** 权限名单接口。 */

import { apiRequest } from './client'
import type { PermissionData } from '@/types/api'

export function getPermissions(): Promise<PermissionData> {
  return apiRequest<PermissionData>('/permissions')
}

export function addPermission(
  scope: string,
  value: string,
): Promise<{ scope: string; value: string; changed: boolean }> {
  return apiRequest(`/permissions/${encodeURIComponent(scope)}`, {
    method: 'POST',
    body: { value },
  })
}

export function removePermission(
  scope: string,
  value: string,
): Promise<{ scope: string; value: string; changed: boolean }> {
  return apiRequest(
    `/permissions/${encodeURIComponent(scope)}/${encodeURIComponent(value)}`,
    { method: 'DELETE' },
  )
}
