/** 运行时配置接口。 */

import { apiRequest } from './client'
import type { SettingValue, SettingView } from '@/types/api'

export function listSettings(): Promise<{ items: SettingView[] }> {
  return apiRequest<{ items: SettingView[] }>('/settings')
}

export function updateSetting(key: string, value: SettingValue): Promise<SettingView> {
  return apiRequest<SettingView>(`/settings/${encodeURIComponent(key)}`, {
    method: 'PATCH',
    body: { value },
  })
}
