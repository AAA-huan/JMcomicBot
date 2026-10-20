import { expect, test, type Page } from '@playwright/test'

import { E2E_PASSWORD } from './helpers'

async function login(page: Page): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('管理员密码', { exact: true }).fill(E2E_PASSWORD)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByText('机器人版本')).toBeVisible()
}

test('漫画下载页空态与已有任务提示（不触发真实下载）', async ({ page }) => {
  await login(page)
  await page.goto('/download')
  await expect(page.getByText('当前没有正在下载的漫画')).toBeVisible()

  // smoke 数据中的 900004 已中断，启动时不会自动续传；这里仅拦截请求验证重复任务提示
  await page.route('**/api/v1/tasks/downloads', async (route) => {
    if (route.request().method() !== 'POST') {
      await route.continue()
      return
    }
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [{ manga_id: '900004', status: 'duplicate', task_id: 'task-900004' }],
        queued_count: 0,
        duplicate_count: 1,
      }),
    })
  })

  const input = page.locator('textarea').first()
  await input.fill('900004')
  await page.getByRole('button', { name: '请求下载', exact: true }).click()

  await expect(page.getByText(/已入队 0 个/)).toBeVisible()
  await expect(page.getByText(/1 个已有活动任务（900004）/)).toBeVisible()
  await expect(input).toHaveValue('')
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth),
  ).toBeLessThanOrEqual(1)
})
