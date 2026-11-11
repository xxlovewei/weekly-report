import type { APIRequestContext } from '@playwright/test'
import { test, expect, skipGuides } from './fixtures'
import { mondayOf, todayShanghai } from '../src/dates'
import type { WeekData } from '../src/types'

async function login(request: APIRequestContext, username: string) {
  const response = await request.post('/api/auth/login', { data: { username, password: 'e2e-password-123' } })
  await expect(response).toBeOK()
  const session = await response.json()
  return { headers: { 'X-CSRF-Token': session.csrf_token as string }, user: session.user }
}

test('任务右键排序、优先级及转交', async ({ page, browser, baseURL }) => {
  const bobContext = await browser.newContext({ baseURL })
  const alice = await login(page.request, 'alice')
  const bob = await login(bobContext.request, 'bob')
  const weekPath = `/api/weeks/${mondayOf(todayShanghai())}`
  const fixtureIds: number[] = []
  const names = ['甲', '乙', '丙'].map(name => `任务操作验证 ${Date.now()} ${name}`)
  const readWeek = async (request: APIRequestContext): Promise<WeekData> => {
    const response = await request.get(weekPath)
    await expect(response).toBeOK()
    return response.json()
  }
  try {
    let week = await readWeek(page.request)
    const baseline = week.tasks.map(task => task.task_group)
    for (const task_group of names) {
      const created = await page.request.post(`${weekPath}/tasks?revision=${week.revision}`, { headers: alice.headers })
      await expect(created).toBeOK()
      week = await created.json()
      const id = week.tasks.at(-1)!.id
      fixtureIds.push(id)
      const edited = await page.request.patch(`${weekPath}/tasks/${id}?revision=${week.revision}`, { headers: alice.headers, data: { task_group } })
      await expect(edited).toBeOK()
      week = await edited.json()
    }
    const rows = page.locator('.task-row')
    const groups = page.getByRole('textbox', { name: '任务大类' })
    const assertOrder = (order: string[]) => expect.poll(() => groups.evaluateAll(elements => elements.map(element => (element as HTMLInputElement).value))).toEqual(order)
    await page.goto('/work')
    await assertOrder([...baseline, ...names])

    const menu = page.getByRole('group', { name: '任务操作' })
    const action = (name: string) => menu.getByRole('button', { name, exact: true })
    const open = (index: number) => rows.nth(index).locator('.task-index').click({ button: 'right' })
    const [a, b, c] = names
    await open(baseline.length + 2)
    await expect(action('下移一行')).toBeDisabled()
    await expect(action('下移一行')).toHaveCSS('cursor', 'not-allowed')
    await action('置顶').click()
    await assertOrder([c, ...baseline, a, b])
    await open(0)
    await expect(action('上移一行')).toBeDisabled()
    await expect(action('上移一行')).toHaveCSS('cursor', 'not-allowed')
    await action('下移一行').click()
    await assertOrder(baseline.length ? [baseline[0], c, ...baseline.slice(1), a, b] : [a, c, b])
    await open(1)
    await action('上移一行').click()
    await assertOrder([c, ...baseline, a, b])
    await open(0)
    await action('置底').click()
    await assertOrder([...baseline, a, b, c])

    const last = rows.last()
    const priorityMenu = page.getByRole('group', { name: '设置优先级' })
    await open(baseline.length + 2)
    await action('设置优先级').click()
    await expect(priorityMenu.getByRole('button')).toHaveText(['高', '中', '低'])
    await expect(priorityMenu.getByRole('button', { name: '低' })).toHaveAttribute('aria-pressed', 'true')
    await expect(priorityMenu.getByRole('button', { name: '低' })).toBeFocused()
    await page.keyboard.press('Escape')

    for (const [priority, background] of [['高', 'rgb(255, 87, 87)'], ['中', 'rgb(255, 149, 0)'], ['低', 'rgba(0, 0, 0, 0)'], ['高', 'rgb(255, 87, 87)']]) {
      await open(baseline.length + 2)
      await action('设置优先级').click()
      await priorityMenu.getByRole('button', { name: priority, exact: true }).click()
      await expect(last.locator('.task-leading')).toHaveCSS('background-color', background)
      await expect(page.getByText('✓ 已保存')).toBeVisible()
    }
    await page.reload()
    await assertOrder([...baseline, a, b, c])
    await expect(last.locator('.task-leading')).toHaveClass(/priority-high/)
    await last.locator('.task-drag-handle').press('Shift+F10')
    await action('转交任务').click()
    const dialog = page.getByRole('dialog', { name: '转交任务' })
    await expect(dialog.getByRole('button', { name: '确认转交' })).toBeDisabled()
    await expect(dialog.getByRole('option', { name: /（bob）/ })).toBeAttached()
    await expect(dialog.getByRole('option', { name: /（admin|（alice/ })).toHaveCount(0)
    await dialog.getByLabel('接收人').selectOption(String(bob.user.id))
    await dialog.getByRole('button', { name: '确认转交' }).click()
    await assertOrder([...baseline, a, b])
    await page.reload()
    await assertOrder([...baseline, a, b])

    const recipientPage = await bobContext.newPage()
    await skipGuides(recipientPage)
    await recipientPage.goto('/work')
    const received = recipientPage.locator('.task-row').last()
    await expect(received.getByRole('textbox', { name: '任务大类' })).toHaveValue(c)
    await expect(received.locator('.task-leading')).toHaveClass(/priority-high/)
    const tooltip = `由${alice.user.display_name}转交的任务`
    const light = received.getByRole('img', { name: tooltip })
    await light.hover()
    await expect(light).toHaveAttribute('title', tooltip)
  } finally {
    // 只清理本次验证创建的任务，保留测试环境原有数据。
    try {
      for (const [request, headers] of [[page.request, alice.headers], [bobContext.request, bob.headers]] as const) {
        const week = await readWeek(request)
        let revision = week.revision
        for (const task of week.tasks.filter(item => fixtureIds.includes(item.id))) {
          const removed = await request.delete(`${weekPath}/tasks/${task.id}?revision=${revision}`, { headers })
          await expect(removed).toBeOK()
          revision = (await removed.json()).revision
        }
      }
    } finally {
      await bobContext.close()
    }
  }
})
