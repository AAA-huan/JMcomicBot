import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { createVuetify } from 'vuetify'

vi.mock('@/api/settings', () => ({
  getOptionFile: vi.fn(),
  listSettings: vi.fn(),
  updateOptionFile: vi.fn(),
  updateSetting: vi.fn(),
}))
vi.mock('@/api/reader', () => ({
  getReaderSettings: vi.fn(),
  updateReaderSettings: vi.fn(),
}))
import { getReaderSettings, updateReaderSettings } from '@/api/reader'
import {
  getOptionFile,
  listSettings,
  updateOptionFile,
  updateSetting,
} from '@/api/settings'
import SettingsPage from '@/pages/SettingsPage.vue'
import type { ReadingSettingUpdate, ReadingSettings } from '@/reader/types'
import type { SettingView } from '@/types/api'

const DEFAULT_READER_SETTINGS: ReadingSettings = {
  reading_mode: 'normal',
  continuous: false,
  click_to_turn: false,
  reverse_click: false,
  dark_background: false,
  prefetch_pages: 1,
  updated_at: '2026-01-01T00:00:00Z',
}

function makeReaderSettings(
  overrides: Partial<ReadingSettings> = {},
): ReadingSettings {
  return { ...DEFAULT_READER_SETTINGS, ...overrides }
}

beforeEach(() => {
  vi.mocked(getReaderSettings).mockReset()
  vi.mocked(getReaderSettings).mockResolvedValue(makeReaderSettings())
  vi.mocked(updateReaderSettings).mockReset()
  vi.mocked(updateReaderSettings).mockImplementation(
    async (payload: ReadingSettingUpdate) => makeReaderSettings(payload),
  )
})

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

/** 阅读偏好卡片的四个开关，顺序与界面一致。 */
function readerSwitches(wrapper: ReturnType<typeof mount>) {
  const inputs = wrapper.findAll<HTMLInputElement>('input[type="checkbox"]')
  expect(inputs).toHaveLength(4)
  return inputs
}

it('阅读偏好加载后仅在有改动时允许保存五项设置', async () => {
  vi.stubGlobal('visualViewport', undefined)
  vi.mocked(listSettings).mockResolvedValue({ items: [] })
  vi.mocked(getOptionFile).mockResolvedValue({ content: '' })
  vi.mocked(getReaderSettings).mockResolvedValue(
    makeReaderSettings({ reading_mode: 'scroll', dark_background: true }),
  )
  vi.mocked(updateReaderSettings).mockResolvedValue(
    makeReaderSettings({
      reading_mode: 'manga',
      continuous: true,
      click_to_turn: true,
      reverse_click: true,
      dark_background: true,
    }),
  )

  const wrapper = mount(SettingsPage, {
    attachTo: document.body,
    global: { plugins: [createVuetify()] },
  })
  await flushPromises()

  expect(wrapper.text()).toContain('阅读偏好')
  expect(wrapper.text()).toContain('与阅读器工具栏共用同一份设置')
  expect(wrapper.text()).toContain('上→下阅读')
  // 未修改时保存按钮禁用
  expect(findEnabledButtonByText('保存阅读偏好')).toBeUndefined()

  await wrapper
    .findAll('button')
    .find((button) => button.text() === '日漫模式')!
    .trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('右→左阅读')

  const switches = readerSwitches(wrapper)
  await switches[0].setValue(true)
  await switches[1].setValue(true)
  await switches[2].setValue(true)
  await flushPromises()

  findEnabledButtonByText('保存阅读偏好').click()
  await flushPromises()

  expect(updateReaderSettings).toHaveBeenCalledExactlyOnceWith({
    reading_mode: 'manga',
    continuous: true,
    click_to_turn: true,
    reverse_click: true,
    dark_background: true,
  })
  expect(wrapper.text()).toContain('阅读偏好已保存')
  expect(wrapper.text()).toContain('无需重启')
  // 保存成功后恢复干净状态，按钮再次禁用
  expect(findEnabledButtonByText('保存阅读偏好')).toBeUndefined()
  wrapper.unmount()
  vi.unstubAllGlobals()
})

it('关闭点击翻页时自动关闭反转并提交两项', async () => {
  vi.stubGlobal('visualViewport', undefined)
  vi.mocked(listSettings).mockResolvedValue({ items: [] })
  vi.mocked(getOptionFile).mockResolvedValue({ content: '' })
  vi.mocked(getReaderSettings).mockResolvedValue(
    makeReaderSettings({ click_to_turn: true, reverse_click: true }),
  )

  const wrapper = mount(SettingsPage, {
    attachTo: document.body,
    global: { plugins: [createVuetify()] },
  })
  await flushPromises()

  const switches = readerSwitches(wrapper)
  expect(switches[1].element.checked).toBe(true)
  expect(switches[2].element.checked).toBe(true)

  await switches[1].setValue(false)
  await flushPromises()

  expect(switches[2].element.checked).toBe(false)
  expect(switches[2].element.disabled).toBe(true)

  findEnabledButtonByText('保存阅读偏好').click()
  await flushPromises()

  expect(updateReaderSettings).toHaveBeenCalledExactlyOnceWith({
    reading_mode: 'normal',
    continuous: false,
    click_to_turn: false,
    reverse_click: false,
    dark_background: false,
  })
  wrapper.unmount()
  vi.unstubAllGlobals()
})

it('阅读偏好加载失败显示错误并可重试', async () => {
  vi.stubGlobal('visualViewport', undefined)
  vi.mocked(listSettings).mockResolvedValue({ items: [] })
  vi.mocked(getOptionFile).mockResolvedValue({ content: '' })
  vi.mocked(getReaderSettings).mockRejectedValueOnce(new Error('设置接口不可用'))

  const wrapper = mount(SettingsPage, {
    attachTo: document.body,
    global: { plugins: [createVuetify()] },
  })
  await flushPromises()

  expect(wrapper.text()).toContain('设置接口不可用')
  expect(wrapper.text()).toContain('重试')

  vi.mocked(getReaderSettings).mockResolvedValue(makeReaderSettings())
  const retry = [...document.querySelectorAll<HTMLButtonElement>('button')].find(
    (button) => button.textContent?.trim() === '重试',
  )!
  retry.click()
  await flushPromises()

  expect(getReaderSettings).toHaveBeenCalledTimes(2)
  expect(wrapper.text()).not.toContain('设置接口不可用')
  wrapper.unmount()
  vi.unstubAllGlobals()
})

it('阅读偏好保存失败显示错误并保留未保存改动', async () => {
  vi.stubGlobal('visualViewport', undefined)
  vi.mocked(listSettings).mockResolvedValue({ items: [] })
  vi.mocked(getOptionFile).mockResolvedValue({ content: '' })
  vi.mocked(updateReaderSettings).mockRejectedValue(
    new Error('阅读设置保存被拒绝'),
  )

  const wrapper = mount(SettingsPage, {
    attachTo: document.body,
    global: { plugins: [createVuetify()] },
  })
  await flushPromises()

  await readerSwitches(wrapper)[3].setValue(true)
  await flushPromises()
  findEnabledButtonByText('保存阅读偏好').click()
  await flushPromises()

  expect(wrapper.text()).toContain('阅读设置保存被拒绝')
  expect(findEnabledButtonByText('保存阅读偏好')).toBeDefined()
  wrapper.unmount()
  vi.unstubAllGlobals()
})
