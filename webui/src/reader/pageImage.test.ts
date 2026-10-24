/** 页面图片探测与尺寸读取。 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import {
  loadPageImageSize,
  pageImageUrl,
  probePageImage,
} from './pageImage'

/** 构造尺寸端点的 JSON 响应，不包含任何图片字节。 */
function sizeResponse(
  width = 800,
  height = 1200,
): Response {
  return {
    status: 200,
    ok: true,
    json: async () => ({ width, height }),
  } as Response
}

const fetchMock = vi.fn()

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('pageImageUrl', () => {
  it('生成 1 基页码的取图地址', () => {
    expect(pageImageUrl(7, 3)).toBe('/api/v1/files/7/page/3')
  })
})

describe('probePageImage', () => {
  it('请求尺寸端点，404 与 415 返回回退标记', async () => {
    fetchMock.mockResolvedValueOnce({ status: 404, ok: false })
    await expect(probePageImage(7, 1)).resolves.toEqual({ kind: 'fallback' })

    fetchMock.mockResolvedValueOnce({ status: 415, ok: false })
    await expect(probePageImage(7, 1)).resolves.toEqual({ kind: 'fallback' })

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/files/7/page/1/size', {
      credentials: 'same-origin',
    })
  })

  it('401 抛出带错误码的 ApiError，由阅读器跳转登录', async () => {
    fetchMock.mockResolvedValueOnce({ status: 401, ok: false })
    const error = await probePageImage(7, 1).catch((reason: unknown) => reason)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 401, code: 'AUTH_REQUIRED' })
  })

  it('其他失败状态抛出 ApiError', async () => {
    fetchMock.mockResolvedValueOnce({ status: 500, ok: false })
    const error = await probePageImage(7, 1).catch((reason: unknown) => reason)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 500, code: 'PAGE_IMAGE_FAILED' })
  })

  it('200 时直接使用响应体尺寸，不下载图片字节也不 decode', async () => {
    fetchMock.mockResolvedValueOnce(sizeResponse())
    await expect(probePageImage(7, 2)).resolves.toEqual({
      kind: 'image',
      size: { width: 800, height: 1200 },
    })
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(
      '/api/v1/files/7/page/2/size',
      { credentials: 'same-origin' },
    )
  })

  it('尺寸非法时失败，避免以 0 尺寸进入图片型路径', async () => {
    fetchMock.mockResolvedValueOnce(sizeResponse(0, 1200))
    const error = await probePageImage(7, 1).catch((reason: unknown) => reason)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 422, code: 'PAGE_IMAGE_INVALID' })
  })
})

describe('loadPageImageSize', () => {
  it('成功时请求尺寸端点并返回尺寸', async () => {
    fetchMock.mockResolvedValueOnce(sizeResponse(1000, 1320))
    await expect(loadPageImageSize(7, 1)).resolves.toEqual({
      width: 1000,
      height: 1320,
    })
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(
      '/api/v1/files/7/page/1/size',
      { credentials: 'same-origin' },
    )
  })

  it('普通失败返回 null，仅用于占位尺寸兜底', async () => {
    fetchMock.mockResolvedValueOnce({ status: 500, ok: false })
    await expect(loadPageImageSize(7, 1)).resolves.toBeNull()
  })

  it('401 继续向上抛出，避免未登录时静默回退', async () => {
    fetchMock.mockResolvedValueOnce({ status: 401, ok: false })
    await expect(loadPageImageSize(7, 1)).rejects.toMatchObject({ status: 401 })
  })
})
