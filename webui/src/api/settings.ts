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

export function getOptionFile(): Promise<{ content: string }> {
  return apiRequest<{ content: string }>('/settings/option-file')
}

export function updateOptionFile(content: string): Promise<{ content: string; updated: boolean }> {
  return apiRequest<{ content: string; updated: boolean }>('/settings/option-file', {
    method: 'PUT',
    body: { content },
  })
}
