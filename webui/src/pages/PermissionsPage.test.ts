import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { createVuetify } from 'vuetify'

vi.mock('@/api/permissions', () => ({
  getPermissions: vi.fn(), addPermission: vi.fn(), removePermission: vi.fn(),
  getAdminQQ: vi.fn(), linkAdminQQ: vi.fn(), unlinkAdminQQ: vi.fn(),
}))
import { ApiError } from '@/api/client'
import { getPermissions, getAdminQQ, linkAdminQQ, unlinkAdminQQ } from '@/api/permissions'
import PermissionsPage from '@/pages/PermissionsPage.vue'

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getPermissions).mockResolvedValue({ scopes: {}, cached_users: [], cached_groups: [] })
  vi.mocked(getAdminQQ).mockResolvedValue({ qq_id: null })
})

async function mountPage() {
  const wrapper = mount(PermissionsPage, { global: { plugins: [createVuetify()] } })
  await flushPromises()
  return wrapper
}

it('输入非法时不发请求，关联后显示 QQ 并可立即解绑', async () => {
  const wrapper = await mountPage()
  await wrapper.findAll('input')[0]!.setValue('00123')
  await wrapper.findAll('button').find(button => button.text() === '关联 QQ')!.trigger('click')
  expect(linkAdminQQ).not.toHaveBeenCalled()
  expect(wrapper.text()).toContain('不能含前导零')
  vi.mocked(linkAdminQQ).mockResolvedValue({ qq_id: '12345', changed: true })
  await wrapper.findAll('input')[0]!.setValue('12345')
  await wrapper.findAll('button').find(button => button.text() === '关联 QQ')!.trigger('click')
  await flushPromises()
  expect(linkAdminQQ).toHaveBeenCalledWith('12345')
  expect(wrapper.text()).toContain('当前关联：12345')
  vi.mocked(unlinkAdminQQ).mockResolvedValue({ qq_id: null, changed: true })
  await wrapper.findAll('button').find(button => button.text() === '解除关联')!.trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('当前关联：未关联')
  wrapper.unmount()
})

it('更换失败展示原因并保留当前关联', async () => {
  vi.mocked(getAdminQQ).mockResolvedValue({ qq_id: '12345' })
  vi.mocked(linkAdminQQ).mockRejectedValue(new ApiError(400, 'INVALID_ADMIN_QQ', '该 QQ 号在全局黑名单中'))
  const wrapper = await mountPage()
  await wrapper.findAll('input')[0]!.setValue('67890')
  await wrapper.findAll('button').find(button => button.text() === '更换关联')!.trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('该 QQ 号在全局黑名单中')
  expect(wrapper.text()).toContain('当前关联：12345')
  wrapper.unmount()
})
