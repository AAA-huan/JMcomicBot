/** 阅读器页码窗口与缩放计算。 */

import { describe, expect, it } from 'vitest'

import {
  clickTurnDelta,
  computeFitScale,
  isHorizontalScroll,
  keyTurnDelta,
  pageGap,
  swipeTurnDelta,
  windowPagesFor,
} from './types'

describe('windowPagesFor', () => {
  it('中间页返回当前页 ±1', () => {
    expect(windowPagesFor(5, 10)).toEqual([4, 5, 6])
  })

  it('首尾页自动裁剪越界页码', () => {
    expect(windowPagesFor(1, 10)).toEqual([1, 2])
    expect(windowPagesFor(10, 10)).toEqual([9, 10])
  })

  it('单页文档只有一页', () => {
    expect(windowPagesFor(1, 1)).toEqual([1])
  })
})

describe('computeFitScale', () => {
  const base = { width: 600, height: 800 }

  it('适应宽度只受容器宽度限制', () => {
    expect(computeFitScale(base, 300, 100, 'fit-width')).toBeCloseTo(0.5)
  })

  it('适应页面取宽度与高度倍率的较小值', () => {
    // 高度容纳不下：400/800 = 0.5 小于 600/600 = 1
    expect(computeFitScale(base, 600, 400, 'fit-page')).toBeCloseTo(0.5)
    // 宽度容纳不下：300/600 = 0.5 小于 900/800
    expect(computeFitScale(base, 300, 900, 'fit-page')).toBeCloseTo(0.5)
  })
})

describe('isHorizontalScroll', () => {
  it('普通与日漫横排，滚动模式纵排', () => {
    expect(isHorizontalScroll('normal')).toBe(true)
    expect(isHorizontalScroll('manga')).toBe(true)
    expect(isHorizontalScroll('scroll')).toBe(false)
  })
})

describe('pageGap', () => {
  it('仅连续模式使用 4px 页间距', () => {
    expect(pageGap(true)).toBe(4)
    expect(pageGap(false)).toBe(0)
  })
})

describe('swipeTurnDelta', () => {
  it('普通模式左滑下一页、右滑上一页', () => {
    expect(swipeTurnDelta('normal', -100, 0)).toBe(1)
    expect(swipeTurnDelta('normal', 100, 0)).toBe(-1)
  })

  it('日漫模式右滑下一页、左滑上一页', () => {
    expect(swipeTurnDelta('manga', 100, 0)).toBe(1)
    expect(swipeTurnDelta('manga', -100, 0)).toBe(-1)
  })

  it('滚动模式下滑下一页、上滑上一页', () => {
    expect(swipeTurnDelta('scroll', 0, 100)).toBe(1)
    expect(swipeTurnDelta('scroll', 0, -100)).toBe(-1)
  })

  it('位移不足或方向不占主导时不翻页', () => {
    expect(swipeTurnDelta('normal', 30, 0)).toBe(0)
    expect(swipeTurnDelta('normal', 100, 80)).toBe(0)
    expect(swipeTurnDelta('manga', -40, 0)).toBe(0)
    expect(swipeTurnDelta('scroll', 0, 50)).toBe(0)
    expect(swipeTurnDelta('scroll', 100, 80)).toBe(0)
  })
})

describe('keyTurnDelta', () => {
  it('普通模式使用左右方向键', () => {
    expect(keyTurnDelta('normal', 'ArrowRight')).toBe(1)
    expect(keyTurnDelta('normal', 'ArrowLeft')).toBe(-1)
    expect(keyTurnDelta('normal', 'ArrowDown')).toBe(0)
  })

  it('日漫模式左右方向键与普通模式相反', () => {
    expect(keyTurnDelta('manga', 'ArrowLeft')).toBe(1)
    expect(keyTurnDelta('manga', 'ArrowRight')).toBe(-1)
    expect(keyTurnDelta('manga', 'ArrowUp')).toBe(0)
  })

  it('滚动模式使用上下方向键', () => {
    expect(keyTurnDelta('scroll', 'ArrowDown')).toBe(1)
    expect(keyTurnDelta('scroll', 'ArrowUp')).toBe(-1)
    expect(keyTurnDelta('scroll', 'ArrowLeft')).toBe(0)
  })
})

describe('clickTurnDelta', () => {
  it('普通模式左区上一页、右区下一页、中间不响应', () => {
    expect(clickTurnDelta('normal', 0.1, false)).toBe(-1)
    expect(clickTurnDelta('normal', 0.9, false)).toBe(1)
    expect(clickTurnDelta('normal', 0.5, false)).toBe(0)
    expect(clickTurnDelta('normal', 0.45, false)).toBe(0)
    expect(clickTurnDelta('normal', 0.55, false)).toBe(0)
  })

  it('日漫模式左右区域方向相反', () => {
    expect(clickTurnDelta('manga', 0.1, false)).toBe(1)
    expect(clickTurnDelta('manga', 0.9, false)).toBe(-1)
  })

  it('反转只翻转点击翻页方向', () => {
    expect(clickTurnDelta('normal', 0.1, true)).toBe(1)
    expect(clickTurnDelta('normal', 0.9, true)).toBe(-1)
    // 日漫 + 反转抵消为普通方向
    expect(clickTurnDelta('manga', 0.1, true)).toBe(-1)
    expect(clickTurnDelta('manga', 0.9, true)).toBe(1)
    expect(clickTurnDelta('normal', 0.5, true)).toBe(0)
  })
})
