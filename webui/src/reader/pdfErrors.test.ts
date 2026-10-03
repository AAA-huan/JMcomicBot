/** PDF.js 异常到中文错误界面的映射。 */

import { InvalidPDFException, PasswordException, ResponseException } from 'pdfjs-dist/legacy/build/pdf.mjs'
import { describe, expect, it } from 'vitest'

import { mapPdfError } from './pdfErrors'

describe('mapPdfError', () => {
  it('401 映射为登录失效并跳转登录', () => {
    const error = new ResponseException('unauthorized', 401, false)
    expect(mapPdfError(error)).toEqual({
      type: 'auth',
      message: '登录状态已失效，请重新登录',
    })
  })

  it('404 映射为文件不存在', () => {
    const error = new ResponseException('not found', 404, true)
    expect(mapPdfError(error).type).toBe('missing')
  })

  it('范围请求失败等其他状态映射为网络错误并保留状态码', () => {
    const result = mapPdfError(new ResponseException('range', 416, false))
    expect(result.type).toBe('network')
    expect(result.message).toContain('416')
  })

  it('损坏 PDF 映射为损坏提示', () => {
    const result = mapPdfError(new InvalidPDFException('bad structure'))
    expect(result.type).toBe('corrupt')
    expect(result.message).toContain('损坏')
  })

  it('加密 PDF 映射为不支持提示', () => {
    const result = mapPdfError(new PasswordException('need password', 1))
    expect(result.type).toBe('encrypted')
    expect(result.message).toContain('加密')
  })

  it('未知异常映射为通用错误', () => {
    expect(mapPdfError(new Error('boom')).type).toBe('unknown')
  })
})
