import { flushPromises, shallowMount } from '@vue/test-utils'
import { ref } from 'vue'
import { expect, it, vi } from 'vitest'
import { getReadingProgress, updateFilePageCount } from '@/api/files'
import PdfReader from './PdfReader.vue'

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { fileId: '42' }, query: {}, fullPath: '/reader/42' }),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }), onBeforeRouteLeave: vi.fn(),
}))
vi.mock('@/api/files', () => ({
  fileDownloadUrl: () => '/pdf', getReadingProgress: vi.fn(), updateFilePageCount: vi.fn(),
}))
vi.mock('./usePdfDocument', () => ({
  usePdfDocument: () => ({
    doc: ref({ numPages: 12, getPage: async () => ({
      getViewport: () => ({ width: 600, height: 800 }), cleanup: vi.fn(),
    }) }), load: async () => null, destroy: vi.fn(),
  }),
}))
vi.mock('./useRenderWindow', () => ({
  useRenderWindow: () => ({ registerCanvas: vi.fn(), syncWindow: vi.fn(), releaseAll: vi.fn() }),
}))
vi.mock('./progressSync', () => ({
  createProgressSync: () => ({ schedule: vi.fn(), flush: vi.fn(), dispose: vi.fn() }),
}))
it('打开后不翻页也立即上报 PDF 实际页数', async () => {
  vi.mocked(getReadingProgress).mockResolvedValue({
    file_id: 42, page_number: 1, page_count: 3, percent: 0, updated_at: null,
  })
  const wrapper = shallowMount(PdfReader)
  await flushPromises()
  expect(updateFilePageCount).toHaveBeenCalledExactlyOnceWith(42, 12)
  wrapper.unmount()
})
