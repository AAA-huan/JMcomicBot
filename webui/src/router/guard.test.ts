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

import { getAuthStatus, getMe } from '@/api/auth'
import router from '@/router'

const adminFixture = {
  id: 1,
  created_at: '2026-10-01T00:00:00',
  updated_at: '2026-10-01T00:00:00',
  last_login_at: null,
  session_expires_at: '2026-10-02T00:00:00',
}

describe('router guard', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('已初始化但未登录时允许停留在登录页（不得重定向循环）', async () => {
    vi.mocked(getAuthStatus).mockResolvedValue({
      initialized: true,
      authenticated: false,
    })

    await router.push('/login')

    expect(router.currentRoute.value.name).toBe('login')
  })

  it('已初始化但未登录时受保护页面跳转登录页并携带回跳地址', async () => {
    vi.mocked(getAuthStatus).mockResolvedValue({
      initialized: true,
      authenticated: false,
    })

    await router.push('/library')

    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBe('/library')
  })

  it('未初始化时任何页面都跳转首次设置', async () => {
    vi.mocked(getAuthStatus).mockResolvedValue({
      initialized: false,
      authenticated: false,
    })

    await router.push('/tasks')

    expect(router.currentRoute.value.name).toBe('setup')
  })

  it('已登录时访问登录页跳转仪表盘', async () => {
    vi.mocked(getAuthStatus).mockResolvedValue({
      initialized: true,
      authenticated: true,
    })
    vi.mocked(getMe).mockResolvedValue(adminFixture)

    await router.push('/login')

    expect(router.currentRoute.value.name).toBe('dashboard')
  })
})
