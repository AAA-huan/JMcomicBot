import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it, vi } from 'vitest'
import { createVuetify } from 'vuetify'

vi.mock('@/api/auth', () => ({
  getAuthStatus: vi.fn(),
  getMe: vi.fn(),
  setup: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  changePassword: vi.fn(),
}))

import LoginPage from '@/pages/LoginPage.vue'

describe('LoginPage', () => {
  it('渲染密码表单与登录按钮', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: { template: '<div />' } },
        { path: '/login', component: LoginPage },
      ],
    })
    await router.push('/login')
    await router.isReady()

    const wrapper = mount(LoginPage, {
      global: {
        plugins: [createPinia(), router, createVuetify()],
      },
    })

    expect(wrapper.text()).toContain('登录')
    expect(wrapper.find('input[type="password"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('登录')
  })
})
