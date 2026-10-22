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
async function openReader(
  page: Page,
  options: { resetSettings?: boolean } = {},
): Promise<void> {
  // 每个用例默认从默认阅读设置开始，避免前一个用例的模式影响翻页方向。
  if (options.resetSettings !== false) await resetReaderSettings(page)
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

/** 通过 API 恢复默认阅读设置，避免用例之间的状态串扰。 */
async function resetReaderSettings(page: Page): Promise<void> {
  const cookies = await page.context().cookies()
  const csrf = cookies.find((cookie) => cookie.name === 'jmbot_csrf')?.value ?? ''
  const response = await page.request.put('/api/v1/reader/settings', {
    headers: { 'X-CSRF-Token': csrf },
    data: {
      reading_mode: 'normal',
      continuous: false,
      click_to_turn: false,
      reverse_click: false,
      dark_background: false,
    },
  })
  expect(response.ok()).toBe(true)
}

/** 打开抽屉/菜单后，点击其中文本匹配的列表项。 */
async function clickMenuItem(page: Page, text: string): Promise<void> {
  await page
    .locator('.v-overlay--active .v-list-item')
    .filter({ hasText: text })
    .first()
    .click()
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
    await clickMenuItem(page, '滚动模式')
    // 选择模式会关闭菜单，等待过场与 Vuetify 内部状态同步后再重新打开
    await expect(page.locator('.v-overlay--active')).toHaveCount(0)
    await page.waitForTimeout(400)
  } else {
    await page.getByRole('button', { name: '阅读模式' }).click()
    await clickMenuItem(page, '滚动模式')
  }
  // 连续翻页在桌面与移动端的设置菜单中均可切换
  await page.getByRole('button', { name: '阅读设置' }).click()
  await expect(page.locator('.v-overlay--active')).toBeVisible()
  await page.waitForTimeout(300)
  const continuousResponse = page.waitForResponse(
    (response) =>
      response.url().includes('/reader/settings') &&
      response.request().method() === 'PUT',
  )
  await page
    .locator('.v-overlay--active')
    .getByText('连续翻页', { exact: true })
    .click()
  await continuousResponse
  await page.keyboard.press('Escape')
  await expect(page.locator('.reader-pages')).toBeVisible()

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

test('设置页保存的阅读偏好会在阅读器生效，工具栏修改后回写并重启保持', async ({ page }, testInfo) => {
  await login(page)
  await resetReaderSettings(page)
  const isMobile = testInfo.project.name.startsWith('mobile')

  // 1. 在设置页改为日漫 + 连续 + 点击 + 反转 + 深色
  await page.goto('/settings')
  await expect(page.getByText('阅读偏好', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '日漫模式', exact: true }).click()
  await page.getByText('连续翻页', { exact: true }).click()
  await page.getByText('点击翻页', { exact: true }).click()
  await page.getByText('反转点击翻页', { exact: true }).click()
  await page.getByText('深色背景', { exact: true }).click()
  const saveResponse = page.waitForResponse(
    (response) =>
      response.url().includes('/reader/settings') &&
      response.request().method() === 'PUT',
  )
  await page.getByRole('button', { name: '保存阅读偏好' }).click()
  await saveResponse
  await expect(page.getByText(/阅读偏好已保存/)).toBeVisible()

  // 2. 进入阅读器，五项设置全部生效
  await page.goto('/library/900001')
  await page.getByRole('button', { name: /阅读/ }).first().click()
  await expect(page).toHaveURL(/\/reader\/\d+/)
  await expect(page.locator('canvas').first()).toBeVisible()
  await expect(page.locator('.reader-root--dark')).toBeVisible()
  await expect(page.locator('.reader-pages--horizontal.reader-pages--reverse')).toBeVisible()
  await expect(page.locator('.reader-pages')).toHaveAttribute(
    'style',
    /--reader-page-gap: 4px/,
  )
  if (isMobile) {
    await page.getByRole('button', { name: '阅读设置' }).click()
    await expect(
      page.locator('.v-overlay--active .v-list-item--active').filter({
        hasText: '日漫模式',
      }),
    ).toBeVisible()
  } else {
    await expect(page.getByRole('button', { name: '阅读模式' })).toContainText(
      '日漫模式',
    )
  }

  // 3. 在工具栏改回普通模式并关闭深色背景，等待两次持久化完成
  const modeResponse = page.waitForResponse(
    (response) =>
      response.url().includes('/reader/settings') &&
      response.request().method() === 'PUT',
  )
  if (isMobile) {
    await clickMenuItem(page, '普通模式')
  } else {
    await page.getByRole('button', { name: '阅读模式' }).click()
    await clickMenuItem(page, '普通模式')
  }
  await modeResponse
  if (!isMobile) {
    await expect(page.getByRole('button', { name: '阅读模式' })).toContainText(
      '普通模式',
    )
  }
  // 移动端选择模式会关闭菜单，等待过场结束再打开阅读设置
  await expect(page.locator('.v-overlay--active')).toHaveCount(0)

  await page.getByRole('button', { name: '阅读设置' }).click()
  const darkResponse = page.waitForResponse(
    (response) =>
      response.url().includes('/reader/settings') &&
      response.request().method() === 'PUT',
  )
  await page
    .locator('.v-overlay--active')
    .getByText('深色背景', { exact: true })
    .click()
  await darkResponse
  await page.keyboard.press('Escape')
  await expect(page.locator('.reader-root--dark')).toHaveCount(0)

  // 4. 设置页同步工具栏改动，刷新后仍保持
  await page.goto('/settings')
  await expect(page.getByText('左→右阅读')).toBeVisible()
  await expect(page.getByLabel('深色背景')).not.toBeChecked()
  await page.reload()
  await expect(page.getByText('左→右阅读')).toBeVisible()
  await expect(page.getByLabel('深色背景')).not.toBeChecked()

  // 5. 再次进入阅读器确认重启/刷新后仍为普通模式与浅色背景
  await page.goto('/library/900001')
  await page.getByRole('button', { name: /阅读/ }).first().click()
  await expect(page).toHaveURL(/\/reader\/\d+/)
  await expect(page.locator('canvas').first()).toBeVisible()
  await expect(page.locator('.reader-root--dark')).toHaveCount(0)
  await expect(page.locator('.reader-pages--horizontal')).toBeVisible()
  await expect(page.locator('.reader-pages--reverse')).toHaveCount(0)

  await resetReaderSettings(page)
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
      clientX: 60,
      clientY: 240,
    })
    const endTouch = new Touch({
      identifier: 2,
      target: element,
      clientX: 300,
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
