/**
 * 页面图片探测与尺寸读取。
 *
 * 阅读器首次打开请求当前进度页的尺寸端点：200 表示图片型 PDF，404/415
 * 表示需要回退 PDF.js。尺寸直接读取服务端返回的宽高元数据，不下载图片
 * 字节，也不在客户端 decode 整图，避免手机打开阅读器时额外耗时。
 */

import { ApiError } from '@/api/client'
import { filePageImageSizeUrl, filePageImageUrl } from '@/api/files'
import type { PageBaseSize } from './types'

/** 页面图片地址；页码从 1 开始。 */
export function pageImageUrl(fileId: number, pageNumber: number): string {
  return filePageImageUrl(fileId, pageNumber)
}

export type PageImageProbe =
  | { kind: 'image'; size: PageBaseSize }
  | { kind: 'fallback' }

/** 解析尺寸端点的 JSON 响应；非法尺寸明确报错，避免以 0 尺寸进入布局。 */
async function readPageSize(response: Response): Promise<PageBaseSize> {
  const payload = (await response.json()) as Partial<PageBaseSize>
  const width = payload.width
  const height = payload.height
  if (
    typeof width !== 'number' ||
    typeof height !== 'number' ||
    !Number.isInteger(width) ||
    !Number.isInteger(height) ||
    width <= 0 ||
    height <= 0
  ) {
    throw new ApiError(422, 'PAGE_IMAGE_INVALID', '页面图片尺寸无效')
  }
  return { width, height }
}

/** 请求指定页尺寸；非 2xx 统一抛出 ApiError 并保留原始状态码。 */
async function fetchImageSize(url: string): Promise<PageBaseSize> {
  const response = await fetch(url, { credentials: 'same-origin' })
  if (!response.ok) {
    throw new ApiError(
      response.status,
      response.status === 401 ? 'AUTH_REQUIRED' : 'PAGE_IMAGE_FAILED',
      '页面图片尺寸加载失败',
    )
  }
  return readPageSize(response)
}

/**
 * 探测指定页是否为图片型内容。
 *
 * 返回 fallback 表示服务端明确判定为非图片型（404/415）；网络或服务端
 * 错误向上抛出，由阅读器统一决定回退或提示。
 */
export async function probePageImage(
  fileId: number,
  pageNumber: number,
): Promise<PageImageProbe> {
  const response = await fetch(filePageImageSizeUrl(fileId, pageNumber), {
    credentials: 'same-origin',
  })
  if (response.status === 404 || response.status === 415) {
    return { kind: 'fallback' }
  }
  if (response.status === 401) {
    throw new ApiError(401, 'AUTH_REQUIRED', '登录状态已失效')
  }
  if (!response.ok) {
    throw new ApiError(response.status, 'PAGE_IMAGE_FAILED', '页面图片加载失败')
  }
  return { kind: 'image', size: await readPageSize(response) }
}

/** 读取指定页原图尺寸；失败返回 null（仅用于占位尺寸兜底）。 */
export async function loadPageImageSize(
  fileId: number,
  pageNumber: number,
): Promise<PageBaseSize | null> {
  try {
    return await fetchImageSize(filePageImageSizeUrl(fileId, pageNumber))
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) throw error
    return null
  }
}
