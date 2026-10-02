import { expect, test } from '@playwright/test'

import { E2E_PASSWORD } from './helpers'

test.describe.configure({ mode: 'serial' })

test('首次设置管理员并自动进入仪表盘', async ({ page, request }) => {
  const status = await request.get('/api/v1/auth/status')
  const data = (await status.json()) as { initialized: boolean }
  test.skip(data.initialized, '管理员已初始化，跳过首次设置流程')

  await page.goto('/')
  await expect(page).toHaveURL(/\/setup$/)
  await expect(page.getByText('首次设置管理员')).toBeVisible()

  await page.locator('input[autocomplete="new-password"]').first().fill(E2E_PASSWORD)
  await page.locator('input[autocomplete="new-password"]').nth(1).fill(E2E_PASSWORD)
  await page.getByRole('button', { name: '创建管理员并登录' }).click()

  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByText('机器人版本')).toBeVisible()
})
