import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ApiError,
  apiRequest,
  errorMessage,
  setUnauthorizedHandler,
} from '@/api/client'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('apiRequest', () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
    fetchMock.mockReset()
    document.cookie = 'jmbot_csrf=token-123'
  })

  afterEach(() => {
    setUnauthorizedHandler(null)
    vi.unstubAllGlobals()
    document.cookie = 'jmbot_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT'
  })

  it('写请求自动携带 CSRF 头与 JSON 内容类型', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }))

    await apiRequest('/tasks/downloads', {
      method: 'POST',
      body: { manga_ids: ['1'] },
    })

    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toBe('http://localhost:3000/api/v1/tasks/downloads')
    expect(init.headers['X-CSRF-Token']).toBe('token-123')
    expect(init.headers['Content-Type']).toBe('application/json')
    expect(init.credentials).toBe('same-origin')
  })

  it('GET 请求不携带 CSRF 头', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [] }))

    await apiRequest('/settings')

    const [, init] = fetchMock.mock.calls[0]
    expect(init.headers['X-CSRF-Token']).toBeUndefined()
  })

  it('查询参数忽略空值并拼接', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [] }))

    await apiRequest('/mangas', {
      query: { page: 2, search: '苹果', status: '', tag: undefined },
    })

    const [url] = fetchMock.mock.calls[0]
    const parsed = new URL(String(url))
    expect(parsed.searchParams.get('page')).toBe('2')
    expect(parsed.searchParams.get('search')).toBe('苹果')
    expect(parsed.searchParams.has('status')).toBe(false)
    expect(parsed.searchParams.has('tag')).toBe(false)
  })

  it('错误响应转换为带中文消息的 ApiError', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        { code: 'MANGA_DOWNLOADING', message: '漫画正在下载中，无法删除', details: null },
        409,
      ),
    )

    await expect(
      apiRequest('/mangas/100', { method: 'DELETE' }),
    ).rejects.toMatchObject({
      status: 409,
      code: 'MANGA_DOWNLOADING',
      message: '漫画正在下载中，无法删除',
    })
  })

  it('401 触发未授权处理且登录接口除外', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    fetchMock.mockImplementation(() =>
      Promise.resolve(jsonResponse({ code: 'AUTH_REQUIRED', message: '尚未登录' }, 401)),
    )

    await expect(apiRequest('/system/status')).rejects.toBeInstanceOf(ApiError)
    expect(handler).toHaveBeenCalledTimes(1)

    handler.mockClear()
    await expect(
      apiRequest('/auth/login', { method: 'POST', body: { password: 'x' } }),
    ).rejects.toBeInstanceOf(ApiError)
    expect(handler).not.toHaveBeenCalled()
  })

  it('网络异常给出一致的中文提示', () => {
    expect(errorMessage(new ApiError(500, 'INTERNAL_ERROR', '服务器内部错误'))).toBe(
      '服务器内部错误',
    )
    expect(errorMessage(new Error('Failed to fetch'))).toContain('网络请求失败')
    expect(errorMessage('boom')).toContain('网络请求失败')
  })
})
