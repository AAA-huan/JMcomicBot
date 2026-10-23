import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createVuetify } from 'vuetify'

vi.mock('@/api/maintenance', () => ({
  scanLibrary: vi.fn(), repairLibrary: vi.fn(), verifyLibrary: vi.fn(),
  exportData: vi.fn(), validateDataImport: vi.fn(), applyDataImport: vi.fn(),
}))
vi.mock('@/api/eventStream', () => ({ useEventSubscription: vi.fn() }))

import {
  applyDataImport,
  exportData,
  repairLibrary,
  scanLibrary,
  validateDataImport,
  verifyLibrary,
} from '@/api/maintenance'
import MaintenancePage from './MaintenancePage.vue'

describe('维护页参数', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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
    vi.mocked(repairLibrary).mockResolvedValue({
      dry_run: true,
      cleaned_count: 0,
      orphan_manga_ids: ['100'],
      orphan_tag_names: ['孤儿标签'],
      processed_manga_ids: [],
      removed_tag_names: [],
    })
    const wrapper = mount(MaintenancePage, { global: { plugins: [createVuetify()] } })
    await wrapper.findAll('input[type="checkbox"]')[4].setValue(true)
    await wrapper.findAll('button').find((button) => button.text().includes('预览修复差异'))!.trigger('click')
    await flushPromises()
    expect(repairLibrary).toHaveBeenCalledWith(true)
    expect(wrapper.text()).toContain('待标记缺失（1）')
    expect(wrapper.text()).toContain('待清理标签（1）')
    expect(wrapper.text()).toContain('100')
    expect(wrapper.text()).toContain('孤儿标签')
    expect(wrapper.text()).not.toContain('已标记缺失')
    wrapper.unmount()
  })

  it('正式修复展示实际处理结果', async () => {
    vi.mocked(repairLibrary).mockResolvedValue({
      dry_run: false,
      cleaned_count: 2,
      orphan_manga_ids: [],
      orphan_tag_names: [],
      processed_manga_ids: ['200', '201'],
      removed_tag_names: ['废弃标签'],
    })
    const wrapper = mount(MaintenancePage, { global: { plugins: [createVuetify()] } })
    await wrapper.findAll('button').find((button) => button.text().includes('开始修复'))!.trigger('click')
    await flushPromises()
    const confirmButton = Array.from(document.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('确认修复'),
    )
    expect(confirmButton).toBeTruthy()
    confirmButton!.click()
    await flushPromises()
    expect(repairLibrary).toHaveBeenCalledWith(false)
    expect(wrapper.text()).toContain('已清理 2 条孤儿记录')
    expect(wrapper.text()).toContain('已标记缺失（2）')
    expect(wrapper.text()).toContain('已清理标签（1）')
    expect(wrapper.text()).toContain('200')
    expect(wrapper.text()).toContain('废弃标签')
    expect(wrapper.text()).not.toContain('待标记缺失')
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

describe('维护页数据迁移', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('导出数据触发浏览器下载并提示文件名', async () => {
    vi.mocked(exportData).mockResolvedValue({
      blob: new Blob(['zip']),
      filename: 'data-export-20261023-120000-schema0029_add_manga_status_favorited.zip',
    })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const wrapper = mount(MaintenancePage, { global: { plugins: [createVuetify()] } })

    await wrapper.findAll('button').find((button) => button.text().includes('导出数据'))!.trigger('click')
    await flushPromises()

    expect(exportData).toHaveBeenCalledTimes(1)
    expect(click).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('数据已导出：data-export-20261023-120000-schema0029_add_manga_status_favorited.zip')
    click.mockRestore()
    wrapper.unmount()
  })

  it('选择 zip 后校验并展示 schema、表行数与路径差异', async () => {
    vi.mocked(validateDataImport).mockResolvedValue({
      format_version: 1,
      schema_revision: '0026_manga_blacklist',
      exported_at: '2026-10-23T12:00:00Z',
      db_filename: 'main-20261023-120000.db',
      db_sha256: 'a'.repeat(64),
      table_counts: { manga: 12, manga_favorite: 3 },
      export_env: { db_path: './data', manga_download_path: './downloads' },
      current_schema_revision: '0029_add_manga_status_favorited',
      path_warnings: ['导出环境下载目录为 ./downloads，当前为 ./other-downloads，请确保 PDF 已拷贝到当前目录或调整配置'],
    })
    const wrapper = mount(MaintenancePage, {
      attachTo: document.body,
      global: { plugins: [createVuetify()] },
    })
    const file = new File(['zip'], 'data.zip', { type: 'application/zip' })
    const input = wrapper.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await flushPromises()

    expect(validateDataImport).toHaveBeenCalledWith(file)
    expect(wrapper.text()).toContain('导出 schema：0026_manga_blacklist')
    expect(wrapper.text()).toContain('当前 schema：0029_add_manga_status_favorited')
    expect(wrapper.text()).toContain('漫画')
    expect(wrapper.text()).toContain('12')
    expect(wrapper.text()).toContain('请确保 PDF 已拷贝到当前目录')
    wrapper.unmount()
  })

  it('二次确认后使用同一文件执行导入并提示重启', async () => {
    vi.mocked(validateDataImport).mockResolvedValue({
      format_version: 1,
      schema_revision: '0029_add_manga_status_favorited',
      exported_at: '2026-10-23T12:00:00Z',
      db_filename: 'main-20261023-120000.db',
      db_sha256: 'a'.repeat(64),
      table_counts: { manga: 1 },
      export_env: { db_path: './data', manga_download_path: './downloads' },
      current_schema_revision: '0029_add_manga_status_favorited',
      path_warnings: [],
    })
    vi.mocked(applyDataImport).mockResolvedValue({ restart: true })
    const wrapper = mount(MaintenancePage, {
      attachTo: document.body,
      global: { plugins: [createVuetify()] },
    })
    const file = new File(['zip'], 'data.zip', { type: 'application/zip' })
    const input = wrapper.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text().includes('确认导入'))!.trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('确认导入全部数据？')
    const confirmButton = Array.from(document.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('确认导入并重启'),
    )
    expect(confirmButton).toBeTruthy()
    confirmButton!.click()
    await flushPromises()

    expect(applyDataImport).toHaveBeenCalledWith(file)
    expect(wrapper.text()).toContain('数据库导入完成，服务正在重启')
    wrapper.unmount()
  })

  it('校验失败的 zip 展示错误且不保留待导入文件', async () => {
    vi.mocked(validateDataImport).mockRejectedValue(new Error('结构错误'))
    const wrapper = mount(MaintenancePage, { global: { plugins: [createVuetify()] } })
    const file = new File(['zip'], 'data.zip', { type: 'application/zip' })
    const input = wrapper.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await flushPromises()

    expect(wrapper.text()).toContain('网络请求失败：结构错误')
    expect(wrapper.find('button').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('确认导入')
    wrapper.unmount()
  })
})
