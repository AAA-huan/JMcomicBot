/** 阅读器共享类型与常量。 */

/** 单页 / 连续滚动两种阅读模式。 */
export type ReaderMode = 'single' | 'continuous'

/** 适应宽度、适应页面或自定义百分比缩放。 */
export type ZoomMode = 'fit-width' | 'fit-page' | 'custom'

/** 连续模式渲染窗口半径：当前页前后各保留 1 页。 */
export const RENDER_WINDOW_RADIUS = 1

/** 缩放百分比档位（自定义缩放菜单使用）。 */
export const ZOOM_PERCENT_OPTIONS = [50, 75, 100, 125, 150, 200, 300]

/** 单个 Canvas 最长边的像素上限，避免移动端超大页面耗尽内存。 */
export const MAX_CANVAS_DIMENSION = 4096

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
