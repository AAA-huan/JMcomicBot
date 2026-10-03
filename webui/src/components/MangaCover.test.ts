import { flushPromises, mount } from '@vue/test-utils'
import { shallowRef } from 'vue'
import { createVuetify } from 'vuetify'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ load: vi.fn(), destroy: vi.fn(), getPage: vi.fn() }))
vi.mock('@/reader/usePdfDocument', () => ({
  usePdfDocument: () => ({
    doc: shallowRef({ getPage: mocks.getPage }),
    load: mocks.load,
    destroy: mocks.destroy,
  }),
}))

import MangaCover from './MangaCover.vue'

describe('漫画封面预览', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.load.mockResolvedValue(null)
    mocks.destroy.mockResolvedValue(undefined)
  })

  it('渲染第一页并在离开页面时释放 PDF', async () => {
    const cancel = vi.fn()
    const cleanup = vi.fn()
    const render = vi.fn().mockReturnValue({ promise: Promise.resolve(), cancel })
    mocks.getPage.mockResolvedValue({
      getViewport: () => ({ width: 640, height: 960 }), render, cleanup,
    })
    const wrapper = mount(MangaCover, { props: { fileId: 42 }, global: { plugins: [createVuetify()] } })
    await flushPromises()
    expect(mocks.load).toHaveBeenCalledWith(42)
    expect(mocks.getPage).toHaveBeenCalledWith(1)
    expect(render).toHaveBeenCalledOnce()
    expect(wrapper.find('canvas').isVisible()).toBe(true)
    expect(cleanup).toHaveBeenCalledOnce()
    wrapper.unmount()
    expect(cancel).toHaveBeenCalledOnce()
    expect(mocks.destroy).toHaveBeenCalledOnce()
  })

  it('加载失败显示错误，不尝试渲染', async () => {
    mocks.load.mockResolvedValue({ type: 'missing', message: '文件不存在或已被移除' })
    const wrapper = mount(MangaCover, { props: { fileId: 42 }, global: { plugins: [createVuetify()] } })
    await flushPromises()
    expect(wrapper.text()).toContain('文件不存在或已被移除')
    expect(mocks.getPage).not.toHaveBeenCalled()
    expect(wrapper.find('canvas').isVisible()).toBe(false)
    wrapper.unmount()
  })
})
