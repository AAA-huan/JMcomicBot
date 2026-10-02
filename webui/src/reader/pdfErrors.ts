/**
 * PDF.js 异常到中文阅读器错误的映射。
 *
 * 独立于 usePdfDocument，便于单元测试且不触发 Worker 初始化。
 */

import {
  InvalidPDFException,
  PasswordException,
  RenderingCancelledException,
  ResponseException,
} from 'pdfjs-dist'

export type ReaderErrorType =
  | 'auth'
  | 'corrupt'
  | 'encrypted'
  | 'missing'
  | 'network'
  | 'unknown'

export interface ReaderError {
  type: ReaderErrorType
  message: string
}

/** 把 PDF.js 抛出的异常映射为可展示的中文错误。 */
export function mapPdfError(error: unknown): ReaderError {
  if (error instanceof ResponseException) {
    if (error.status === 401) {
      return { type: 'auth', message: '登录状态已失效，请重新登录' }
    }
    if (error.status === 404 || error.missing) {
      return { type: 'missing', message: '文件不存在或已被移除' }
    }
    return {
      type: 'network',
      message: `文件读取失败（HTTP ${error.status}），请重试`,
    }
  }
  if (error instanceof InvalidPDFException) {
    return { type: 'corrupt', message: 'PDF 文件已损坏或格式不完整' }
  }
  if (error instanceof PasswordException) {
    return {
      type: 'encrypted',
      message: '暂不支持加密 PDF，请下载后使用本地阅读器打开',
    }
  }
  return { type: 'unknown', message: 'PDF 加载失败，请重试' }
}

export function isRenderingCancelled(error: unknown): boolean {
  return error instanceof RenderingCancelledException
}
