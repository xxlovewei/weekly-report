import { expect, test, type Page } from '@playwright/test'
import type { User } from '../src/types'

async function mockWorkspace(page: Page, user: User) {
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/auth/me')) return route.fulfill({ json: { user, csrf_token: 'test' } })
    if (path.includes('/weeks/')) return route.fulfill({ json: { revision: 0, tasks: [] } })
    if (path.endsWith('/meetings')) return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 50 } })
    if (path.includes('/releases/')) return route.fulfill({ json: { description: '新增侧栏折叠和按周导航。' } })
    return route.fulfill({ json: [] })
  })
}

const member: User = { id: 42, username: 'member', display_name: '测试成员', role: 'user', is_active: true, status: '正常', must_change_password: false }

test('首次进入逐步演示收起和展开，完成后刷新不再显示', async ({ page }) => {
  const width = 801
  await page.setViewportSize({ width, height: 720 })
  await mockWorkspace(page, member)
  await page.goto('/work')
  const tour = page.locator('.driver-popover')
  await expect(tour).toHaveAccessibleName('收起侧栏', { timeout: 3000 })
  await page.locator('.sidebar').getByRole('button', { name: '收起侧栏' }).click()
  await expect(page.locator('.shell')).toHaveClass(/sidebar-collapsed/)
  await tour.getByRole('button', { name: '上一步' }).click()
  await expect(tour).toHaveAccessibleName('收起侧栏')
  await expect(page.locator('.shell')).not.toHaveClass(/sidebar-collapsed/)
  await tour.getByRole('button', { name: '收起侧栏' }).click()

  await expect(tour).toHaveAccessibleName('Logo 和版本号')
  await tour.getByRole('button', { name: '下一步' }).click()
  await expect(tour).toHaveAccessibleName('查看版本更新内容')
  await page.locator('.release-notes small').hover()
  const releaseNotes = page.getByRole('tooltip')
  await expect(releaseNotes).toContainText('新增侧栏折叠和按周导航。')
  const notesBox = (await releaseNotes.boundingBox())!
  const tourBox = (await tour.boundingBox())!
  expect(notesBox.x + notesBox.width).toBeLessThanOrEqual(tourBox.x)
  expect(tourBox.x + tourBox.width).toBeLessThanOrEqual(width)
  await releaseNotes.hover()
  await tour.getByRole('button', { name: '下一步' }).click()

  for (const title of ['本周工作', '周报汇总', '任务类型', '会议记录', '回到本周', '上一周', '下一周', '修改密码', '退出登录']) {
    await expect(tour).toHaveAccessibleName(title)
    await tour.getByRole('button', { name: '下一步' }).click()
  }
  await expect(tour).toHaveAccessibleName('展开侧栏')
  await page.locator('.sidebar').getByRole('button', { name: '展开侧栏' }).click()
  await expect(tour).toHaveCount(0)
  await expect(page.locator('.calendar-grid')).toBeVisible()
  await expect(page).toHaveURL(/\/work$/)
  await page.reload()
  await page.getByRole('button', { name: '收起侧栏' }).click()
  await expect(tour).toHaveCount(0)
  await expect(page.locator('.shell')).toHaveClass(/sidebar-collapsed/)
})

test('移动端不消耗首次机会，桌面跳过后只对新账号显示', async ({ page }) => {
  const admin = { ...member, role: 'admin' as const }
  await mockWorkspace(page, admin)
  await page.setViewportSize({ width: 390, height: 700 })
  await page.goto('/reports')
  const tour = page.locator('.driver-popover')
  await expect(page.getByRole('button', { name: '打开或关闭导航' })).toBeVisible()
  await expect(tour).toHaveCount(0)

  await page.setViewportSize({ width: 1280, height: 720 })
  await expect(tour).toHaveAccessibleName('收起侧栏', { timeout: 3000 })
  await tour.getByRole('button', { name: '收起侧栏' }).click()
  for (const title of ['Logo 和版本号', '查看版本更新内容', '本周工作', '周报汇总', '任务类型', '会议记录', '用户管理', '回到本周', '上一周', '下一周', '周会快捷入口']) {
    await expect(tour).toHaveAccessibleName(title)
    await tour.getByRole('button', { name: '下一步' }).click()
  }
  await tour.getByRole('button', { name: '跳过引导' }).click()
  await expect(tour).toHaveCount(0)
  await expect(page.locator('.calendar-grid')).toBeVisible()
  await page.reload()
  await page.getByRole('button', { name: '收起侧栏' }).click()
  await expect(tour).toHaveCount(0)

  admin.id += 1
  admin.must_change_password = true
  await page.reload()
  await expect(page.getByRole('heading', { name: '修改密码' })).toBeVisible()
  await expect(tour).toHaveCount(0)
  admin.must_change_password = false
  await page.goto('/reports')
  await expect(tour).toHaveAccessibleName('收起侧栏')
})
