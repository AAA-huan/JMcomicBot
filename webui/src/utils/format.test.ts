import { describe, expect, it } from 'vitest'

import {
  formatBytes,
  formatDateTime,
  formatUptime,
  parseMangaIds,
  parseTags,
} from '@/utils/format'

/** 与实现一致地构造本地时间字符串，用于对比 UTC 解析行为。 */
function localString(utcIso: string): string {
  const date = new Date(utcIso)
  const pad = (part: number) => String(part).padStart(2, '0')
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    ` ${pad(date.getHours())}:${pad(date.getMinutes())}`
  )
}

describe('formatDateTime', () => {
  it('无时区标记的时间按 UTC 解析（后端约定）', () => {
    expect(formatDateTime('2026-10-01T00:00:00')).toBe(
      localString('2026-10-01T00:00:00Z'),
    )
  })

  it('带时区标记的时间按原时区解析', () => {
    expect(formatDateTime('2026-10-01T08:00:00+08:00')).toBe(
      localString('2026-10-01T08:00:00+08:00'),
    )
  })

  it('空值与非法值返回占位符', () => {
    expect(formatDateTime(null)).toBe('—')
    expect(formatDateTime(undefined)).toBe('—')
    expect(formatDateTime('')).toBe('—')
    expect(formatDateTime('不是时间')).toBe('—')
  })
})

describe('formatBytes', () => {
  it('按单位换算并保持精度', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(2048)).toBe('2.0 KB')
    expect(formatBytes(15 * 1024 * 1024)).toBe('15 MB')
  })

  it('空值返回占位符', () => {
    expect(formatBytes(null)).toBe('—')
  })
})

describe('formatUptime', () => {
  it('按天/小时/分钟分级展示', () => {
    expect(formatUptime(90)).toBe('1 分钟')
    expect(formatUptime(3 * 3600 + 25 * 60)).toBe('3 小时 25 分钟')
    expect(formatUptime(2 * 86400 + 3 * 3600)).toBe('2 天 3 小时')
  })
})

describe('parseMangaIds', () => {
  it('支持中英文逗号、句号、分号、换行与空格分隔', () => {
    expect(parseMangaIds('350234,422866.123\n456；789 321')).toEqual([
      '350234',
      '422866',
      '123',
      '456',
      '789',
      '321',
    ])
  })

  it('保持顺序并去重', () => {
    expect(parseMangaIds('100, 100，200')).toEqual(['100', '200'])
  })

  it('空输入返回空数组', () => {
    expect(parseMangaIds('  ')).toEqual([])
  })
})

describe('parseTags', () => {
  it('解析标签并去重', () => {
    expect(parseTags('恋爱，校园, 校园')).toEqual(['恋爱', '校园'])
  })
})
