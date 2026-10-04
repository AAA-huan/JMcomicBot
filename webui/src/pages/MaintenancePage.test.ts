import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createVuetify } from 'vuetify'

vi.mock('@/api/maintenance', () => ({
  scanLibrary: vi.fn(), repairLibrary: vi.fn(), verifyLibrary: vi.fn(),
  listBackups: vi.fn(), createBackup: vi.fn(),
}))
vi.mock('@/api/eventStream', () => ({ useEventSubscription: vi.fn() }))

import { listBackups, repairLibrary, scanLibrary, verifyLibrary } from '@/api/maintenance'
import MaintenancePage from './MaintenancePage.vue'

describe('维护页参数', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(listBackups).mockResolvedValue({ items: [], total: 0, pages: 0, page: 1, page_size: 10 })
  })

  it('扫描时传递预览及联网补全选项', async () => {
    vi.mocked(scanLibrary).mockResolvedValue({
      task_id: null, scanned_files: 2, manga_count: 2, new_count: 2,
      unchanged_count: 0, skipped_count: 0, duplicate_count: 0, enrich_succeeded: 0, enrich_failed: 0, chapter_errors: 0, page_read_failed: 0, details: [],
      updated_count: 0, marked_missing_count: 0, pending_cleanup_count: 1, dry_run: true,
    })
    const wrapper = mount(MaintenancePage, { global: { plugins: [createVuetify()] } })
    const checkboxes = wrapper.findAll('input[type="checkbox"]')
    await checkboxes[0].setValue(true)
    await checkboxes[1].setValue(true)
    await checkboxes[2].setValue(true)
    await checkboxes[3].setValue(true)
    await wrapper.findAll('button').find((button) => button.text().includes('预览扫描'))!.trigger('click')
    await flushPromises()
    expect(scanLibrary).toHaveBeenCalledWith({ dry_run: true, enrich: true, read_pages: true, check_chapters: true })
    expect(wrapper.text()).toContain('未写入数据库')
    expect(wrapper.text()).toContain('待标记缺失：1')
    wrapper.unmount()
  })

  it('修复预览展示差异，不执行正式修复', async () => {
    vi.mocked(repairLibrary).mockResolvedValue({ dry_run: true, cleaned_count: 0, orphan_manga_ids: ['100'], orphan_tag_names: ['孤儿标签'] })
    const wrapper = mount(MaintenancePage, { global: { plugins: [createVuetify()] } })
    await wrapper.findAll('input[type="checkbox"]')[4].setValue(true)
    await wrapper.findAll('button').find((button) => button.text().includes('预览修复差异'))!.trigger('click')
    await flushPromises()
    expect(repairLibrary).toHaveBeenCalledWith(true)
    expect(wrapper.text()).toContain('漫画 ID：100')
    expect(wrapper.text()).toContain('标签：孤儿标签')
    wrapper.unmount()
  })

  it('全部校验不需要填写漫画 ID', async () => {
    const wrapper = mount(MaintenancePage, { global: { plugins: [createVuetify()] } })
    await wrapper.find('input[value="all"]').setValue(true)
    await wrapper.findAll('button').find((button) => button.text().includes('开始校验'))!.trigger('click')
    await flushPromises()
    expect(verifyLibrary).toHaveBeenCalledWith(null)
    expect(wrapper.text()).not.toContain('请输入 1 到 100 个漫画 ID')
    wrapper.unmount()
  })
})
