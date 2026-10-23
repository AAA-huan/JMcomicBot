import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

import { E2E_PASSWORD } from './helpers'

interface SystemStatusView {
  manga_count: number
  uptime_seconds: number
}

interface AuditListResponse {
  total: number
}

async function login(page: Page): Promise<void> {
  // 单独运行本用例时不会先执行 00-setup，需要保证管理员已初始化
  const status = await page.request.get('/api/v1/auth/status')
  const auth = (await status.json()) as { initialized: boolean }
  if (!auth.initialized) {
    await page.goto('/setup')
    await page
      .locator('input[autocomplete="new-password"]')
      .first()
      .fill(E2E_PASSWORD)
    await page
      .locator('input[autocomplete="new-password"]')
      .nth(1)
      .fill(E2E_PASSWORD)
    await page.getByRole('button', { name: '创建管理员并登录' }).click()
    await expect(page).toHaveURL(/\/$/)
    await expect(page.getByText('机器人版本')).toBeVisible()
    return
  }

  await page.goto('/login')
  await page.getByLabel('管理员密码', { exact: true }).fill(E2E_PASSWORD)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByText('机器人版本')).toBeVisible()
}

async function getStatus(
  request: APIRequestContext,
): Promise<SystemStatusView | null> {
  try {
    const response = await request.get('/api/v1/system/status')
    if (!response.ok()) return null
    return (await response.json()) as SystemStatusView
  } catch {
    return null
  }
}

async function auditTotal(
  request: APIRequestContext,
  eventType: string,
): Promise<number | null> {
  try {
    const response = await request.get('/api/v1/audit-events', {
      params: { event_type: eventType, page_size: 1 },
    })
    if (!response.ok()) return null
    const body = (await response.json()) as AuditListResponse
    return body.total
  } catch {
    return null
  }
}

test('导出数据库并确认导入，重启后数据保持一致', async ({
  page,
}, testInfo) => {
  test.setTimeout(180_000)
  // 导入会触发真实进程重启，只在桌面项目验证一次，避免重复重启后端
  test.skip(testInfo.project.name !== 'desktop-chromium', '数据迁移只验证一次')

  await login(page)
  await page.goto('/maintenance')
  await expect(page.getByText('数据导出与导入', { exact: true })).toBeVisible()

  // 让服务运行足够久，重启后可用 uptime 归零区分新旧进程
  await expect
    .poll(async () => (await getStatus(page.request))?.uptime_seconds ?? 0, {
      timeout: 60_000,
      intervals: [1_000, 2_000],
    })
    .toBeGreaterThan(10)

  const beforeStatus = await getStatus(page.request)
  if (beforeStatus === null) throw new Error('无法读取导入前的系统状态')
  const beforeUptime = beforeStatus.uptime_seconds

  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出数据', exact: true }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toMatch(/^data-export-.*\.zip$/)
  const archivePath = testInfo.outputPath(download.suggestedFilename())
  await download.saveAs(archivePath)
  await expect(page.getByText(/数据已导出：/)).toBeVisible()

  // 导出审计在快照生成后写入旧库，可用于判断重启后新库是否生效
  await expect
    .poll(() => auditTotal(page.request, 'data.exported'))
    .toBe(1)

  await page.getByLabel('选择导入数据包').setInputFiles(archivePath)
  await expect(page.getByText(/导出 schema：/)).toBeVisible()
  await expect(page.getByText(/数据库文件：main-/)).toBeVisible()
  await expect(
    page.getByRole('button', { name: '确认导入', exact: true }),
  ).toBeEnabled()

  await page.getByRole('button', { name: '确认导入', exact: true }).click()
  await expect(page.getByText('确认导入全部数据？')).toBeVisible()
  await page.getByRole('button', { name: '确认导入并重启', exact: true }).click()

  // 新库不含本次导出/导入审计，且新进程 uptime 小于导入前，说明替换与重启都已完成
  await expect
    .poll(
      async () => {
        const [exported, imported, status] = await Promise.all([
          auditTotal(page.request, 'data.exported'),
          auditTotal(page.request, 'data.imported'),
          getStatus(page.request),
        ])
        if (exported === null || imported === null || status === null) {
          return false
        }
        return (
          exported === 0 &&
          imported === 0 &&
          status.uptime_seconds < beforeUptime
        )
      },
      { timeout: 120_000, intervals: [500, 1_000, 2_000] },
    )
    .toBe(true)

  // 登录态、漫画数量与业务数据来自导出快照，重启前后应保持一致
  await page.goto('/maintenance')
  await expect(page).toHaveURL(/\/maintenance$/)
  await expect(page.getByText('数据导出与导入', { exact: true })).toBeVisible()

  const afterStatus = await getStatus(page.request)
  if (afterStatus === null) throw new Error('无法读取导入后的系统状态')
  expect(afterStatus.manga_count).toBe(beforeStatus.manga_count)

  await page.goto('/library?search=900006&sort=id_asc')
  await expect(page.getByText('星尘与猫').first()).toBeVisible()
})
