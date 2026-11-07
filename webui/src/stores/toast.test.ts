/** 全局 toast 队列：入队、自动过期、手动关闭与同屏上限。 */

import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  DEFAULT_TOAST_TIMEOUT,
  MAX_VISIBLE_TOASTS,
  useToast,
} from '@/stores/toast'

const toast = useToast()
const { visible } = toast

beforeEach(() => {
  toast.clear()
  vi.useFakeTimers()
})

describe('toast store', () => {
  it('success 入队并在默认时间后自动消失', () => {
    toast.success('已收藏')
    expect(visible.value).toHaveLength(1)
    expect(visible.value[0].type).toBe('success')

    vi.advanceTimersByTime(DEFAULT_TOAST_TIMEOUT)
    expect(visible.value).toHaveLength(0)
  })

  it('error 与 info 使用同一默认过期时间', () => {
    toast.error('操作失败')
    toast.info('提示')
    vi.advanceTimersByTime(DEFAULT_TOAST_TIMEOUT - 1)
    expect(visible.value).toHaveLength(2)
    vi.advanceTimersByTime(1)
    expect(visible.value).toHaveLength(0)
  })

  it('手动关闭立即移除消息', () => {
    toast.success('可关闭')
    toast.dismiss(visible.value[0].id)
    expect(visible.value).toHaveLength(0)
  })

  it('超过同屏上限时排队，前面的消失后补位', () => {
    for (let index = 0; index < MAX_VISIBLE_TOASTS + 2; index += 1) {
      toast.success(`消息${index}`)
    }
    expect(visible.value).toHaveLength(MAX_VISIBLE_TOASTS)

    toast.dismiss(visible.value[0].id)
    expect(visible.value).toHaveLength(MAX_VISIBLE_TOASTS)
    expect(visible.value.map((item) => item.message)).toEqual(['消息1', '消息2', '消息3'])
  })

  it('常驻 info 不自动消失，需手动关闭', () => {
    toast.info('服务正在重启', { persistent: true })
    vi.advanceTimersByTime(DEFAULT_TOAST_TIMEOUT * 10)
    expect(visible.value).toHaveLength(1)
    expect(visible.value[0].timeout).toBeNull()

    toast.dismiss(visible.value[0].id)
    expect(visible.value).toHaveLength(0)
  })
})
