import { test, expect, type Page } from '@playwright/test'
import type { Task } from '../src/types'

async function setup(page: Page) {
  await page.setViewportSize({ width: 1440, height: 1100 })
  let tasks: Task[] = ['第一项', '第二项', '第三项'].map((name, index) => ({ id: index + 1, position: index + 1, category_name: null, task_group: name, description: '', status: null, work_days: [], notes: '' }))
  let revision = 0
  const writes: string[] = []
  const orders: number[][] = []
  let rejectOrder = false
  await page.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname
    let data: unknown
    if (path.endsWith('/auth/me')) {
      data = { user: { id: 1, username: 'test', display_name: '测试用户', role: 'user', is_active: true, status: '正常', must_change_password: false }, csrf_token: 'test-csrf' }
    } else if (path.endsWith('/categories') || path.endsWith('/calendar/marks')) data = []
    else if (/\/reports\/[^/]+$/.test(path)) data = [{ id: 1, name: '测试用户', is_active: true }]
    else if (path.includes('/weeks/') || path.includes('/reports/')) {
      if (request.method() !== 'GET') {
        writes.push(request.method())
        if (Number(url.searchParams.get('revision')) !== revision || (rejectOrder && request.method() === 'PUT')) {
          await route.fulfill({ status: 409, json: { detail: '本周任务已在其他页面更新，请重新载入后保存' } })
          return
        }
        if (request.method() === 'PUT') {
          const ids = request.postDataJSON().task_ids as number[]
          orders.push(ids)
          tasks = ids.map((id, index) => ({ ...tasks.find(task => task.id === id)!, position: index + 1 }))
        } else if (request.method() === 'PATCH') Object.assign(tasks.find(task => task.id === Number(path.split('/').at(-1)))!, request.postDataJSON())
        revision++
      }
      data = { tasks, revision }
    } else { await route.fulfill({ status: 404, json: {} }); return }
    await route.fulfill({ json: data })
  })
  await page.goto('work')
  await expect(page.locator('.task-row')).toHaveCount(3)
  return { writes, orders, reject: () => { rejectOrder = true } }
}

async function startDrag(page: Page, from: number, to: number, after: boolean) {
  const handle = await page.locator('.task-drag-handle').nth(from).boundingBox()
  const target = await page.locator('.task-row').nth(to).boundingBox()
  if (!handle || !target) throw new Error('拖拽目标不可见')
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2)
  await page.mouse.down()
  await page.mouse.move(handle.x + handle.width / 2 + 8, handle.y + handle.height / 2, { steps: 4 })
  const x = target.x + target.width / 2, y = target.y + target.height * (after ? 0.8 : 0.2)
  await page.mouse.move(x, y, { steps: 12 })
  await page.mouse.move(x, y)
}

test('手柄拖拽上下排序，松手才保存，刷新后保留顺序与编号', async ({ page }, testInfo) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const state = await setup(page)
  await startDrag(page, 0, 2, true)
  expect(state.orders).toEqual([])
  await expect(page.locator('.task-row.drop-after')).toHaveCount(1)
  await page.mouse.up()
  await expect.poll(() => page.getByRole('textbox', { name: '任务大类' }).evaluateAll(elements => elements.map(element => (element as HTMLInputElement).value))).toEqual(['第二项', '第三项', '第一项'])
  expect(state.orders).toEqual([[2, 3, 1]])
  await page.reload()
  await expect.poll(() => page.getByRole('textbox', { name: '任务大类' }).evaluateAll(elements => elements.map(element => (element as HTMLInputElement).value))).toEqual(['第二项', '第三项', '第一项'])
  await expect(page.locator('.task-index')).toHaveText(['01', '02', '03'])
  await startDrag(page, 2, 0, false)
  await page.mouse.up()
  await expect.poll(() => page.getByRole('textbox', { name: '任务大类' }).evaluateAll(elements => elements.map(element => (element as HTMLInputElement).value))).toEqual(['第一项', '第二项', '第三项'])
  expect(state.orders).toEqual([[2, 3, 1], [1, 2, 3]])
  await page.screenshot({ path: testInfo.outputPath('task-order-desktop.png'), fullPage: true })
  for (const width of [320, 768, 1024]) {
    await page.setViewportSize({ width, height: 900 })
    const handle = page.locator('.task-drag-handle').first()
    await handle.scrollIntoViewIfNeeded()
    await expect(handle).toBeVisible()
    if (width === 320) await page.locator('.task-row').first().screenshot({ path: testInfo.outputPath('task-order-mobile.png') })
  }
  expect(errors).toEqual([])
})

test('排序前保存待提交的编辑，手柄支持键盘上下移动', async ({ page }) => {
  const state = await setup(page)
  await page.getByRole('textbox', { name: '任务大类' }).first().fill('修改后')
  await page.locator('.task-drag-handle').first().press('ArrowDown')
  await expect.poll(() => page.getByRole('textbox', { name: '任务大类' }).evaluateAll(elements => elements.map(element => (element as HTMLInputElement).value))).toEqual(['第二项', '修改后', '第三项'])
  expect(state.writes).toEqual(['PATCH', 'PUT'])
  await expect(page.locator('.task-drag-handle').nth(1)).toBeFocused()
  await page.keyboard.press('ArrowUp')
  await expect.poll(() => page.getByRole('textbox', { name: '任务大类' }).evaluateAll(elements => elements.map(element => (element as HTMLInputElement).value))).toEqual(['修改后', '第二项', '第三项'])
  await expect(page.locator('.task-drag-handle').first()).toBeFocused()
  await page.locator('.task-drag-handle').first().press('ArrowUp')
  expect(state.orders).toHaveLength(2)
})

test('取消拖拽与原地放下不保存，保存冲突时保留原顺序', async ({ page }) => {
  const state = await setup(page)
  await startDrag(page, 0, 2, true)
  await page.keyboard.press('Escape')
  await page.mouse.up()
  await expect(page.locator('.task-row.dragging')).toHaveCount(0)
  await startDrag(page, 0, 0, false)
  await page.mouse.up()
  expect(state.writes).toEqual([])
  state.reject()
  await startDrag(page, 0, 2, true)
  await page.mouse.up()
  await expect(page.getByRole('alert')).toContainText('本周任务已在其他页面更新')
  await expect.poll(() => page.getByRole('textbox', { name: '任务大类' }).evaluateAll(elements => elements.map(element => (element as HTMLInputElement).value))).toEqual(['第一项', '第二项', '第三项'])
})

test('周报汇总只读卡片不显示拖拽手柄', async ({ page }) => {
  const state = await setup(page)
  await page.getByRole('button', { name: /周报汇总/ }).click()
  await expect(page.locator('.task-row')).toHaveCount(3)
  await expect(page.locator('.task-drag-handle')).toHaveCount(0)
  expect(state.writes).toEqual([])
})
