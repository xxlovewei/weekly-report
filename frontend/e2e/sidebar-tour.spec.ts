import { expect, test, type Page } from '@playwright/test'
import type { Task, User } from '../src/types'

async function mockWorkspace(page: Page, user: User, tasks: Task[] = []) {
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/auth/me')) return route.fulfill({ json: { user, csrf_token: 'test' } })
    if (path.includes('/weeks/')) return route.fulfill({ json: { revision: 0, tasks } })
    if (path.endsWith('/meetings')) return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 50 } })
    if (path.includes('/releases/')) return route.fulfill({ json: { description: '新增侧栏折叠和按周导航。' } })
    return route.fulfill({ json: [] })
  })
}

const member: User = { id: 42, username: 'member', display_name: '测试成员', role: 'user', is_active: true, status: '正常', must_change_password: false }

test('任务引导自动高亮整张卡片，每个账号只显示一次', async ({ page }) => {
  await mockWorkspace(page, member, [{ id: 1, position: 1, category_name: null, task_group: '', description: '', status: null, work_days: [], notes: '' }])
  await page.goto('/work')
  const tour = page.locator('.driver-popover')
  await expect(tour).toHaveAccessibleName('收起侧栏')
  await tour.getByRole('button', { name: '跳过引导' }).click()
  await expect(tour).toHaveAccessibleName('任务卡片右键菜单')
  await expect(page.locator('.task-row').first()).toHaveClass(/driver-active-element/)
  await expect(tour.locator('.driver-popover-description')).toHaveText('右键点击任意任务卡片，即可置顶、上移一行、下移一行或置底。高、中优先级的序号区域分别显示红色、橙色。转交任务时请选择接收人并确认，接收人可悬停在序号下的灯泡上查看转交来源。')
  await tour.getByRole('button', { name: '完成' }).click()
  await expect(page.getByRole('button', { name: '任务操作引导' })).toHaveCount(0)
  await page.reload()
  await page.getByRole('button', { name: '任务类型', exact: true }).click()
  await page.getByRole('button', { name: '本周工作', exact: true }).click()
  await expect(page.locator('.task-row')).toHaveCount(1)
  await expect(tour).toHaveCount(0)
})

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

  await expect(tour).toHaveAccessibleName('查看版本更新内容')
  const version = page.locator('.release-notes small')
  const versionBox = (await version.boundingBox())!
  const tourBox = (await tour.boundingBox())!
  expect(tourBox.x - (versionBox.x + versionBox.width)).toBeLessThan(32)
  await version.hover()
  const releaseNotes = page.getByRole('tooltip')
  await expect(releaseNotes).toContainText('新增侧栏折叠和按周导航。')
  const notesBox = (await releaseNotes.boundingBox())!
  expect(notesBox.y).toBeGreaterThanOrEqual(tourBox.y + tourBox.height)
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
  for (const title of ['查看版本更新内容', '本周工作', '周报汇总', '任务类型', '会议记录', '用户管理', '回到本周', '上一周', '下一周', '周会快捷入口']) {
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
