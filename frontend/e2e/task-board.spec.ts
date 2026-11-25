import { expect, signIn, skipGuides, test } from './fixtures'
import type { WeekData } from '../src/types'

test('个人看板拖拽与明细双向同步，管理员可以代管明细', async ({ page, browser, baseURL }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await signIn(page, 'alice')
  await page.getByRole('button', { name: '任务看板', exact: true }).click()
  const inbox = page.getByRole('region', { name: '任务箱' })
  const ongoing = page.getByRole('region', { name: '进行中' })
  const completed = page.getByRole('region', { name: '已完成' })
  const name = '第一条看板卡片'
  await inbox.getByRole('button', { name: '添加任务' }).click()
  const add = page.getByRole('dialog', { name: '添加任务' })
  await add.getByLabel('任务名称').fill(name)
  await add.getByLabel('任务类型').selectOption('联调联试')
  await add.getByLabel('优先级').selectOption('高')
  await add.getByRole('button', { name: '保存' }).click()
  await expect(inbox.getByText(name)).toBeVisible()
  const card = inbox.getByRole('article', { name: `${name}，优先级高` })
  await expect(card.getByRole('combobox')).toHaveCount(0)
  const height = await card.evaluate(element => element.getBoundingClientRect().height)
  const secondName = '第二条看板卡片'
  await inbox.getByRole('button', { name: '添加任务' }).click()
  await add.getByLabel('任务名称').fill(secondName)
  await add.getByLabel('任务类型').selectOption('其他')
  await add.getByRole('button', { name: '保存' }).click()
  const second = inbox.getByRole('article', { name: `${secondName}，优先级低` })
  await expect(second).toBeVisible()
  expect(await card.evaluate(element => element.getBoundingClientRect().height)).toBe(height)
  await second.dragTo(card, { targetPosition: { x: 25, y: 5 } })
  await expect(inbox.getByRole('article').first()).toContainText(secondName)
  await page.reload()
  await expect(inbox.getByRole('article').first()).toContainText(secondName)
  await second.dragTo(ongoing)
  const secondInProgress = ongoing.getByRole('article', { name: `${secondName}，优先级低` })
  await expect(secondInProgress).toBeVisible()
  const targetHeight = await secondInProgress.evaluate(element => element.getBoundingClientRect().height)
  await card.dragTo(secondInProgress, { targetPosition: { x: 25, y: targetHeight - 5 } })
  await expect(ongoing.getByText(name)).toBeVisible()
  await expect(ongoing.getByRole('article').first()).toContainText(name)

  await page.getByRole('button', { name: '本周工作', exact: true }).click()
  const detail = page.locator('.task-row').last()
  await expect(detail.getByLabel('任务名称')).toHaveValue(name)
  await expect(detail.getByLabel('完成状态')).toHaveValue('5%')
  await detail.getByLabel('完成状态').selectOption('已完成')
  await expect(page.getByText('✓ 已保存')).toBeVisible()
  await page.getByRole('button', { name: '任务看板', exact: true }).click()
  await expect(completed.getByText(name)).toBeVisible()
  await page.reload()
  await expect(completed.getByText(name)).toBeVisible()

  const admin = await browser.newContext({ baseURL })
  try {
    const manager = await admin.newPage()
    await skipGuides(manager)
    await manager.goto('/login')
    await manager.getByLabel('用户名').fill('admin')
    await manager.getByLabel('密码', { exact: true }).fill('e2e-password-123')
    await manager.getByRole('button', { name: /进入工作台/ }).click()
    await manager.getByRole('tab', { name: '小王' }).click()
    await expect(manager.getByRole('button', { name: '新增任务' })).toHaveCount(0)
    const memberDetail = manager.locator('.task-row').last()
    await expect(memberDetail.getByLabel('任务名称')).toHaveValue(name)
    await memberDetail.getByLabel('完成状态').selectOption('30%')
    await expect(manager.getByText('✓ 已保存')).toBeVisible()
  } finally { await admin.close() }

  await page.reload()
  await expect(ongoing.getByText(name)).toBeVisible()
  await ongoing.getByRole('article', { name: `${name}，优先级高` }).dragTo(inbox)
  await page.getByRole('button', { name: '确认移回' }).click()
  const returned = inbox.getByRole('article', { name: `${name}，优先级高` })
  await expect(returned).toBeVisible()
  await returned.getByRole('button', { name: '删除任务' }).click()
  await page.getByRole('button', { name: '确认删除' }).click()
  await expect(returned).toHaveCount(0)
  expect(errors).toEqual([])
})

test('新增和复制周任务同步到看板，删除当周任务同步移除卡片', async ({ page }) => {
  await signIn(page, 'alice')
  const name = `周任务同步 ${Date.now()}`
  const create = page.waitForResponse(response => response.request().method() === 'POST' &&
    /\/api\/weeks\/[^/]+\/tasks$/.test(new URL(response.url()).pathname))
  await page.getByRole('button', { name: '新增任务' }).click()
  const created: WeekData = await (await create).json()
  const original = created.tasks.at(-1)!
  const added = page.locator(`#work-task-${original.id}`)
  await added.getByLabel('任务名称').fill(name)
  await added.getByLabel('完成状态').selectOption('40%')
  await expect(page.getByText('✓ 已保存')).toBeVisible()
  const duplicate = page.waitForResponse(response => response.request().method() === 'POST' &&
    new URL(response.url()).pathname.endsWith(`/tasks/${original.id}/duplicate`))
  await added.getByRole('button', { name: '复制一行' }).click()
  const response: WeekData = await (await duplicate).json()
  const copied = response.tasks[response.tasks.findIndex(task => task.id === original.id) + 1]
  expect(copied.board_task_id).not.toBe(original.board_task_id)
  await expect(page.locator(`#work-task-${copied.id}`).getByLabel('任务名称')).toHaveValue(name)

  await page.getByRole('button', { name: '任务看板', exact: true }).click()
  const cards = page.getByRole('region', { name: '进行中' }).getByRole('article', { name: `${name}，优先级低` })
  await expect(cards).toHaveCount(2)

  await page.getByRole('button', { name: '本周工作', exact: true }).click()
  for (const id of [copied.id, original.id]) {
    const deleteButton = page.locator(`#work-task-${id}`).getByRole('button', { name: '删除', exact: true })
    await deleteButton.click()
    const dialog = page.getByRole('dialog', { name: '确认删除任务' })
    await expect(dialog).toContainText('本周明细和看板任务都将删除')
    await dialog.getByRole('button', { name: '确认删除' }).click()
    await expect(dialog).toHaveCount(0)
  }
  await page.getByRole('button', { name: '任务看板', exact: true }).click()
  await expect(page.getByRole('region', { name: '进行中' })).toBeVisible()
  await expect(cards).toHaveCount(0)
})
