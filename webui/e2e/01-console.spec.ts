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
  const searchBox = page.getByRole('textbox', { name: '搜索关键字' })
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

test('新建下载对话框命中已有任务（不触发真实下载）', async ({ page }) => {
  await login(page)
  await page.goto('/tasks')

  await page.getByRole('button', { name: '新建下载' }).click()
  await expect(page.getByText('新建下载请求')).toBeVisible()
  // 900004 在测试数据中已有一个排队中的下载任务，服务端应返回去重结果，
  // 避免测试触发 jmcomic 的真实联网下载而消耗本机资源
  await page.getByPlaceholder('例如：350234, 422866').fill('900004')
  await page.getByRole('button', { name: '请求下载' }).click()

  await expect(page.getByText(/已入队 0 个/)).toBeVisible()
  await expect(page.getByText(/已有活动任务/)).toBeVisible()
  await expect(page.getByText('900004').first()).toBeVisible()
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

test('侧边栏/抽屉可直达权限、配置、维护并在页面间跳转', async ({ page }, testInfo) => {
  await login(page)
  const isMobile = testInfo.project.name.startsWith('mobile')

  const openDrawerIfMobile = async () => {
    if (!isMobile) return
    // 等待 Vuetify 响应式断点稳定，避免刚打开的抽屉被初始化抖动关闭
    await page.waitForTimeout(500)
    await page.getByRole('button', { name: '打开菜单' }).click()
    await expect(page.locator('.v-navigation-drawer')).toHaveClass(
      /v-navigation-drawer--active/,
      { timeout: 5000 },
    )
  }

  for (const [label, path, marker] of [
    ['权限管理', '/permissions', '群白名单'],
    ['配置', '/settings', '文件发送'],
    ['维护', '/maintenance', '扫描漫画目录'],
  ] as const) {
    // 每次都从非仪表盘页面发起，验证跨页面跳转不再需要先回仪表盘
    await page.goto('/library')
    await openDrawerIfMobile()
    await page
      .locator('.v-navigation-drawer a', { hasText: label })
      .first()
      .click()
    await expect(page).toHaveURL(new RegExp(`${path}$`))
    await expect(page.getByText(marker).first()).toBeVisible()
  }
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
