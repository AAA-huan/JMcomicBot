import { expect, test, type Page } from '@playwright/test'

import { E2E_PASSWORD } from './helpers'

async function login(page: Page, password = E2E_PASSWORD): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('管理员密码', { exact: true }).fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByText('机器人版本')).toBeVisible()
}

test('手动校验保存任务与审计，审计筛选刷新后保留', async ({ page }) => {
  await login(page)
  await page.goto('/maintenance')
  await page.getByRole('textbox', { name: '待校验漫画 ID' }).fill('900001')
  await page.getByRole('button', { name: '开始校验', exact: true }).click()
  await expect(page.getByText(/校验完成：1 个文件，就绪 1/)).toBeVisible()
  await page.getByRole('link', { name: '查看校验任务' }).click()
  await expect(page).toHaveURL(/\/tasks\?task_type=verify/)
  await expect(page.getByText('校验漫画文件').first()).toBeVisible()

  await page.goto('/audit')
  await page.getByRole('textbox', { name: '事件类型（精确匹配）' }).fill('library.verify_completed')
  await page.getByRole('button', { name: '筛选', exact: true }).click()
  await expect(page).toHaveURL(/\/audit\?event_type=library.verify_completed/)
  await expect(page.getByText('library.verify_completed', { exact: true }).first()).toBeVisible()
  await page.reload()
  await expect(page.getByRole('textbox', { name: '事件类型（精确匹配）' })).toHaveValue('library.verify_completed')
  await expect(page.getByText('library.verify_completed', { exact: true }).first()).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0)
})

test('大 PDF 停留首页时只读取部分数据并按 Range 翻页', async ({ page }) => {
  await login(page)
  await page.goto('/library/900007')
  const ranges: Array<{ start: number; end: number }> = []
  page.on('request', (request) => {
    if (!request.url().includes('/content')) return
    const match = /^bytes=(\d+)-(\d+)$/.exec(request.headers().range ?? '')
    if (match) ranges.push({ start: Number(match[1]), end: Number(match[2]) })
  })
  await page.getByRole('button', { name: /阅读/ }).first().click()
  const canvas = page.locator('canvas').first()
  await expect(canvas).toBeVisible()
  await expect.poll(() => canvas.evaluate((el) => (el as HTMLCanvasElement).width)).toBeGreaterThan(0)
  // 给自动预取足够时间触发；本用例关注网络数据，而非 Canvas 数量。
  await page.waitForTimeout(1500)
  expect(ranges.length).toBeGreaterThan(0)
  const initialBytes = ranges.reduce((total, range) => total + range.end - range.start + 1, 0)
  expect(initialBytes).toBeLessThan(3 * 1024 * 1024)
  const initialCount = ranges.length
  const pageInput = page.getByRole('textbox', { name: '跳转页码' })
  await pageInput.fill('10')
  await pageInput.press('Enter')
  await expect.poll(() => ranges.length).toBeGreaterThan(initialCount)
  await expect(pageInput).toHaveValue('10')
  await expect.poll(() => canvas.evaluate((el) => (el as HTMLCanvasElement).width)).toBeGreaterThan(0)
})

test('账户菜单修改密码使旧会话失效并使用新密码重新登录', async ({ page }) => {
  const newPassword = 'e2e-changed-password-654321'
  await login(page)
  await page.getByRole('button', { name: '账户菜单' }).click()
  await page.getByText('修改密码', { exact: true }).click()
  await expect(page).toHaveURL(/\/password$/)
  await page.getByLabel('旧密码', { exact: true }).fill('wrong-password')
  await page.getByLabel('新密码', { exact: true }).fill(newPassword)
  await page.getByLabel('确认新密码', { exact: true }).fill(newPassword)
  await page.getByRole('button', { name: '修改密码', exact: true }).click()
  await expect(page.getByText('原管理员密码错误')).toBeVisible()
  await page.getByLabel('旧密码', { exact: true }).fill(E2E_PASSWORD)
  await page.getByRole('button', { name: '修改密码', exact: true }).click()
  await expect(page).toHaveURL(/\/login\?password_changed=1/)
  await expect(page.getByText('密码已修改，请使用新密码重新登录。')).toBeVisible()
  expect((await page.request.get('/api/v1/system/status')).status()).toBe(401)
  // 恢复测试密码供另一个视口使用；成功改密后即使断言失败也尝试恢复。
  try {
    await login(page, newPassword)
    await page.goto('/password')
    await expect(page.getByText('修改管理员密码', { exact: true })).toBeVisible()
  } finally {
    await page.request.post('/api/v1/auth/login', { data: { password: newPassword } })
    const cookies = await page.context().cookies()
    const csrf = cookies.find((cookie) => cookie.name === 'jmbot_csrf')?.value
    const restored = await page.request.put('/api/v1/auth/password', {
      headers: { 'X-CSRF-Token': csrf ?? '' },
      data: { old_password: newPassword, new_password: E2E_PASSWORD },
    })
    expect(restored.ok()).toBe(true)
  }
  await login(page)
})
