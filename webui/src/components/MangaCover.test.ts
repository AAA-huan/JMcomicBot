import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import { describe, expect, it } from 'vitest'

import MangaCover from './MangaCover.vue'

/** 用可控的图片桩替换 v-img，便于断言地址并模拟加载失败。 */
const VImgStub = {
  name: 'VImg',
  props: { src: { type: String, default: '' } },
  emits: ['error'],
  template: '<div class="img-stub" :data-src="src" @click="$emit(\'error\')" />',
}

function mountCover() {
  return mount(MangaCover, {
    props: { fileId: 42 },
    global: {
      plugins: [createVuetify()],
      stubs: { VImg: VImgStub },
    },
  })
}

describe('漫画封面预览', () => {
  it('直接使用封面图片地址，不加载 PDF.js', () => {
    const wrapper = mountCover()
    expect(wrapper.find('.img-stub').attributes('data-src')).toBe(
      '/api/v1/files/42/cover',
    )
    expect(wrapper.find('canvas').exists()).toBe(false)
    wrapper.unmount()
  })

  it('封面加载失败显示占位文案', async () => {
    const wrapper = mountCover()
    await wrapper.find('.img-stub').trigger('click')
    expect(wrapper.text()).toContain('封面不可用')
    expect(wrapper.find('.img-stub').exists()).toBe(false)
    wrapper.unmount()
  })
})
