import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import { createVuetify } from 'vuetify'

vi.mock('@/api/settings', () => ({
  getOptionFile: vi.fn(),
  listSettings: vi.fn(),
  updateOptionFile: vi.fn(),
  updateSetting: vi.fn(),
}))
import {
  getOptionFile,
  listSettings,
  updateOptionFile,
  updateSetting,
} from '@/api/settings'
import SettingsPage from '@/pages/SettingsPage.vue'
import type { SettingView } from '@/types/api'

function makeTokenView(overrides: Partial<SettingView> = {}): SettingView {
  return {
    key: 'NAPCAT_TOKEN',
    title: 'NapCat 访问令牌',
    value_type: 'str',
    group: 'NapCat',
    editable: true,
    sensitive: true,
    effect: 'restart',
    apply_target: '重启机器人',
    value: 'super-secret-token',
    is_set: true,
    ...overrides,
  }
}

function makeBindingView(overrides: Partial<SettingView> = {}): SettingView {
  return {
    key: 'BLACKLIST_DELETE_BINDING',
    title: '漫画黑名单与删除绑定',
    value_type: 'bool',
    group: '下载与存储',
    editable: true,
    sensitive: false,
    effect: 'restart',
    apply_target: '重启机器人',
    value: false,
    is_set: true,
    restart_required: false,
    ...overrides,
  }
}

/** 查找文本匹配且未禁用的按钮（disabled 按钮不触发 click）。 */
function findEnabledButtonByText(text: string): HTMLButtonElement {
  const buttons = document.querySelectorAll<HTMLButtonElement>('button')
  return [...buttons].find(
    (button) => !button.disabled && button.textContent?.trim() === text,
  )!
}

it('敏感项明文显示与编辑回显，保存后标记待重启', async () => {
  vi.stubGlobal('visualViewport', undefined)
  const token = makeTokenView()
  vi.mocked(listSettings).mockResolvedValueOnce({ items: [token] })
  vi.mocked(listSettings).mockResolvedValue({
    items: [{ ...token, restart_required: true }],
  })
  vi.mocked(updateSetting).mockResolvedValue({
    ...token,
    value: 'new-secret',
    restart_required: true,
  })
  vi.mocked(getOptionFile).mockResolvedValue({ content: '' })
  const wrapper = mount(SettingsPage, {
    attachTo: document.body,
    global: { plugins: [createVuetify()] },
  })
  await flushPromises()

  // 明文显示在列表中
  expect(wrapper.text()).toContain('super-secret-token')

  await wrapper.find('[aria-label="修改NapCat 访问令牌"]').trigger('click')
  await flushPromises()

  // 编辑对话框内的 input，type 为 text（明文），初始回显真实值
  const dialogInput = document.querySelector<HTMLInputElement>(
    '.v-dialog input[type="text"]',
  )!
  expect(dialogInput.value).toBe('super-secret-token')
  dialogInput.value = 'new-secret'
  dialogInput.dispatchEvent(new Event('input', { bubbles: true }))
  await flushPromises()

  findEnabledButtonByText('保存').click()
  await flushPromises()

  expect(updateSetting).toHaveBeenCalledWith('NAPCAT_TOKEN', 'new-secret')
  expect(wrapper.text()).toContain('待重启')
  wrapper.unmount()
  vi.unstubAllGlobals()
})

it('黑名单绑定开关展示说明并可切换为待重启', async () => {
  vi.stubGlobal('visualViewport', undefined)
  const binding = makeBindingView()
  vi.mocked(listSettings).mockResolvedValueOnce({ items: [binding] })
  vi.mocked(listSettings).mockResolvedValue({
    items: [{ ...binding, value: true, restart_required: true }],
  })
  vi.mocked(updateSetting).mockResolvedValue({
    ...binding,
    value: true,
    restart_required: true,
  })
  vi.mocked(getOptionFile).mockResolvedValue({ content: '' })
  const wrapper = mount(SettingsPage, {
    attachTo: document.body,
    global: { plugins: [createVuetify()] },
  })
  await flushPromises()

  expect(wrapper.text()).toContain('漫画黑名单与删除绑定')
  expect(wrapper.text()).toContain('默认关闭')
  expect(wrapper.text()).toContain('删除漫画时同步加入黑名单')
  expect(wrapper.text()).toContain('需重启机器人生效')

  await wrapper
    .find('[aria-label="修改漫画黑名单与删除绑定"]')
    .trigger('click')
  await flushPromises()

  const checkbox = document.querySelector<HTMLInputElement>(
    '.v-dialog input[type="checkbox"]',
  )!
  expect(checkbox.checked).toBe(false)
  checkbox.click()
  await flushPromises()

  findEnabledButtonByText('保存').click()
  await flushPromises()

  expect(updateSetting).toHaveBeenCalledWith('BLACKLIST_DELETE_BINDING', true)
  expect(wrapper.text()).toContain('待重启')
  wrapper.unmount()
  vi.unstubAllGlobals()
})

it('启动项被环境变量覆盖时显示明确提示', async () => {
  vi.stubGlobal('visualViewport', undefined)
  const binding = makeBindingView({ overridden_by_env: true })
  vi.mocked(listSettings).mockResolvedValue({ items: [binding] })
  vi.mocked(getOptionFile).mockResolvedValue({ content: '' })
  const wrapper = mount(SettingsPage, {
    attachTo: document.body,
    global: { plugins: [createVuetify()] },
  })
  await flushPromises()

  expect(wrapper.text()).toContain('检测到同名环境变量')
  expect(wrapper.text()).toContain('通过网页重启会清除该覆盖并以 .env 为准')

  await wrapper
    .find('[aria-label="修改漫画黑名单与删除绑定"]')
    .trigger('click')
  await flushPromises()

  const dialog = document.querySelector('.v-dialog')
  expect(dialog?.textContent).toContain('检测到同名环境变量')

  wrapper.unmount()
  vi.unstubAllGlobals()
})

it('option.yml 编辑器加载内容、保存后提示生效', async () => {
  vi.stubGlobal('visualViewport', undefined)
  const content = 'download:\n  image:\n    suffix: .jpg\n'
  vi.mocked(listSettings).mockResolvedValue({ items: [] })
  vi.mocked(getOptionFile).mockResolvedValueOnce({ content })
  vi.mocked(updateOptionFile).mockResolvedValue({ content, updated: true })
  const wrapper = mount(SettingsPage, {
    attachTo: document.body,
    global: { plugins: [createVuetify()] },
  })
  await flushPromises()

  expect(wrapper.text()).toContain('下载器配置（option.yml）')

  const textarea = wrapper.find('textarea')
  expect(textarea.element.value).toBe(content)

  // 修改后标记脏状态，保存按钮变为可用
  await textarea.setValue('download:\n  image:\n    suffix: .png\n')
  await flushPromises()
  expect(wrapper.text()).toContain('有未保存的改动')

  findEnabledButtonByText('保存').click()
  await flushPromises()

  expect(updateOptionFile).toHaveBeenCalledWith(
    'download:\n  image:\n    suffix: .png\n',
  )
  expect(wrapper.text()).toContain('已保存')
  expect(wrapper.text()).toContain('无需重启')
  wrapper.unmount()
  vi.unstubAllGlobals()
})

it('option.yml 保存失败显示错误信息', async () => {
  vi.stubGlobal('visualViewport', undefined)
  vi.mocked(listSettings).mockResolvedValue({ items: [] })
  vi.mocked(getOptionFile).mockResolvedValue({ content: 'download:\n' })
  // errorMessage 对普通 Error 返回 "网络请求失败：<message>"
  vi.mocked(updateOptionFile).mockRejectedValue(new Error('YAML 解析失败'))
  const wrapper = mount(SettingsPage, {
    attachTo: document.body,
    global: { plugins: [createVuetify()] },
  })
  await flushPromises()

  const textarea = wrapper.find('textarea')
  await textarea.setValue('invalid: : :')
  await flushPromises()
  findEnabledButtonByText('保存').click()
  await flushPromises()

  expect(wrapper.text()).toContain('YAML 解析失败')
  wrapper.unmount()
  vi.unstubAllGlobals()
})
