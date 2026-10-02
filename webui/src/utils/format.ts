/** 展示格式化工具：时间（后端为无时区 UTC）、大小、运行时长与下载 ID 解析。 */

/** 后端时间为无时区的 UTC 语义，缺失时区标记时按 UTC 解析。 */
function parseBackendTime(value: string): Date {
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value)
  return new Date(hasTimezone ? value : `${value}Z`)
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = parseBackendTime(value)
  if (Number.isNaN(date.getTime())) return '—'
  const pad = (part: number) => String(part).padStart(2, '0')
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    ` ${pad(date.getHours())}:${pad(date.getMinutes())}`
  )
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return '—'
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let value = bytes / 1024
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[index]}`
}

export function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (days > 0) return `${days} 天 ${hours} 小时`
  if (hours > 0) return `${hours} 小时 ${minutes} 分钟`
  return `${minutes} 分钟`
}

/** 解析逗号、句号、换行或空格分隔的漫画 ID 列表，保持顺序去重。 */
export function parseMangaIds(raw: string): string[] {
  const seen = new Set<string>()
  const result: string[] = []
  for (const part of raw.split(/[,，.。;；\s]+/)) {
    const value = part.trim()
    if (!value || seen.has(value)) continue
    seen.add(value)
    result.push(value)
  }
  return result
}

/** 解析逗号或换行分隔的标签列表，保持顺序去重。 */
export function parseTags(raw: string): string[] {
  return parseMangaIds(raw)
}
