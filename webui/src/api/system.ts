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
