import { test, expect } from './fixtures'

test('周报汇总在未来周按成员显示只读任务计划', async ({ page }) => {
  await page.clock.setFixedTime(new Date('2026-11-25T04:00:00Z'))
  const current = '2026-11-23', future = '2026-11-30'
  const members = [{ id: 2, name: '小王', is_active: true }, { id: 3, name: '小李', is_active: true }]
  const task = { id: 1, position: 1, category_name: null, description: '', status: null, work_days: [3], notes: '' }
  await page.route('**/api/**', route => {
    const { pathname } = new URL(route.request().url())
    if (pathname === '/api/auth/me') return route.fulfill({ json: {
      user: { id: 2, username: 'alice', display_name: '小王', roles: ['user'] }, csrf_token: 'test',
    } })
    if (pathname === '/api/meetings') return route.fulfill({ json: { items: [], total: 0 } })
    if (pathname === '/api/calendar/marks') return route.fulfill({ json: [future] })
    if (pathname === `/api/reports/${current}/users/2`) return route.fulfill({ json: {
      revision: 1, tasks: [{ ...task, task_group: '本周工作明细' }], plans: [{ ...task, task_group: '历史计划' }],
    } })
    if (pathname === `/api/reports/${future}/users/2`) return route.fulfill({ json: {
      revision: 1, tasks: [], plans: [{ ...task, task_group: '接口联调计划' }],
    } })
    if (pathname === `/api/reports/${future}/users/3`) return route.fulfill({ json: { revision: 0, tasks: [] } })
    return route.fulfill({ json: pathname.startsWith('/api/reports/') ? members : [] })
  })

  await page.goto('/reports')
  await expect(page.getByText('本周工作明细')).toBeVisible()
  await expect(page.getByText('历史计划')).toHaveCount(0)
  await page.getByRole('button', { name: '2026-11-30，选择该周' }).click()
  await expect(page.getByRole('region', { name: '任务计划表' }).getByText('接口联调计划')).toBeVisible()
  await expect(page.getByRole('button', { name: '2026-12-06，选择该周，已有任务计划' })).toBeVisible()
  await expect(page.getByRole('button', { name: '删除', exact: true })).toHaveCount(0)

  await page.getByRole('tab', { name: '小李' }).click()
  await expect(page.getByText('这周还没有任务计划。')).toBeVisible()
  await page.getByRole('tab', { name: '小王' }).click()
  await expect(page.getByText('接口联调计划')).toBeVisible()

  await page.getByRole('button', { name: '回到本周' }).click()
  await expect(page.getByText('本周工作明细')).toBeVisible()
  await expect(page.getByRole('region', { name: '任务计划表' })).toHaveCount(0)
})
