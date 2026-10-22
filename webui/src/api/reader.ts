/** 阅读器偏好设置接口。 */

import { apiRequest } from './client'
import type { ReadingSettingUpdate, ReadingSettings } from '@/reader/types'

export function getReaderSettings(): Promise<ReadingSettings> {
  return apiRequest<ReadingSettings>('/reader/settings')
}

export function updateReaderSettings(
  payload: ReadingSettingUpdate,
): Promise<ReadingSettings> {
  return apiRequest<ReadingSettings>('/reader/settings', {
    method: 'PUT',
    body: payload,
  })
}
