import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import * as authApi from '@/api/auth'
import type { AdminInfo, AuthStatus } from '@/types/api'

/** 认证状态：跨页面共享的初始化/登录信息。 */
export const useAuthStore = defineStore('auth', () => {
  const initialized = ref(false)
  const authenticated = ref(false)
  const admin = ref<AdminInfo | null>(null)
  const loaded = ref(false)

  const isReady = computed(() => loaded.value)

  async function refresh(): Promise<AuthStatus> {
    const status = await authApi.getAuthStatus()
    initialized.value = status.initialized
    authenticated.value = status.authenticated
    loaded.value = true
    admin.value = status.authenticated ? await authApi.getMe() : null
    return status
  }

  async function setup(password: string): Promise<void> {
    await authApi.setup(password)
    initialized.value = true
  }

  async function login(password: string): Promise<void> {
    await authApi.login(password)
    await refresh()
  }

  async function logout(): Promise<void> {
    await authApi.logout()
    clearSession()
  }

  function clearSession(): void {
    authenticated.value = false
    admin.value = null
  }

  return {
    initialized,
    authenticated,
    admin,
    loaded,
    isReady,
    refresh,
    setup,
    login,
    logout,
    clearSession,
  }
})
