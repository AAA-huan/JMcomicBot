import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createVuetify } from 'vuetify'

import IdScrollWindow from './IdScrollWindow.vue'

const global = { plugins: [createVuetify()] }

describe('IdScrollWindow', () => {
  it('空列表时不渲染窗口', () => {
    const wrapper = mount(IdScrollWindow, {
      props: { title: '待标记缺失', items: [] },
      global,
    })

    expect(wrapper.find('.id-scroll-window').exists()).toBe(false)
    expect(wrapper.text()).toBe('')
    wrapper.unmount()
  })

  it('展示标题、数量与全部条目', () => {
    const wrapper = mount(IdScrollWindow, {
      props: { title: '已清理标签', items: ['标签一', '标签二'] },
      global,
    })

    expect(wrapper.find('.id-scroll-window').exists()).toBe(true)
    expect(wrapper.text()).toContain('已清理标签（2）')
    expect(wrapper.text()).toContain('标签一')
    expect(wrapper.text()).toContain('标签二')
    wrapper.unmount()
  })
})
