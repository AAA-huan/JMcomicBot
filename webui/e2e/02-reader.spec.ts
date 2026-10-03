import { expect, test, type Page } from '@playwright/test'

import { E2E_PASSWORD } from './helpers'

/** 使用管理员密码登录并等待仪表盘出现。 */
async function login(page: Page): Promise<void> {
  await page.goto('/login')
  await page.locator('input[autocomplete="current-password"]').fill(E2E_PASSWORD)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByText('机器人版本')).toBeVisible()
}

/** 打开 900001 详情页并进入阅读器，等待第一页 Canvas 渲染出尺寸。 */
async function openReader(page: Page): Promise<void> {
  await page.goto('/library/900001')
  const readButton = page.getByRole('button', { name: /阅读/ }).first()
  await expect(readButton).toBeVisible()
  await readButton.click()
  await expect(page).toHaveURL(/\/reader\/\d+/)
  await expect(page.locator('canvas').first()).toBeVisible()
  await expect
    .poll(
      () =>
        page
          .locator('canvas')
          .first()
          .evaluate((canvas) => (canvas as HTMLCanvasElement).width),
      { timeout: 15_000 },
    )
    .toBeGreaterThan(0)
}

/** 读取工具栏页码输入框的当前值。 */
async function currentPage(page: Page): Promise<number> {
  const value = await page.getByRole('textbox', { name: '跳转页码' }).inputValue()
  return Number.parseInt(value, 10)
}

test.describe.configure({ mode: 'serial' })

test('缺少新 JavaScript API 的手机浏览器仍能加载并再次进入阅读器', async ({ page }) => {
  // 视口模拟不会改变浏览器 API；主线程与 Worker 都需要模拟旧版内核。
  await page.addInitScript(() => {
    Reflect.deleteProperty(Promise, 'withResolvers')
    Reflect.deleteProperty(Map.prototype, 'getOrInsertComputed')
    // 用独立入口先删除 Worker 环境中的 API，再加载实际打包的解析器。
    // 浏览器自动化中的请求拦截并不总能覆盖 Worker 的初始脚本请求。
    const NativeWorker = window.Worker
    window.Worker = class extends NativeWorker {
      constructor(url: string | URL, options?: WorkerOptions) {
        const source = `Reflect.deleteProperty(Promise, 'withResolvers');
Reflect.deleteProperty(Map.prototype, 'getOrInsertComputed');
await import(${JSON.stringify(new URL(url, window.location.href).href)});`
        super(URL.createObjectURL(new Blob([source], { type: 'text/javascript' })), options)
      }
    }
  })

  await login(page)
  await openReader(page)
  await page.getByRole('button', { name: '返回' }).click()
  await expect(page).toHaveURL(/\/library\/900001/)
  await openReader(page)
  await expect(page.getByText('PDF 加载失败，请重试')).toBeHidden()
})

test('从详情页进入阅读器并渲染 PDF 页面', async ({ page }) => {
  await login(page)
  await openReader(page)

  // 工具栏页码应在有效范围内，且存在「下载 PDF」入口
  const pageNumber = await currentPage(page)
  expect(pageNumber).toBeGreaterThanOrEqual(1)

  // 翻到下一页验证渲染切换（页码从 1 起，最后一页除外）
  const canvas = page.locator('canvas').first()
  await page.keyboard.press('ArrowRight')
  await expect.poll(() => currentPage(page)).toBe(pageNumber + 1)
  await expect
    .poll(() => canvas.evaluate((el) => (el as HTMLCanvasElement).width))
    .toBeGreaterThan(0)
})

test('翻页后刷新页面恢复阅读进度', async ({ page }) => {
  await login(page)
  await openReader(page)

  const before = await currentPage(page)
  const putResponse = page.waitForResponse(
    (response) =>
      response.url().includes('/progress') &&
      response.request().method() === 'PUT',
  )
  await page.keyboard.press('ArrowRight')
  await putResponse
  const after = await currentPage(page)
  expect(after).toBe(before + 1)

  // 刷新后应从服务端恢复到新页码
  await page.reload()
  await expect(page.locator('canvas').first()).toBeVisible()
  await expect.poll(() => currentPage(page), { timeout: 15_000 }).toBe(after)
})

test('连续滚动模式可用且不横向滚动、渲染窗口受限', async ({ page }, testInfo) => {
  await login(page)
  await openReader(page)
  const isMobile = testInfo.project.name.startsWith('mobile')

  if (isMobile) {
    await page.getByRole('button', { name: '阅读设置' }).click()
    await page.getByText('连续滚动', { exact: true }).click()
  } else {
    await page.getByRole('button', { name: '切换到连续滚动' }).click()
  }

  // 连续模式至少渲染当前页，且不超过 ±1 窗口
  await expect.poll(() => page.locator('.reader-scroll canvas').count()).toBeGreaterThan(0)
  const canvasCount = await page.locator('.reader-scroll canvas').count()
  expect(canvasCount).toBeLessThanOrEqual(3)

  // 滚动到中段，页码应前进且不发生整页横向滚动
  await page.locator('.reader-scroll').evaluate((element) => {
    element.scrollTop = element.scrollHeight * 0.6
  })
  await expect.poll(() => currentPage(page), { timeout: 10_000 }).toBeGreaterThan(1)

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
})

test('损坏 PDF 显示明确的中文错误界面', async ({ page }) => {
  await login(page)
  await page.goto('/library/900004')
  const readButton = page.getByRole('button', { name: /阅读/ }).first()
  await expect(readButton).toBeVisible()
  await readButton.click()
  await expect(page).toHaveURL(/\/reader\/\d+/)

  await expect(page.getByText('PDF 文件已损坏或格式不完整')).toBeVisible({
    timeout: 15_000,
  })
  await expect(page.getByRole('button', { name: '重试' })).toBeVisible()
  await expect(page.getByRole('link', { name: /下载 PDF/ })).toBeVisible()
})

test('移动端单页模式左右滑动翻页', async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith('mobile'), '仅移动视口验证触摸滑动')
  await login(page)
  await openReader(page)
  const before = await currentPage(page)

  await page.locator('.reader-scroll').evaluate((element) => {
    const startTouch = new Touch({
      identifier: 1,
      target: element,
      clientX: 300,
      clientY: 240,
    })
    const endTouch = new Touch({
      identifier: 2,
      target: element,
      clientX: 60,
      clientY: 245,
    })
    element.dispatchEvent(
      new TouchEvent('touchstart', {
        touches: [startTouch],
        changedTouches: [startTouch],
        bubbles: true,
      }),
    )
    element.dispatchEvent(
      new TouchEvent('touchend', {
        touches: [],
        changedTouches: [endTouch],
        bubbles: true,
      }),
    )
  })

  await expect.poll(() => currentPage(page)).toBe(before + 1)
})

test('退出阅读器后再次进入仍能正常加载', async ({ page }) => {
  await login(page)
  await openReader(page)

  // 返回详情页会销毁上一个 PDF 与它的 Worker
  await page.getByRole('button', { name: '返回' }).click()
  await expect(page).toHaveURL(/\/library\/900001/)

  // 再次进入：Worker 生命周期重生，必须仍能渲染而不是停在加载/错误界面
  const readButton = page.getByRole('button', { name: /阅读/ }).first()
  await expect(readButton).toBeVisible()
  await readButton.click()
  await expect(page).toHaveURL(/\/reader\/\d+/)
  const canvas = page.locator('canvas').first()
  await expect(canvas).toBeVisible()
  await expect
    .poll(() => canvas.evaluate((el) => (el as HTMLCanvasElement).width), {
      timeout: 15_000,
    })
    .toBeGreaterThan(0)
  await expect(page.getByText('PDF 加载失败，请重试')).toBeHidden()
})

test('Worker 不可用时回退主线程仍能渲染', async ({ page }) => {
  // 模拟无法创建 Web Worker 的浏览器，让 PDF.js 实际进入主线程解析路径。
  await page.addInitScript(() => {
    Object.defineProperty(window, 'Worker', {
      value: class {
        constructor() {
          throw new Error('测试：浏览器无法创建 Worker')
        }
      },
    })
  })

  await login(page)
  await page.goto('/library/900001')
  await page.getByRole('button', { name: /阅读/ }).first().click()
  await expect(page).toHaveURL(/\/reader\/\d+/)

  const canvas = page.locator('canvas').first()
  await expect(canvas).toBeVisible({ timeout: 20_000 })
  await expect
    .poll(() => canvas.evaluate((el) => (el as HTMLCanvasElement).width), {
      timeout: 20_000,
    })
    .toBeGreaterThan(0)
  await expect(page.getByText('PDF 加载失败，请重试')).toBeHidden()
})
