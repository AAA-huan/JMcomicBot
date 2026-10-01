/** 认证与管理员接口。 */

import { apiRequest } from './client'
import type { AdminInfo, AuthStatus } from '@/types/api'

export function getAuthStatus(): Promise<AuthStatus> {
  return apiRequest<AuthStatus>('/auth/status')
}

export function setup(password: string): Promise<{ initialized: boolean }> {
  return apiRequest('/auth/setup', { method: 'POST', body: { password } })
}

export function login(password: string): Promise<{ authenticated: boolean }> {
  return apiRequest('/auth/login', { method: 'POST', body: { password } })
}

export function logout(): Promise<{ authenticated: boolean }> {
  return apiRequest('/auth/logout', { method: 'POST' })
}

export function getMe(): Promise<AdminInfo> {
  return apiRequest<AdminInfo>('/auth/me')
}

export function changePassword(
  oldPassword: string,
  newPassword: string,
): Promise<{ authenticated: boolean }> {
  return apiRequest('/auth/password', {
    method: 'PUT',
    body: { old_password: oldPassword, new_password: newPassword },
  })
}
