import { expect, test, type Page } from '@playwright/test'

import { E2E_PASSWORD } from './helpers'

async function login(page: Page): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('管理员密码', { exact: true }).fill(E2E_PASSWORD)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByText('机器人版本')).toBeVisible()
}

test.describe.configure({ mode: 'serial' })

test('单条拉黑拦截下载，任务与审计可见，解除后恢复', async ({ page }) => {
  await login(page)
  await page.goto('/library?search=900006&sort=id_asc')

  await page.getByRole('button', { name: '加入黑名单', exact: true }).click()
  await page.getByRole('button', { name: '确认拉黑', exact: true }).click()
  await expect(page.getByText('已将《星尘与猫》加入黑名单', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '解除拉黑', exact: true })).toBeVisible()
  await expect(page.getByText('已拉黑', { exact: true }).first()).toBeVisible()

  await page.goto('/download')
  await page.locator('textarea').first().fill('900006')
  await page.getByRole('button', { name: '请求下载', exact: true }).click()
  await expect(page.getByText(/1 个已被拉黑跳过（900006）/)).toBeVisible()

  await page.goto('/tasks?task_type=blacklist')
  await expect(page.getByText('漫画黑名单 900006').first()).toBeVisible()
  await expect(page.getByText('黑名单', { exact: true }).first()).toBeVisible()

  await page.goto('/audit?event_type=manga.blacklisted')
  await expect(page.getByText('manga.blacklisted', { exact: true }).first()).toBeVisible()

  await page.goto('/library?search=900006&sort=id_asc')
  await page.getByRole('button', { name: '解除拉黑', exact: true }).click()
  await page.getByRole('button', { name: '确认解除', exact: true }).click()
  await expect(page.getByText('已将《星尘与猫》移出黑名单', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '加入黑名单', exact: true })).toBeVisible()
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth - innerWidth),
  ).toBeLessThanOrEqual(1)
})

test('批量拉黑后在黑名单标签展示，刷新保留筛选并可批量解除', async ({ page }) => {
  await login(page)
  await page.goto('/library?search=900006&sort=id_asc')

  await page.getByRole('checkbox', { name: '选择 星尘与猫', exact: true }).check()
  await page.getByRole('button', { name: '批量拉黑', exact: true }).click()
  await page.getByRole('button', { name: '确认批量拉黑', exact: true }).click()
  await expect(page.getByText('已拉黑 1 个漫画', { exact: true })).toBeVisible()

  await page.getByRole('tab', { name: '黑名单', exact: true }).click()
  await expect(page).toHaveURL(/collection=blacklist_only/)
  await expect(page.getByText('星尘与猫').first()).toBeVisible()
  await page.reload()
  await expect(page.getByRole('tab', { name: '黑名单', exact: true })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  await expect(page.getByText('星尘与猫').first()).toBeVisible()

  await page.getByRole('checkbox', { name: '选择 星尘与猫', exact: true }).check()
  await expect(page.getByRole('button', { name: '批量解除', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: '批量解除', exact: true }).click()
  await page.getByRole('button', { name: '确认批量解除', exact: true }).click()
  await expect(page.getByText('已解除拉黑 1 个漫画', { exact: true })).toBeVisible()
  await expect(page.getByText('没有找到漫画')).toBeVisible()
})
