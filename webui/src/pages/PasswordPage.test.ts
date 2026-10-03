import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createVuetify } from 'vuetify'

vi.mock('@/api/auth', () => ({ changePassword: vi.fn() }))

import { changePassword } from '@/api/auth'
import { ApiError } from '@/api/client'
import PasswordPage from '@/pages/PasswordPage.vue'
import { useAuthStore } from '@/stores/auth'

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/password', component: PasswordPage },
      { path: '/login', name: 'login', component: { template: '<div />' } },
    ],
  })
  await router.push('/password')
  const pinia = createPinia()
  const auth = useAuthStore(pinia)
  auth.authenticated = true
  const wrapper = mount(PasswordPage, {
    global: { plugins: [pinia, router, createVuetify()] },
  })
  await wrapper.findAll('input')[0]!.setValue('old-password')
  await wrapper.findAll('input')[1]!.setValue('new-password')
  await wrapper.findAll('input')[2]!.setValue('new-password')
  return { wrapper, router, auth }
}

describe('PasswordPage', () => {
  beforeEach(() => vi.clearAllMocks())

  it('两次新密码不一致时阻止请求', async () => {
    const { wrapper } = await mountPage()
    await wrapper.findAll('input')[2]!.setValue('different-password')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.text()).toContain('两次输入的新密码不一致')
    expect(changePassword).not.toHaveBeenCalled()
  })

  it('旧密码错误时保留登录与表单并展示错误', async () => {
    vi.mocked(changePassword).mockRejectedValue(new ApiError(400, 'PASSWORD_INVALID', '原管理员密码错误'))
    const { wrapper, auth, router } = await mountPage()
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('原管理员密码错误')
    expect(auth.authenticated).toBe(true)
    expect(router.currentRoute.value.path).toBe('/password')
  })

  it('成功后清理会话、清空密码并跳转重新登录', async () => {
    vi.mocked(changePassword).mockResolvedValue({ authenticated: false })
    const { wrapper, auth, router } = await mountPage()
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(changePassword).toHaveBeenCalledWith('old-password', 'new-password')
    expect(auth.authenticated).toBe(false)
    expect(wrapper.findAll('input').every((input) => input.element.value === '')).toBe(true)
    expect(router.currentRoute.value.fullPath).toBe('/login?password_changed=1')
  })
})
