import { afterEach, describe, expect, it, vi } from 'vitest'

import { copyText } from './clipboard'

describe('clipboard copyText', () => {
  const originalExec = document.execCommand
  afterEach(() => {
    vi.unstubAllGlobals()
    // 恢复原始 execCommand（jsdom 下为 undefined，但显式恢复更安全）
    if (originalExec) {
      document.execCommand = originalExec
    } else {
      // @ts-expect-error jsdom 不实现 execCommand，删除测试注入的 mock
      delete document.execCommand
    }
  })

  it('安全上下文优先用 navigator.clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('isSecureContext', true)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const ok = await copyText('hello')
    expect(ok).toBe(true)
    expect(writeText).toHaveBeenCalledWith('hello')
  })

  it('navigator.clipboard 失败时回退到 execCommand', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('denied'))
    vi.stubGlobal('isSecureContext', true)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const execMock = vi.fn().mockReturnValue(true)
    document.execCommand = execMock
    const ok = await copyText('fallback')
    expect(ok).toBe(true)
    expect(writeText).toHaveBeenCalled()
    expect(execMock).toHaveBeenCalledWith('copy')
  })

  it('非安全上下文走 execCommand 回退', async () => {
    vi.stubGlobal('isSecureContext', false)
    const execMock = vi.fn().mockReturnValue(true)
    document.execCommand = execMock
    const ok = await copyText('plain')
    expect(ok).toBe(true)
    expect(execMock).toHaveBeenCalledWith('copy')
  })

  it('execCommand 失败返回 false', async () => {
    vi.stubGlobal('isSecureContext', false)
    document.execCommand = vi.fn().mockReturnValue(false)
    const ok = await copyText('fail')
    expect(ok).toBe(false)
  })
})
