import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import { createVuetify } from 'vuetify'
vi.mock('@/api/settings', () => ({ listSettings: vi.fn(), updateSetting: vi.fn() }))
import { listSettings, updateSetting } from '@/api/settings'
import SettingsPage from '@/pages/SettingsPage.vue'
import type { SettingView } from '@/types/api'

it('敏感启动项可编辑且不回显，保存后显示待重启', async () => {
  vi.stubGlobal('visualViewport', undefined)
  const token: SettingView = {
    key: 'NAPCAT_TOKEN', title: 'NapCat 访问令牌', value_type: 'str', group: 'NapCat',
    editable: true, sensitive: true, effect: 'restart', apply_target: '重启机器人',
    value: null, is_set: true,
  }
  vi.mocked(listSettings).mockResolvedValueOnce({ items: [token] })
  vi.mocked(listSettings).mockResolvedValue({ items: [{ ...token, restart_required: true }] })
  vi.mocked(updateSetting).mockResolvedValue({ ...token, restart_required: true })
  const wrapper = mount(SettingsPage, { attachTo: document.body, global: { plugins: [createVuetify()] } })
  await flushPromises()
  await wrapper.find('[aria-label="修改NapCat 访问令牌"]').trigger('click')
  await flushPromises()
  const input = document.querySelector<HTMLInputElement>('input[type="password"]')!
  expect(input.value).toBe('')
  input.value = 'new-secret'
  input.dispatchEvent(new Event('input', { bubbles: true }))
  await flushPromises()
  const save = [...document.querySelectorAll('button')].find(button => button.textContent?.trim() === '保存')!
  save.click()
  await flushPromises()
  expect(updateSetting).toHaveBeenCalledWith('NAPCAT_TOKEN', 'new-secret')
  expect(wrapper.text()).toContain('待重启')
  expect(wrapper.text()).not.toContain('new-secret')
  wrapper.unmount()
  vi.unstubAllGlobals()
})
