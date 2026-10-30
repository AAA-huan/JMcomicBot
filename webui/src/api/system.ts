/** 系统状态与控制接口。 */

import { apiRequest } from './client'
import type { SystemStatus } from '@/types/api'

export function getSystemStatus(): Promise<SystemStatus> {
  return apiRequest<SystemStatus>('/system/status')
}

export function reconnectNapcat(): Promise<{ accepted: boolean }> {
  return apiRequest('/system/napcat/reconnect', { method: 'POST' })
}

export function requestShutdown(): Promise<{ shutdown: boolean }> {
  return apiRequest('/system/shutdown', { method: 'POST' })
}

export function requestRestart(): Promise<{ restart: boolean }> {
  return apiRequest('/system/restart', { method: 'POST' })
}

export interface RecoveryStatus {
  pending: boolean
  task_count: number
  remaining_seconds: number
  decision: 'continue' | 'cancel' | null
}

/** 查询启动恢复询问状态，未启用或已结束时 pending 为 false。 */
export function getRecoveryStatus(): Promise<RecoveryStatus> {
  return apiRequest<RecoveryStatus>('/system/recovery')
}

/** 提交恢复决定；终端与 WebUI 任一渠道先到先得。 */
export function resolveRecovery(
  action: 'continue' | 'cancel',
): Promise<{ resolved: boolean }> {
  return apiRequest('/system/recovery', {
    method: 'POST',
    body: { action },
  })
}
