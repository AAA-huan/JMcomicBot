/** 阅读器共享类型与常量。 */

/** 翻页方向模式：普通（左→右）、日漫（右→左）、滚动（上→下）。 */
export type ReaderMode = 'normal' | 'manga' | 'scroll'

/** 翻页方向：-1 上一页，0 不翻页，1 下一页。 */
export type TurnDelta = -1 | 0 | 1

/** 适应宽度、适应页面或自定义百分比缩放。 */
export type ZoomMode = 'fit-width' | 'fit-page' | 'custom'

/** 连续模式渲染窗口半径：当前页前后各保留 1 页。 */
export const RENDER_WINDOW_RADIUS = 1

/** 缩放百分比档位（自定义缩放菜单使用）。 */
export const ZOOM_PERCENT_OPTIONS = [50, 75, 100, 125, 150, 200, 300]

/** 单个 Canvas 最长边的像素上限，避免移动端超大页面耗尽内存。 */
export const MAX_CANVAS_DIMENSION = 4096

/** 滑动翻页的最小位移阈值（像素）。 */
export const SWIPE_THRESHOLD = 60

/** 点击翻页左右热区占比，中间 10% 不响应。 */
export const CLICK_ZONE_RATIO = 0.45

/** 阅读器后端设置；未保存时由后端返回默认值。 */
export interface ReadingSettings {
  reading_mode: ReaderMode
  continuous: boolean
  click_to_turn: boolean
  reverse_click: boolean
  dark_background: boolean
  updated_at: string | null
}

/** 阅读设置更新请求，只传需要修改的字段。 */
export interface ReadingSettingUpdate {
  reading_mode?: ReaderMode
  continuous?: boolean
  click_to_turn?: boolean
  reverse_click?: boolean
  dark_background?: boolean
}

/** 普通/日漫模式使用水平轴向，滚动模式使用垂直轴向。 */
export function isHorizontalScroll(mode: ReaderMode): boolean {
  return mode !== 'scroll'
}

/** 连续连排时的页间距；不连续模式没有页间距。 */
export function pageGap(continuous: boolean): number {
  return continuous ? 4 : 0
}

/** 根据模式与滑动位移计算翻页方向，主方向位移不足时返回 0。 */
export function swipeTurnDelta(
  mode: ReaderMode,
  deltaX: number,
  deltaY: number,
): TurnDelta {
  if (mode === 'scroll') {
    if (
      Math.abs(deltaY) < SWIPE_THRESHOLD ||
      Math.abs(deltaY) < Math.abs(deltaX) * 1.5
    ) {
      return 0
    }
    return deltaY > 0 ? 1 : -1
  }
  if (
    Math.abs(deltaX) < SWIPE_THRESHOLD ||
    Math.abs(deltaX) < Math.abs(deltaY) * 1.5
  ) {
    return 0
  }
  if (mode === 'manga') return deltaX < 0 ? 1 : -1
  return deltaX > 0 ? 1 : -1
}

/** 根据模式把键盘方向键映射为翻页方向。 */
export function keyTurnDelta(mode: ReaderMode, key: string): TurnDelta {
  if (mode === 'scroll') {
    if (key === 'ArrowDown') return 1
    if (key === 'ArrowUp') return -1
    return 0
  }
  if (mode === 'manga') {
    if (key === 'ArrowLeft') return 1
    if (key === 'ArrowRight') return -1
    return 0
  }
  if (key === 'ArrowRight') return 1
  if (key === 'ArrowLeft') return -1
  return 0
}

/** 根据点击横向比例计算翻页方向；反转只影响点击翻页。 */
export function clickTurnDelta(
  mode: ReaderMode,
  ratio: number,
  reverse: boolean,
): TurnDelta {
  let delta: TurnDelta = 0
  if (ratio < CLICK_ZONE_RATIO) {
    delta = mode === 'manga' ? 1 : -1
  } else if (ratio > 1 - CLICK_ZONE_RATIO) {
    delta = mode === 'manga' ? -1 : 1
  }
  if (delta === 0 || !reverse) return delta
  return delta === 1 ? -1 : 1
}

/** 计算连续模式的渲染窗口页码（含边界裁剪）。 */
export function windowPagesFor(
  current: number,
  total: number,
  radius: number = RENDER_WINDOW_RADIUS,
): number[] {
  const pages: number[] = []
  for (let page = current - radius; page <= current + radius; page += 1) {
    if (page >= 1 && page <= total) pages.push(page)
  }
  return pages
}

export interface PageBaseSize {
  width: number
  height: number
}

/**
 * 计算目标缩放倍率。
 *
 * base 为页面在 scale=1 时的尺寸；availableWidth/Height 为阅读区可用
 * 尺寸（已扣除内边距）。fit-page 同时受宽高限制，custom 由调用方处理。
 */
export function computeFitScale(
  base: PageBaseSize,
  availableWidth: number,
  availableHeight: number,
  mode: Exclude<ZoomMode, 'custom'>,
): number {
  const widthScale = availableWidth / base.width
  if (mode === 'fit-width') return widthScale
  return Math.min(widthScale, availableHeight / base.height)
}
