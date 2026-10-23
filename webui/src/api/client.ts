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

/** 从 Content-Disposition 中提取附件文件名。 */
function filenameFromDisposition(value: string | null): string | null {
  if (!value) return null
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(value)
  if (encoded) return decodeURIComponent(encoded[1])
  const quoted = /filename="([^"]+)"/i.exec(value)
  if (quoted) return quoted[1]
  const plain = /filename=([^;]+)/i.exec(value)
  return plain ? plain[1].trim() : null
}

/** 把失败响应转换为带稳定错误码的 ApiError。 */
async function parseErrorResponse(response: Response): Promise<ApiError> {
  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = null
    }
  }
  const errorPayload = (payload ?? {}) as {
    code?: string
    message?: string
    details?: unknown
  }
  return new ApiError(
    response.status,
    errorPayload.code ?? 'REQUEST_FAILED',
    errorPayload.message ?? '请求失败，请稍后重试',
    errorPayload.details ?? null,
  )
}

function handleUnauthorized(path: string, error: ApiError): void {
  // 会话过期统一跳转登录；登录/状态接口的 401 由页面自行处理
  if (error.status === 401 && path !== '/auth/login' && path !== '/auth/status') {
    unauthorizedHandler?.()
  }
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

  if (!response.ok) {
    const error = await parseErrorResponse(response)
    handleUnauthorized(path, error)
    throw error
  }

  const text = await response.text()
  if (!text) return null as T
  try {
    return JSON.parse(text) as T
  } catch {
    return null as T
  }
}

/** 上传 multipart 表单，浏览器自动设置 boundary，统一携带 CSRF 头。 */
export async function apiUpload<T>(path: string, formData: FormData): Promise<T> {
  const url = new URL(`${API_BASE}${path}`, window.location.origin)
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = readCookie(CSRF_COOKIE)
  if (token) headers[CSRF_HEADER] = token

  const response = await fetch(url.toString(), {
    method: 'POST',
    headers,
    credentials: 'same-origin',
    body: formData,
  })
  if (!response.ok) {
    const error = await parseErrorResponse(response)
    handleUnauthorized(path, error)
    throw error
  }
  const text = await response.text()
  return (text ? JSON.parse(text) : null) as T
}

export interface DownloadedFile {
  blob: Blob
  filename: string | null
}

/** 以流式请求下载二进制文件，并解析服务端建议的文件名。 */
export async function apiDownload(
  path: string,
  method: 'GET' | 'POST' = 'GET',
): Promise<DownloadedFile> {
  const url = new URL(`${API_BASE}${path}`, window.location.origin)
  const headers: Record<string, string> = { Accept: 'application/octet-stream' }
  if (!SAFE_METHODS.has(method)) {
    const token = readCookie(CSRF_COOKIE)
    if (token) headers[CSRF_HEADER] = token
  }
  const response = await fetch(url.toString(), {
    method,
    headers,
    credentials: 'same-origin',
  })
  if (!response.ok) {
    const error = await parseErrorResponse(response)
    handleUnauthorized(path, error)
    throw error
  }
  return {
    blob: await response.blob(),
    filename: filenameFromDisposition(response.headers.get('content-disposition')),
  }
}

/** 把任意异常转换为适合界面展示的中文提示。 */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error && error.message) {
    return `网络请求失败：${error.message}`
  }
  return '网络请求失败，请检查后端服务是否运行'
}
