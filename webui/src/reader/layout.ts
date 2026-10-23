/**
 * 连排页面布局计算：只依赖页面尺寸与缩放结果，不读取 DOM。
 *
 * offsets 沿滚动方向从内容起始边缘累加（普通模式为左/上，日漫模式为右），
 * 包含首尾内边距与页间距。滚动事件据此二分查找当前页，避免逐页
 * getBoundingClientRect 造成的强制重排。
 */

import type { PageBaseSize } from './types'

export interface PageLayout {
  /** 每页沿滚动方向的起始偏移。 */
  offsets: number[]
  /** 每页沿滚动方向的主轴长度。 */
  lengths: number[]
  /** 含首尾内边距与页间距的总内容长度。 */
  contentLength: number
  /** 页间距，同时作为容器首尾内边距。 */
  gap: number
}

/** 根据完整页面尺寸数组构造连排布局。 */
export function buildPageLayout(
  sizes: PageBaseSize[],
  horizontal: boolean,
  gap: number,
): PageLayout {
  const lengths = sizes.map((size) => (horizontal ? size.width : size.height))
  const offsets: number[] = []
  let cursor = gap
  for (const length of lengths) {
    offsets.push(cursor)
    cursor += length + gap
  }
  return { offsets, lengths, contentLength: cursor, gap }
}

/**
 * 二分查找指定滚动位置命中的页面索引。
 *
 * position 为沿滚动方向、从内容起始边缘算起的坐标。落在页间距时选择
 * 与视口中心更近的一页；空布局返回 -1。
 */
export function findPageIndexAt(layout: PageLayout, position: number): number {
  const { offsets, lengths } = layout
  if (offsets.length === 0) return -1
  if (position <= offsets[0]) return 0

  let low = 0
  let high = offsets.length - 1
  let found = 0
  while (low <= high) {
    const middle = Math.floor((low + high) / 2)
    if (offsets[middle] <= position) {
      found = middle
      low = middle + 1
    } else {
      high = middle - 1
    }
  }

  if (found < offsets.length - 1) {
    const currentEnd = offsets[found] + lengths[found]
    if (position >= currentEnd) {
      const currentCenter = offsets[found] + lengths[found] / 2
      const nextCenter = offsets[found + 1] + lengths[found + 1] / 2
      if (Math.abs(position - nextCenter) < Math.abs(position - currentCenter)) {
        return found + 1
      }
    }
  }
  return found
}

/** 把滚动位置换算为沿内容方向的坐标；日漫横排从右往左镜像。 */
export function positionAlongContent(
  layout: PageLayout,
  scrollOffset: number,
  viewportLength: number,
  manga: boolean,
): number {
  const center = scrollOffset + viewportLength / 2
  return manga ? layout.contentLength - center : center
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum)
}

/**
 * 计算目标页的滚动位置。
 *
 * center=true 用于横排居中；false 用于纵排顶部对齐（保留原有阅读习惯）。
 * 日漫模式从右侧边缘反算 scrollLeft。
 */
export function scrollPositionForPage(
  layout: PageLayout,
  index: number,
  viewportLength: number,
  manga: boolean,
  center: boolean,
): number {
  const offset = layout.offsets[index]
  const length = layout.lengths[index]
  if (offset === undefined || length === undefined) return 0
  const maxScroll = Math.max(layout.contentLength - viewportLength, 0)
  if (!center) return clamp(offset - layout.gap, 0, maxScroll)
  const pageCenter = manga
    ? layout.contentLength - offset - length / 2
    : offset + length / 2
  return clamp(pageCenter - viewportLength / 2, 0, maxScroll)
}
