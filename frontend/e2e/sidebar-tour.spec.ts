import { expect, test, type Page } from '@playwright/test'
import packageInfo from '../package.json' with { type: 'json' }
import type { Task, User } from '../src/types'
import { mondayOf, todayShanghai } from '../src/dates'

const currentVersion = packageInfo.version

async function mockWorkspace(page: Page, user: User, tasks: Task[] = []) {
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/auth/me')) return route.fulfill({ json: { user, csrf_token: 'test' } })
    if (path.endsWith('/work-context')) return route.fulfill({ json: { current_week: mondayOf(todayShanghai()), members: [] } })
    if (path.includes('/weeks/')) return route.fulfill({ json: { revision: 0, tasks } })
    if (path.includes('/reviews/days/')) return route.fulfill({ json: { projects: {}, issues: [], common_project_ids: [], summary: null } })
    if (path.endsWith('/meetings')) return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 50 } })
    if (path.endsWith('/releases')) return route.fulfill({ json: [
      { version: '1.10.0', description: '较新的历史版本说明。' },
      { version: currentVersion, description: '新增侧栏折叠和按周导航。' },
      { version: '1.9.0', description: '最早的版本说明。' },
    ] })
    return route.fulfill({ json: [] })
  })
}

const member: User = { id: 42, username: 'member', display_name: '测试成员', role: 'user', is_active: true, status: '正常', must_change_password: false }

for (const [mode, width, height] of [['展开', 1280, 460], ['收起', 1024, 360], ['移动', 390, 390]] as const) {
  test(`${mode}侧栏的账号区和月历贴底，长列表可滚到最后一条`, async ({ page }) => {
    const tasks: Task[] = Array.from({ length: 12 }, (_, index) => ({
      id: index + 1, position: index + 1, category_name: null, task_group: '',
      description: `任务 ${index + 1}`, status: null, work_days: [], notes: '',
    }))
    await page.setViewportSize({ width, height })
    await page.context().grantPermissions(['notifications'])
    await mockWorkspace(page, { ...member, role: 'admin' }, tasks)
    await page.addInitScript(id => {
      localStorage.setItem(`zhoubao.sidebar-tour.v1.4.0.${id}`, '1')
      localStorage.setItem(`zhoubao.task-actions-tour.${id}`, '1')
    }, member.id)
    await page.goto('/work')
    const mobileToggle = page.getByRole('button', { name: '打开或关闭导航' })
    if (mode === '移动') await mobileToggle.click()
    if (mode === '收起') await page.getByRole('button', { name: '收起侧栏' }).click()

    const footer = page.locator('.sidebar-bottom')
    const calendar = page.locator('.sidebar .calendar')
    const sidebarBody = page.locator('.sidebar-body')
    await expect(footer.getByRole('button', { name: '退出登录' })).toBeInViewport({ ratio: 1 })
    await expect(calendar).toBeInViewport({ ratio: 1 })
    const footerBox = (await footer.boundingBox())!
    const calendarY = (await calendar.boundingBox())!.y
    expect(height - footerBox.y - footerBox.height).toBeLessThanOrEqual(24)
    await sidebarBody.hover()
    await page.mouse.wheel(0, 5000)
    await expect.poll(() => sidebarBody.evaluate(element => element.scrollTop)).toBeGreaterThan(0)
    await expect(sidebarBody.getByRole('button', { name: '本周工作' })).toBeInViewport({ ratio: 1 })
    expect((await footer.boundingBox())?.y).toBe(footerBox.y)
    expect((await calendar.boundingBox())?.y).toBe(calendarY)
    if (mode === '移动') await mobileToggle.click()

    const lastTask = page.locator('#work-task-12')
    const workArea = page.locator('.work-area')
    await expect(lastTask).not.toBeInViewport()
    await workArea.hover()
    await page.mouse.wheel(0, 10000)
    await expect.poll(() => workArea.evaluate(element => element.scrollHeight - element.clientHeight - element.scrollTop)).toBeLessThanOrEqual(1)
    const taskBox = (await lastTask.boundingBox())!
    const workAreaBox = (await workArea.boundingBox())!
    expect(taskBox.y + taskBox.height).toBeLessThanOrEqual(workAreaBox.y + workAreaBox.height)
    await expect(lastTask).toBeInViewport()
    expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBe(height)
  })
}

test('当前菜单项吸附在菜单上下边缘，滚回时恢复原位', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 412 })
  await mockWorkspace(page, { ...member, role: 'admin' })
  await page.goto('/review-records')
  const menu = page.locator('.sidebar-body')
  const active = menu.getByRole('button', { name: '审查记录' })
  const edges = () => menu.evaluate(element => {
    const selected = element.querySelector('[aria-current="page"]')!
    const previous = selected.previousElementSibling!
    const menuRect = element.getBoundingClientRect()
    const activeRect = selected.getBoundingClientRect()
    const previousRect = previous.getBoundingClientRect()
    const { paddingTop, paddingBottom } = getComputedStyle(element)
    const { rowGap } = getComputedStyle(selected.parentElement!)
    return {
      fromTop: activeRect.top - menuRect.top - parseFloat(paddingTop),
      fromBottom: menuRect.bottom - parseFloat(paddingBottom) - activeRect.bottom,
      fromOriginal: activeRect.top - previousRect.bottom - parseFloat(rowGap),
      centerScroll: element.scrollTop + previousRect.bottom + parseFloat(rowGap)
        - menuRect.top - (menuRect.height - activeRect.height) / 2,
    }
  })

  await expect(active).toHaveAttribute('aria-current', 'page')
  await expect(active).toBeInViewport({ ratio: 1 })
  const bottom = await edges()
  expect(bottom.fromBottom).toBeLessThanOrEqual(2)
  expect(bottom.fromOriginal).toBeLessThan(0)
  await menu.hover()
  await page.mouse.wheel(0, 5000)
  await expect.poll(async () => (await edges()).fromTop).toBeLessThanOrEqual(2)
  await expect(active).toBeInViewport({ ratio: 1 })
  expect((await edges()).fromOriginal).toBeGreaterThan(0)

  await menu.evaluate((element, target) => { element.scrollTop = target }, (await edges()).centerScroll)
  const middle = await edges()
  expect(middle.fromOriginal).toBeCloseTo(0, 0)
  expect(middle.fromTop).toBeGreaterThan(0)
  expect(middle.fromBottom).toBeGreaterThan(0)
  await page.mouse.wheel(0, -5000)
  await expect.poll(async () => (await edges()).fromBottom).toBeLessThanOrEqual(2)
})

test('版本更新可按版本号前后切换，重新打开恢复当前版本', async ({ page }) => {
  await mockWorkspace(page, member)
  await page.goto('/categories')
  const version = page.locator('[data-sidebar-tour="release-notes"]')
  const notes = page.getByRole('region', { name: /更新内容/ })
  const previous = notes.getByRole('button', { name: '上一个版本' })
  const next = notes.getByRole('button', { name: '下一个版本' })
  await version.hover()
  await expect(notes).toHaveAccessibleName(`v${currentVersion} 更新内容`)
  await expect(next).toBeDisabled()
  await previous.click()
  await expect(notes).toHaveAccessibleName('v1.10.0 更新内容')
  await expect(notes).toContainText('较新的历史版本说明。')
  await previous.click()
  await expect(notes).toHaveAccessibleName('v1.9.0 更新内容')
  await expect(previous).toBeDisabled()
  await next.click()
  await expect(notes).toHaveAccessibleName('v1.10.0 更新内容')
  await page.mouse.move(4, 4)
  await expect(notes).toHaveCount(0)

  await version.focus()
  await expect(notes).toHaveAccessibleName(`v${currentVersion} 更新内容`)
  await page.keyboard.press('Tab')
  await expect(previous).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(notes).toHaveAccessibleName('v1.10.0 更新内容')
  await page.keyboard.press('Escape')
  await expect(notes).toHaveCount(0)
  await expect(version).toBeFocused()
})

test('任务引导自动高亮整张卡片，每个账号只显示一次', async ({ page }) => {
  await mockWorkspace(page, member, [{ id: 1, position: 1, category_name: null, task_group: '', description: '', status: null, work_days: [], notes: '' }])
  await page.goto('/work')
  const tour = page.locator('.driver-popover')
  await expect(tour).toHaveAccessibleName('收起侧栏')
  await tour.getByRole('button', { name: '跳过引导' }).click()
  await expect(tour).toHaveAccessibleName('任务卡片右键菜单')
  await expect(page.locator('.task-row').first()).toHaveClass(/driver-active-element/)
  await expect(tour.locator('.driver-popover-description')).toHaveText('右键点击任意任务卡片，即可置顶、上移一行、下移一行或置底。高、中优先级的序号区域分别显示红色、橙色。转交后，接收人可在任务箱中开始任务，悬停灯泡可查看转交来源。')
  await expect(tour.getByRole('button')).toHaveText(['完成'])
  await tour.getByRole('button', { name: '完成', exact: true }).click()
  await expect(tour).toHaveCount(0)
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
  const version = page.locator('[data-sidebar-tour="release-notes"]')
  const versionBox = (await version.boundingBox())!
  const tourBox = (await tour.boundingBox())!
  expect(tourBox.x - (versionBox.x + versionBox.width)).toBeLessThan(32)
  await version.hover()
  const releaseNotes = page.getByRole('region', { name: /更新内容/ })
  await expect(releaseNotes).toContainText('新增侧栏折叠和按周导航。')
  const notesBox = (await releaseNotes.boundingBox())!
  expect(notesBox.y).toBeGreaterThanOrEqual(tourBox.y + tourBox.height)
  expect(tourBox.x + tourBox.width).toBeLessThanOrEqual(width)
  await releaseNotes.hover()
  await releaseNotes.getByRole('button', { name: '上一个版本' }).click()
  await expect(releaseNotes).toContainText('较新的历史版本说明。')
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
  const reportActions = page.locator('.report-top .top-actions')
  const meetingShortcut = reportActions.getByRole('button', { name: '新增会议记录' })
  await expect(meetingShortcut).toHaveClass(/primary-button/)
  await meetingShortcut.click()
  const meetingDialog = page.getByRole('dialog', { name: '新增会议记录' })
  await expect(meetingDialog.getByLabel('会议类型')).toHaveValue('周会')
  await meetingDialog.locator('.modal-actions').getByRole('button', { name: '关闭' }).click()

  await page.setViewportSize({ width: 1280, height: 720 })
  await expect(tour).toHaveAccessibleName('收起侧栏', { timeout: 3000 })
  await tour.getByRole('button', { name: '收起侧栏' }).click()
  for (const title of ['查看版本更新内容', '本周工作', '周报汇总', '任务类型', '会议记录', '用户管理', '回到本周', '上一周', '下一周', '周会快捷入口']) {
    await expect(tour).toHaveAccessibleName(title)
    if (title === '周会快捷入口') await expect(meetingShortcut).toHaveClass(/driver-active-element/)
    await tour.getByRole('button', { name: '下一步' }).click()
  }
  await tour.getByRole('button', { name: '跳过引导' }).click()
  await expect(tour).toHaveCount(0)
  await expect(page.locator('.calendar-grid')).toBeVisible()
  await page.reload()
  await page.getByRole('button', { name: '收起侧栏' }).click()
  await expect(tour).toHaveCount(0)
  await page.getByRole('button', { name: '展开侧栏' }).click()
  await page.setViewportSize({ width: 801, height: 720 })
  await expect(meetingShortcut).toBeInViewport({ ratio: 1 })
  await expect(reportActions.getByRole('button', { name: '消息中心' })).toBeInViewport({ ratio: 1 })

  admin.id += 1
  admin.must_change_password = true
  await page.reload()
  await expect(page.getByRole('heading', { name: '修改密码' })).toBeVisible()
  await expect(tour).toHaveCount(0)
  admin.must_change_password = false
  await page.goto('/reports')
  await expect(tour).toHaveAccessibleName('收起侧栏')
})
