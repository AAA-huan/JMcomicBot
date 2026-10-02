import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/auth', () => ({
  getAuthStatus: vi.fn(),
  getMe: vi.fn(),
  setup: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  changePassword: vi.fn(),
}))

import * as authApi from '@/api/auth'
import { useAuthStore } from '@/stores/auth'

const adminFixture = {
  id: 1,
  created_at: '2026-10-01T00:00:00',
  updated_at: '2026-10-01T00:00:00',
  last_login_at: null,
  session_expires_at: '2026-10-02T00:00:00',
}

describe('auth store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('refresh 更新初始化状态与登录信息', async () => {
    vi.mocked(authApi.getAuthStatus).mockResolvedValue({
      initialized: true,
      authenticated: true,
    })
    vi.mocked(authApi.getMe).mockResolvedValue(adminFixture)
    const store = useAuthStore()

    await store.refresh()

    expect(store.initialized).toBe(true)
    expect(store.authenticated).toBe(true)
    expect(store.loaded).toBe(true)
    expect(store.admin?.id).toBe(1)
  })

  it('未登录时不请求管理员信息', async () => {
    vi.mocked(authApi.getAuthStatus).mockResolvedValue({
      initialized: true,
      authenticated: false,
    })
    const store = useAuthStore()

    await store.refresh()

    expect(store.authenticated).toBe(false)
    expect(store.admin).toBeNull()
    expect(authApi.getMe).not.toHaveBeenCalled()
  })

  it('login 成功后刷新会话，logout 清空会话', async () => {
    vi.mocked(authApi.getAuthStatus).mockResolvedValue({
      initialized: true,
      authenticated: true,
    })
    vi.mocked(authApi.getMe).mockResolvedValue(adminFixture)
    const store = useAuthStore()

    await store.login('password-1234')
    expect(authApi.login).toHaveBeenCalledWith('password-1234')
    expect(store.authenticated).toBe(true)

    await store.logout()
    expect(authApi.logout).toHaveBeenCalled()
    expect(store.authenticated).toBe(false)
    expect(store.admin).toBeNull()
  })
})
