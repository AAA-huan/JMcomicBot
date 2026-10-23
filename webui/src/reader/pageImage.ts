/**
 * 页面图片探测与尺寸读取。
 *
 * 阅读器首次打开直接请求当前进度页：200 表示图片型 PDF，404/415 表示
 * 需要回退 PDF.js。探测请求与页面尺寸读取共用同一响应，避免额外接口。
 */

import { ApiError } from '@/api/client'
import { filePageImageUrl } from '@/api/files'
import type { PageBaseSize } from './types'

/** 页面图片地址；页码从 1 开始。 */
export function pageImageUrl(fileId: number, pageNumber: number): string {
  return filePageImageUrl(fileId, pageNumber)
}

export type PageImageProbe =
  | { kind: 'image'; size: PageBaseSize }
  | { kind: 'fallback' }

/** 从 Blob 加载图片并读取原始像素尺寸。 */
function blobImageSize(blob: Blob): Promise<PageBaseSize> {
  const objectUrl = URL.createObjectURL(blob)
  return new Promise<PageBaseSize>((resolve, reject) => {
    const image = new Image()
    image.onload = () => {
      URL.revokeObjectURL(objectUrl)
      const size = { width: image.naturalWidth, height: image.naturalHeight }
      if (size.width <= 0 || size.height <= 0) {
        reject(new ApiError(422, 'PAGE_IMAGE_INVALID', '页面图片尺寸无效'))
        return
      }
      resolve(size)
    }
    image.onerror = () => {
      URL.revokeObjectURL(objectUrl)
      reject(new ApiError(422, 'PAGE_IMAGE_INVALID', '页面图片无法解码'))
    }
    image.src = objectUrl
  })
}

async function fetchImageSize(url: string): Promise<PageBaseSize> {
  const response = await fetch(url, { credentials: 'same-origin' })
  if (!response.ok) {
    throw new ApiError(response.status, 'PAGE_IMAGE_FAILED', '页面图片加载失败')
  }
  return blobImageSize(await response.blob())
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
  const response = await fetch(pageImageUrl(fileId, pageNumber), {
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
  return { kind: 'image', size: await blobImageSize(await response.blob()) }
}

/** 读取指定页原图尺寸；失败返回 null（仅用于占位尺寸兜底）。 */
export async function loadPageImageSize(
  fileId: number,
  pageNumber: number,
): Promise<PageBaseSize | null> {
  try {
    return await fetchImageSize(pageImageUrl(fileId, pageNumber))
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) throw error
    return null
  }
}
