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

test.describe.configure({ mode: 'serial' })

test('管理员登录并看到仪表盘状态', async ({ page }) => {
  await login(page)
  await expect(page.getByText('NapCat 连接')).toBeVisible()
  await expect(page.getByText('最近任务')).toBeVisible()
})

test('漫画库搜索、清空与危险操作确认', async ({ page }) => {
  await login(page)
  await page.goto('/library')
  await expect(page.getByText('共', { exact: false }).first()).toBeVisible()

  // 搜索已知测试数据标题
  const searchBox = page.getByRole('textbox', { name: '搜索标题 / 作者' })
  await searchBox.fill('夜行')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await expect(page.getByText('夜行测试录').first()).toBeVisible()

  // 清空搜索恢复列表
  await searchBox.fill('')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await expect(page.getByText('夜行测试录').first()).toBeVisible()

  // 选中第一本并打开批量删除确认，取消后数据仍在
  await page.getByRole('checkbox', { name: /选择/ }).first().click()
  await page.getByRole('button', { name: '批量删除' }).click()
  await expect(page.getByText('批量删除 1 个漫画？')).toBeVisible()
  await page.getByRole('button', { name: '取消' }).click()
  await expect(page.getByText('批量删除 1 个漫画？')).toBeHidden()
  await expect(page.getByText('夜行测试录').first()).toBeVisible()
})

test('新建下载请求并在任务页查看', async ({ page }) => {
  await login(page)
  await page.goto('/tasks')

  await page.getByRole('button', { name: '新建下载' }).click()
  await expect(page.getByText('新建下载请求')).toBeVisible()
  await page.getByPlaceholder('例如：350234, 422866').fill('900001, 900002')
  await page.getByRole('button', { name: '请求下载' }).click()

  await expect(page.getByText(/已入队 \d+ 个/)).toBeVisible()
  await expect(page.getByText('900001').first()).toBeVisible()
  await expect(page.getByText('900002').first()).toBeVisible()
})

test('备份下载触发附件下载', async ({ page }) => {
  await login(page)
  await page.goto('/maintenance')
  const readyBackup = page
    .locator('tr, .v-list-item')
    .filter({ hasText: '就绪' })
    .first()
  const downloadLink = readyBackup.getByRole('link', { name: '下载备份' })
  await expect(downloadLink).toBeVisible()

  const [download] = await Promise.all([
    page.waitForEvent('download'),
    downloadLink.click(),
  ])

  expect(download.suggestedFilename()).toMatch(/^main-\d{8}-\d{6}-.*\.db$/)
})

test('移动端与桌面均无页面级横向滚动', async ({ page }) => {
  await login(page)
  for (const path of ['/library', '/tasks', '/permissions', '/settings', '/maintenance']) {
    await page.goto(path)
    await expect(page.locator('.v-main')).toBeVisible()
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    )
    expect(overflow, `页面 ${path} 不应出现横向滚动`).toBeLessThanOrEqual(1)
  }
})
