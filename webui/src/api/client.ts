/** 统一 API 客户端：携带会话 Cookie 与 CSRF 头，统一中文错误对象。 */

const API_BASE = '/api/v1'
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])
const CSRF_COOKIE = 'jmbot_csrf'
const CSRF_HEADER = 'X-CSRF-Token'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: unknown

  constructor(status: number, code: string, message: string, details: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

type UnauthorizedHandler = () => void

let unauthorizedHandler: UnauthorizedHandler | null = null

/** 注册 401 处理（会话过期时跳转登录），由应用入口注入。 */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler
}

function readCookie(name: string): string | null {
  const prefix = `${name}=`
  for (const part of document.cookie.split(';')) {
    const trimmed = part.trim()
    if (trimmed.startsWith(prefix)) {
      return decodeURIComponent(trimmed.slice(prefix.length))
    }
  }
  return null
}

/** 读取 CSRF Token，供 keepalive 等自定义 fetch 请求复用。 */
export function readCsrfToken(): string | null {
  return readCookie(CSRF_COOKIE)
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  query?: Record<string, string | number | boolean | null | undefined>
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? 'GET'
  const url = new URL(`${API_BASE}${path}`, window.location.origin)
  if (options.query) {
    for (const [key, value] of Object.entries(options.query)) {
      if (value === undefined || value === null || value === '') continue
      url.searchParams.set(key, String(value))
    }
  }

  const headers: Record<string, string> = { Accept: 'application/json' }
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
  }
  if (!SAFE_METHODS.has(method)) {
    const token = readCookie(CSRF_COOKIE)
    if (token) headers[CSRF_HEADER] = token
  }

  const response = await fetch(url.toString(), {
    method,
    headers,
    credentials: 'same-origin',
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })

  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = null
    }
  }

  if (!response.ok) {
    const errorPayload = (payload ?? {}) as {
      code?: string
      message?: string
      details?: unknown
    }
    const error = new ApiError(
      response.status,
      errorPayload.code ?? 'REQUEST_FAILED',
      errorPayload.message ?? '请求失败，请稍后重试',
      errorPayload.details ?? null,
    )
    // 会话过期统一跳转登录；登录/状态接口的 401 由页面自行处理
    if (response.status === 401 && path !== '/auth/login' && path !== '/auth/status') {
      unauthorizedHandler?.()
    }
    throw error
  }

  return payload as T
}

/** 把任意异常转换为适合界面展示的中文提示。 */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error && error.message) {
    return `网络请求失败：${error.message}`
  }
  return '网络请求失败，请检查后端服务是否运行'
}
