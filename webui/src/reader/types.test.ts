/** 阅读器页码窗口与缩放计算。 */

import { describe, expect, it } from 'vitest'

import { computeFitScale, windowPagesFor } from './types'

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
