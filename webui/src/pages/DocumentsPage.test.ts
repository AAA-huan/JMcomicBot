import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createVuetify } from 'vuetify'

vi.mock('@/api/documents', () => ({ listDocuments: vi.fn(), getDocument: vi.fn() }))

import { getDocument, listDocuments } from '@/api/documents'
import DocumentsPage from './DocumentsPage.vue'

async function mountPage(path = '/documents') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/documents', name: 'documents', component: DocumentsPage }],
  })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(DocumentsPage, { global: { plugins: [router, createVuetify()] } })
  await flushPromises()
  return { wrapper, router }
}

describe('项目文档页', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(listDocuments).mockResolvedValue([
      { path: 'guide.md', title: '指南' },
      { path: 'deployment/linux.md', title: 'Linux 部署' },
    ])
    vi.mocked(getDocument).mockResolvedValue({ path: 'guide.md', content: '# 使用指南\n\n**正文**\n\n[部署](deployment/linux.md)\n\n<img src="x" onerror="alert(1)"><script>alert(1)</script>' })
  })

  it('默认选择第一篇，渲染 Markdown 并清理危险 HTML', async () => {
    const { wrapper, router } = await mountPage()
    await vi.waitFor(() => expect(getDocument).toHaveBeenCalledWith('guide.md'))
    await flushPromises()
    expect(router.currentRoute.value.query.doc).toBe('guide.md')
    expect(wrapper.find('article h1').text()).toBe('使用指南')
    expect(wrapper.find('article strong').text()).toBe('正文')
    expect(wrapper.find('article script').exists()).toBe(false)
    expect(wrapper.find('article img').attributes('onerror')).toBeUndefined()
    wrapper.unmount()
  })

  it('相对文档链接跳转到子目录文档', async () => {
    const { wrapper, router } = await mountPage('/documents?doc=guide.md')
    await wrapper.find('article a').trigger('click')
    await vi.waitFor(() => expect(router.currentRoute.value.query.doc).toBe('deployment/linux.md'))
    expect(getDocument).toHaveBeenLastCalledWith('deployment/linux.md')
    wrapper.unmount()
  })

  it('读取失败展示中文错误和重试', async () => {
    vi.mocked(getDocument).mockRejectedValue(new Error('Failed to fetch'))
    const { wrapper } = await mountPage('/documents?doc=guide.md')
    expect(wrapper.text()).toContain('网络请求失败')
    expect(wrapper.text()).toContain('重试')
    wrapper.unmount()
  })
})
