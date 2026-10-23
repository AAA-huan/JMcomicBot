/** 连排布局与 offset 二分查找。 */

import { describe, expect, it } from 'vitest'

import {
  buildPageLayout,
  findPageIndexAt,
  positionAlongContent,
  scrollPositionForPage,
} from './layout'

const SIZES = [
  { width: 100, height: 200 },
  { width: 200, height: 300 },
  { width: 300, height: 400 },
]

describe('buildPageLayout', () => {
  it('按页尺寸与间距累加偏移，包含首尾内边距', () => {
    const layout = buildPageLayout(SIZES, true, 4)
    expect(layout.offsets).toEqual([4, 108, 312])
    expect(layout.lengths).toEqual([100, 200, 300])
    // 4 + (100+4) + (200+4) + (300+4)
    expect(layout.contentLength).toBe(616)
  })

  it('纵排使用高度作为主轴长度', () => {
    const layout = buildPageLayout(SIZES, false, 4)
    expect(layout.lengths).toEqual([200, 300, 400])
    expect(layout.offsets).toEqual([4, 208, 512])
  })
})

describe('findPageIndexAt', () => {
  const layout = buildPageLayout(SIZES, true, 4)

  it('二分命中页面区间与边界', () => {
    expect(findPageIndexAt(layout, 0)).toBe(0)
    expect(findPageIndexAt(layout, 50)).toBe(0)
    expect(findPageIndexAt(layout, 104)).toBe(0)
    expect(findPageIndexAt(layout, 108)).toBe(1)
    expect(findPageIndexAt(layout, 350)).toBe(2)
    expect(findPageIndexAt(layout, 700)).toBe(2)
  })

  it('落在页间距时选择中心更近的一页', () => {
    // 第 1 页中心 54，第 2 页中心 208，分界约 131
    expect(findPageIndexAt(layout, 106)).toBe(0)
    expect(findPageIndexAt(layout, 157)).toBe(1)
  })

  it('空布局返回 -1', () => {
    expect(findPageIndexAt(buildPageLayout([], true, 4), 10)).toBe(-1)
  })
})

describe('positionAlongContent 与 scrollPositionForPage', () => {
  const layout = buildPageLayout(SIZES, true, 4)

  it('普通模式从左侧累加，日漫模式从右侧镜像', () => {
    expect(positionAlongContent(layout, 100, 200, false)).toBe(200)
    // 日漫：内容长 616，scrollLeft=0 时视口中心距右边缘 616 - 100 = 516
    expect(positionAlongContent(layout, 0, 200, true)).toBe(516)
  })

  it('普通模式横向居中的滚动位置并夹紧到 0', () => {
    expect(scrollPositionForPage(layout, 0, 200, false, true)).toBe(0)
    expect(scrollPositionForPage(layout, 1, 200, false, true)).toBe(108)
  })

  it('日漫模式从右边缘反算滚动位置', () => {
    // 第 1 页中心距右 562，滚动位置 462 超过最大滚动量 416，夹紧为 416
    expect(scrollPositionForPage(layout, 0, 200, true, true)).toBe(416)
    // 第 3 页中心距右 154：154 - 100 = 54
    expect(scrollPositionForPage(layout, 2, 200, true, true)).toBe(54)
  })

  it('纵排顶部对齐时减去页间距', () => {
    const vertical = buildPageLayout(SIZES, false, 4)
    expect(scrollPositionForPage(vertical, 1, 300, false, false)).toBe(204)
  })
})
