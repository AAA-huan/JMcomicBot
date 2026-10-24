/** 阅读器工具栏：菜单保持打开、移动端尺寸与预加载档位。 */

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createVuetify } from 'vuetify'
import { VMenu, VSelect } from 'vuetify/components'

import ReaderToolbar from './ReaderToolbar.vue'

const displayState = vi.hoisted(() => ({ mobile: false }))

vi.mock('vuetify', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vuetify')>()
  return {
    ...actual,
    useDisplay: () => ({ mobile: displayState.mobile }),
  }
})

const DEFAULT_PROPS = {
  pageNumber: 1,
  pageCount: 10,
  mode: 'normal' as const,
  continuous: false,
  clickToTurn: false,
  reverseClick: false,
  prefetchPages: 1,
  zoomMode: 'fit-width' as const,
  zoomPercent: 100,
  dark: false,
  fullscreen: false,
  progressState: 'synced' as const,
}

function mountToolbar(
  overrides: Partial<typeof DEFAULT_PROPS> = {},
): ReturnType<typeof mount> {
  return mount(ReaderToolbar, {
    attachTo: document.body,
    props: { ...DEFAULT_PROPS, ...overrides },
    global: { plugins: [createVuetify()] },
  })
}

/** 点击当前打开菜单中的指定列表项。 */
async function clickListItem(title: string): Promise<void> {
  const item = [...document.querySelectorAll<HTMLElement>('.v-list-item')].find(
    (element) => element.textContent?.trim() === title,
  )
  if (!item) throw new Error(`未找到菜单项：${title}`)
  item.click()
  await flushPromises()
}

beforeEach(() => {
  displayState.mobile = false
  document.body.innerHTML = ''
})

afterEach(() => {
  document.body.innerHTML = ''
})

describe('桌面端菜单', () => {
  it('模式与设置菜单不随内容点击关闭，设置开关和预加载下拉可连续调整', async () => {
    const wrapper = mountToolbar()
    const menus = wrapper.findAllComponents(VMenu)
    expect(menus).toHaveLength(3)
    expect(menus[1].props('closeOnContentClick')).toBe(false)
    expect(menus[2].props('closeOnContentClick')).toBe(false)

    await wrapper.find('[aria-label="阅读设置"]').trigger('click')
    await flushPromises()
    expect(menus[2].props('modelValue')).toBe(true)

    const switches = document.querySelectorAll<HTMLInputElement>(
      'input[type="checkbox"]',
    )
    expect(switches).toHaveLength(4)
    switches[0].click()
    await flushPromises()
    expect(wrapper.emitted('update:continuous')?.[0]).toEqual([true])
    expect(menus[2].props('modelValue')).toBe(true)

    const select = wrapper.findComponent(VSelect)
    expect(select.props('items')).toEqual([
      { title: '1 页', value: 1 },
      { title: '2 页', value: 2 },
      { title: '3 页', value: 3 },
      { title: '4 页', value: 4 },
    ])
    expect(select.props('hint')).toBe(
      '连续模式当前页前后保留的页数，越大越流畅但更耗内存；手机建议 1-2',
    )
    await select.find('.v-field').trigger('mousedown')
    await select.find('.v-field').trigger('click')
    await flushPromises()
    await clickListItem('2 页')
    expect(wrapper.emitted('update:prefetch-pages')?.[0]).toEqual([2])
    expect(menus[2].props('modelValue')).toBe(true)
    wrapper.unmount()
  })

  it('选择模式后手动关闭菜单，选择缩放后菜单也收起', async () => {
    const wrapper = mountToolbar()
    const menus = wrapper.findAllComponents(VMenu)

    await wrapper.find('[aria-label="阅读模式"]').trigger('click')
    await flushPromises()
    expect(menus[1].props('modelValue')).toBe(true)
    await clickListItem('日漫模式')
    expect(wrapper.emitted('update:mode')?.[0]).toEqual(['manga'])
    expect(menus[1].props('modelValue')).toBe(false)

    const zoomButton = wrapper
      .findAll('button')
      .find((button) => button.text().trim() === '适宽')
    expect(zoomButton).toBeDefined()
    await zoomButton!.trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('适应页面')
    await clickListItem('适应页面')
    expect(wrapper.emitted('update:zoomMode')?.[0]).toEqual(['fit-page'])
    await new Promise((resolve) => setTimeout(resolve, 300))
    expect(document.querySelector('.v-overlay--active')).toBeNull()
    wrapper.unmount()
  })
})

describe('移动端菜单', () => {
  it('限制菜单最大宽度，模式/缩放/全屏选择后仍手动关闭', async () => {
    displayState.mobile = true
    const wrapper = mountToolbar()
    const menus = wrapper.findAllComponents(VMenu)
    expect(menus).toHaveLength(1)
    expect(menus[0].props('closeOnContentClick')).toBe(false)
    expect(menus[0].props('maxWidth')).toBe('340')

    await wrapper.find('[aria-label="阅读设置"]').trigger('click')
    await flushPromises()
    expect(menus[0].props('modelValue')).toBe(true)

    await clickListItem('日漫模式')
    expect(wrapper.emitted('update:mode')?.[0]).toEqual(['manga'])
    expect(menus[0].props('modelValue')).toBe(false)

    await wrapper.find('[aria-label="阅读设置"]').trigger('click')
    await flushPromises()
    await clickListItem('适应页面')
    expect(wrapper.emitted('update:zoomMode')?.[0]).toEqual(['fit-page'])
    expect(menus[0].props('modelValue')).toBe(false)

    await wrapper.find('[aria-label="阅读设置"]').trigger('click')
    await flushPromises()
    await clickListItem('进入全屏')
    expect(wrapper.emitted('toggle-fullscreen')).toHaveLength(1)
    expect(menus[0].props('modelValue')).toBe(false)
    wrapper.unmount()
  })
})

describe('预加载档位', () => {
  it('移动端下拉同样只提供 1-4 档', async () => {
    displayState.mobile = true
    const wrapper = mountToolbar()
    await wrapper.find('[aria-label="阅读设置"]').trigger('click')
    await flushPromises()

    const select = wrapper.findComponent(VSelect)
    expect(select.props('items')).toEqual([
      { title: '1 页', value: 1 },
      { title: '2 页', value: 2 },
      { title: '3 页', value: 3 },
      { title: '4 页', value: 4 },
    ])
    expect(wrapper.text()).not.toContain('仅当前页')
    wrapper.unmount()
  })
})
