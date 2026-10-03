import { expect, test, type Page } from '@playwright/test'
import { E2E_PASSWORD } from './helpers'

async function login(page: Page): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('管理员密码', { exact: true }).fill(E2E_PASSWORD)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByText('机器人版本')).toBeVisible()
}

test('漫画操作收藏，收藏筛选刷新保留，取消后移出列表', async ({ page }) => {
  await login(page)
  await page.goto('/library?search=900007&sort=id_asc')
  await page.getByRole('button', { name: '收藏', exact: true }).click()
  await expect(page.getByRole('button', { name: '取消收藏', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '删除', exact: true }).click()
  await page.getByRole('button', { name: '确认删除', exact: true }).click()
  await expect(page.getByText('不能删除：该漫画已被管理员收藏，请管理员先取消收藏', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '取消收藏', exact: true })).toBeVisible()
  await page.getByRole('checkbox', { name: '选择 大文件读取测试', exact: true }).check()
  await page.getByRole('button', { name: '批量删除', exact: true }).click()
  await page.getByRole('button', { name: '确认批量删除', exact: true }).click()
  await expect(page.getByText(/批量删除完成：成功 0 个，失败 1 个：900007.*不能删除/)).toBeVisible()
  await page.getByRole('checkbox', { name: '仅看收藏', exact: true }).check()
  await expect(page).toHaveURL(/favorite_only=true/)
  await page.reload()
  await expect(page.getByRole('checkbox', { name: '仅看收藏', exact: true })).toBeChecked()
  await expect(page.getByRole('button', { name: '取消收藏', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0)
  await page.getByRole('button', { name: '取消收藏', exact: true }).click()
  await expect(page.getByText('没有找到漫画')).toBeVisible()
})

test('权限页关联、更换与解除 QQ，刷新保持关联', async ({ page }) => {
  await login(page)
  await page.goto('/permissions')
  await page.getByLabel('管理员 QQ 号', { exact: true }).fill('123456789')
  await page.getByRole('button', { name: '关联 QQ', exact: true }).click()
  await expect(page.getByText('当前关联：123456789', { exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByLabel('管理员 QQ 号', { exact: true })).toHaveValue('123456789')
  await page.getByLabel('管理员 QQ 号', { exact: true }).fill('987654321')
  await page.getByRole('button', { name: '更换关联', exact: true }).click()
  await expect(page.getByText('当前关联：987654321', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0)
  await page.getByRole('button', { name: '解除关联', exact: true }).click()
  await expect(page.getByText('当前关联：未关联', { exact: true })).toBeVisible()
})
