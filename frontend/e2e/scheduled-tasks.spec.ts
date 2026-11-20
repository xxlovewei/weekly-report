import { test, expect } from './fixtures'

test('管理员可以保存定时任务设置，普通用户无法进入管理页', async ({ page }) => {
  const user = { id: 7, role: 'admin', display_name: '管理员', must_change_password: false }
  const task = { key: 'unread-message-reminder', name: '未读消息提醒', enabled: true, interval_minutes: 5 }
  await page.route('**/api/auth/me', route => route.fulfill({ json: { user, csrf_token: 'test' } }))
  await page.route('**/api/notifications/unread', route => route.fulfill({ json: { count: 0 } }))
  await page.route('**/api/notifications/stream*', route => route.abort())
  await page.route('**/api/scheduled-tasks', route => route.fulfill({ json: [task] }))
  await page.route(`**/api/scheduled-tasks/${task.key}`, route => {
    expect(route.request().method()).toBe('PUT')
    expect(route.request().postDataJSON()).toEqual({ enabled: false, interval_minutes: 12 })
    Object.assign(task, route.request().postDataJSON())
    return route.fulfill({ json: task })
  })

  await page.goto('/scheduled-tasks')
  await expect(page.getByRole('heading', { name: '定时任务', exact: true })).toBeVisible()
  const status = page.getByLabel('任务状态')
  const interval = page.getByLabel('执行间隔（分钟）')
  await expect(status.locator('option:checked')).toHaveText('开启')
  await expect(interval).toHaveValue('5')
  await status.selectOption({ label: '关闭' })
  await interval.fill('12')
  await page.getByRole('button', { name: '保存设置' }).click()
  await expect(page.getByText('未读消息提醒已保存')).toBeVisible()
  await page.reload()
  await expect(status.locator('option:checked')).toHaveText('关闭')
  await expect(interval).toHaveValue('12')

  user.role = 'user'
  await page.reload()
  await expect(page).toHaveURL(/\/work$/)
  await expect(page.getByRole('navigation', { name: '主导航' }).getByText('定时任务')).toHaveCount(0)
})
