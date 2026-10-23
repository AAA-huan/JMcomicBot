import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createVuetify } from 'vuetify'
import { VSelect } from 'vuetify/components'

import PaginationBar from './PaginationBar.vue'

function mountBar(page: number, pages: number) {
  return mount(PaginationBar, {
    props: { page, pages },
    global: { plugins: [createVuetify()] },
  })
}

describe('PaginationBar', () => {
  afterEach(() => {
    delete (Element.prototype as Partial<Element>).scrollIntoView
  })

  it('首尾页固定显示，中间页全部可横向滚动且不使用省略号', () => {
    const wrapper = mountBar(5, 10)

    const edges = wrapper.findAll('.pagination-page--edge')
    expect(edges.map((button) => button.text())).toEqual(['1', '10'])
    const middle = wrapper.findAll('.pagination-scroll .pagination-page')
    expect(middle.map((button) => button.text())).toEqual([
      '2', '3', '4', '5', '6', '7', '8', '9',
    ])
    expect(wrapper.text()).not.toContain('…')
    wrapper.unmount()
  })

  it('点击页码或上一页/下一页时发出页码事件', async () => {
    const wrapper = mountBar(5, 10)

    const pageThree = wrapper
      .findAll('.pagination-page')
      .find((button) => button.text() === '3')!
    await pageThree.trigger('click')
    expect(wrapper.emitted('update:page')?.[0]).toEqual([3])

    await wrapper.find('[aria-label="下一页"]').trigger('click')
    expect(wrapper.emitted('update:page')?.[1]).toEqual([6])
    await wrapper.find('[aria-label="上一页"]').trigger('click')
    expect(wrapper.emitted('update:page')?.[2]).toEqual([4])
    wrapper.unmount()
  })

  it('当前页自动滚动到中间位置', async () => {
    const scrollIntoView = vi.fn()
    Element.prototype.scrollIntoView = scrollIntoView
    const wrapper = mountBar(5, 10)
    await flushPromises()

    expect(scrollIntoView).toHaveBeenCalledWith({
      behavior: 'smooth',
      block: 'nearest',
      inline: 'center',
    })
    wrapper.unmount()
  })

  it('分页大小选择器展示并发出切换事件', async () => {
    const wrapper = mount(PaginationBar, {
      props: { page: 1, pages: 3, pageSize: 20, pageSizeOptions: [20, 50, 100] },
      global: { plugins: [createVuetify()] },
    })

    const select = wrapper.findComponent(VSelect)
    expect(select.props('items')).toEqual([20, 50, 100])
    await select.vm.$emit('update:modelValue', 50)
    expect(wrapper.emitted('update:pageSize')?.[0]).toEqual([50])
    wrapper.unmount()
  })
})
