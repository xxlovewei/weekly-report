import { expect, signIn, skipGuides, test } from './fixtures'
import type { WeekData } from '../src/types'

test('看板按条提示新任务，已提示的卡片再次进入时不重播', async ({ page }) => {
  const tasks = ['接口交接 <待核对>', '会议安排', '资料转交'].map((name, index) => ({
    id: index + 1, name, state: 'inbox', priority: '低', position: index,
    transferred_by: index === 1 ? null : '小王',
  }))
  const pending = tasks.map(task => ({
    id: task.id + 10, card_id: task.id, kind: task.id === 2 ? '会议指派' : '转交任务',
  }))
  const shown: number[] = []
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/auth/me')) return route.fulfill({ json: {
      user: { id: 20, username: 'member', display_name: '测试成员', role: 'user', must_change_password: false },
      csrf_token: 'test',
    } })
    if (path.endsWith('/board-tasks')) return route.fulfill({ json: {
      current_week: '2026-11-23', tasks, reminders: pending.filter(item => !shown.includes(item.id)),
    } })
    if (path.includes('/board-tasks/reminders/')) {
      shown.push(Number(path.split('/').at(-1)))
      return route.fulfill({ json: { ok: true } })
    }
    return route.fulfill({ json: [] })
  })

  await page.goto('/task-board?task=2')
  const meeting = page.getByRole('dialog', { name: '收到会议指派' })
  await expect(meeting).toContainText('会议安排')
  await expect(page.locator('#board-task-2')).toHaveClass(/driver-active-element/)
  await expect.poll(() => [...shown]).toEqual([12])
  await meeting.getByRole('button', { name: '关闭提醒' }).click()

  await page.goto('/task-board')
  const handoff = page.getByRole('dialog', { name: '收到转交任务' })
  await expect(handoff).toContainText('接口交接 <待核对>')
  await expect(page.locator('#board-task-1')).toHaveClass(/driver-active-element/)
  await handoff.getByRole('button', { name: '下一条' }).click()
  await expect(handoff).toContainText('资料转交')
  await expect(page.locator('#board-task-3')).toHaveClass(/driver-active-element/)
  await expect.poll(() => [...shown]).toEqual([12, 11, 13])
  await handoff.getByRole('button', { name: '完成' }).click()

  await page.goto('/task-board?task=2')
  await expect(page.locator('#board-task-2')).toBeFocused()
  await expect(meeting.or(handoff)).toHaveCount(0)
  expect(shown).toEqual([12, 11, 13])
})

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
  await expect(add.getByLabel('任务名称').and(add.locator('textarea'))).toBeVisible()
  await expect(add.getByLabel('备注').and(add.locator('textarea'))).toBeVisible()
  await add.getByLabel('任务名称').fill(name)
  await add.getByLabel('备注').fill('看板备注\n第二行')
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
  await expect(inbox.getByRole('article').filter({ hasText: /第一条看板卡片|第二条看板卡片/ }).first()).toContainText(secondName)
  await page.reload()
  await expect(inbox.getByRole('article').filter({ hasText: /第一条看板卡片|第二条看板卡片/ }).first()).toContainText(secondName)
  await second.dragTo(ongoing)
  const secondInProgress = ongoing.getByRole('article', { name: `${secondName}，优先级低` })
  await expect(secondInProgress).toBeVisible()
  const targetHeight = await secondInProgress.evaluate(element => element.getBoundingClientRect().height)
  await card.dragTo(secondInProgress, { targetPosition: { x: 25, y: targetHeight - 5 } })
  await expect(ongoing.getByText(name)).toBeVisible()
  await expect(ongoing.getByRole('article').filter({ hasText: /第一条看板卡片|第二条看板卡片/ }).first()).toContainText(name)

  await page.getByRole('button', { name: '本周工作', exact: true }).click()
  const detail = page.locator('.task-row').last()
  await expect(detail.getByLabel('任务名称')).toHaveValue(name)
  await expect(detail.getByLabel('备注')).toHaveValue('看板备注\n第二行')
  await detail.getByLabel('备注').fill('明细修改备注')
  await expect(detail.getByLabel('完成状态')).toHaveValue('5%')
  await detail.getByLabel('完成状态').selectOption('已完成')
  await expect(page.getByText('✓ 已保存')).toBeVisible()
  const boardLoaded = page.waitForResponse(response =>
    response.request().method() === 'GET' && new URL(response.url()).pathname === '/api/board-tasks')
  await page.getByRole('button', { name: '任务看板', exact: true }).click()
  // 已完成卡片隐藏操作按钮，备注同步通过看板接口确认。
  const { tasks } = await (await boardLoaded).json()
  expect(tasks).toContainEqual(expect.objectContaining({ name, state: 'done', notes: '明细修改备注' }))
  const completedCard = completed.getByRole('article', { name: `${name}，优先级高` })
  await expect(completedCard).toBeVisible()
  await expect(completedCard.locator('.board-card-actions')).toHaveCount(0)
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

test('新增和复制周任务同步到看板，删除当周明细保留卡片', async ({ page }) => {
  await signIn(page, 'alice')
  const name = `周任务同步 ${Date.now()}`
  const create = page.waitForResponse(response => response.request().method() === 'POST' &&
    /\/api\/weeks\/[^/]+\/tasks$/.test(new URL(response.url()).pathname))
  await page.getByRole('button', { name: '新增任务' }).click()
  const created: WeekData = await (await create).json()
  const original = created.tasks[0]
  expect(original.position).toBe(1)
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
  const copiedCard = page.getByRole('region', { name: '任务箱' }).getByRole('article', { name: `${name}，优先级低` })
  await expect(cards).toHaveCount(1)
  await expect(copiedCard).toHaveCount(1)

  await page.getByRole('button', { name: '本周工作', exact: true }).click()
  for (const id of [copied.id, original.id]) {
    const deleteButton = page.locator(`#work-task-${id}`).getByRole('button', { name: '删除', exact: true })
    await deleteButton.click()
    const dialog = page.getByRole('dialog', { name: '确认删除任务' })
    await expect(dialog).toContainText('该任务将从本周工作明细移除')
    await dialog.getByRole('button', { name: '确认删除' }).click()
    await expect(dialog).toHaveCount(0)
  }
  await page.getByRole('button', { name: '任务看板', exact: true }).click()
  await expect(page.getByRole('region', { name: '进行中' })).toBeVisible()
  await expect(cards).toHaveCount(1)
  await expect(copiedCard).toHaveCount(1)
  for (const card of [cards, copiedCard]) {
    await card.getByRole('button', { name: '删除任务' }).click()
    await page.getByRole('button', { name: '确认删除' }).click()
    await expect(card).toHaveCount(0)
  }
})

test('三个看板栏目随窗口限高，卡片列表独立滚动', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 780 })
  await page.context().grantPermissions(['notifications'])
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const columns = ['任务箱', '进行中', '已完成']
  const currentWeek = '2027-01-04'
  // 覆盖无记录的旧卡片、跨年的上周和更早分组。
  const completedWeeks = [null, '2026-12-21', '2026-12-28', ...Array<string>(21).fill(currentWeek)]
  const tasks = ['inbox', 'in_progress', 'done'].flatMap((state, column) =>
    Array.from({ length: 24 }, (_, position) => ({
      id: column * 24 + position + 1, name: `${columns[column]}任务 ${position + 1}`, state,
      category_name: '其他', priority: '低', position, revision: 0,
      has_current_detail: state !== 'inbox', has_other_details: false,
      completed_week: state === 'done' ? completedWeeks[position] : null,
    })),
  )
  const user = { id: 42, username: 'member', display_name: '测试成员', role: 'user', is_active: true, status: '正常', must_change_password: false }
  const submittedEstimates: unknown[] = []
  await page.route('**/api/**', route => {
    const { pathname } = new URL(route.request().url())
    if (pathname.endsWith('/auth/me')) return route.fulfill({ json: { user, csrf_token: 'test' } })
    if (pathname.endsWith('/board-tasks')) {
      if (route.request().method() === 'POST') {
        const fields = route.request().postDataJSON()
        submittedEstimates.push(fields.estimated_days)
        return route.fulfill({ status: 201, json: { ...tasks[0], ...fields, id: 100, position: 24 } })
      }
      return route.fulfill({ json: { current_week: currentWeek, tasks } })
    }
    return route.fulfill({ json: [] })
  })
  await page.goto('/task-board')
  const board = page.locator('.board')
  const lists = board.locator('.board-card-list')
  await expect(lists).toHaveCount(3)

  const columnSizes = () => board.locator('.board-column').evaluateAll(elements => elements.map(column => {
    const list = column.querySelector<HTMLElement>('.board-card-list')!
    return { height: column.clientHeight, visible: list.clientHeight, total: list.scrollHeight }
  }))
  const original = await columnSizes()
  const availableHeight = await board.evaluate(element => element.clientHeight)
  for (const size of original) {
    expect(size.height).toBeLessThanOrEqual(availableHeight)
    expect(size.total).toBeGreaterThan(size.visible)
  }

  const addButton = board.getByRole('button', { name: '添加任务' })
  await addButton.click()
  const addDialog = page.getByRole('dialog', { name: '添加任务' })
  const nameHint = '用尽量简短的一句话描述任务，一个任务工时尽量在5天以内，具体工作内容可写在备注中。'
  const nameField = addDialog.getByRole('textbox', { name: '任务名称', exact: true })
  await expect(nameField).toHaveAttribute('placeholder', nameHint)
  const hintColor = () => nameField.evaluate(element => getComputedStyle(element, '::placeholder').color)
  expect(await hintColor()).toBe('rgb(101, 107, 115)')
  await nameField.click()
  expect(await hintColor()).toBe('rgba(0, 0, 0, 0)')
  await nameField.fill('预估工时示例')
  await addDialog.getByLabel('任务类型').selectOption('其他')
  const estimateField = addDialog.getByRole('textbox', { name: '预估工时（人天）', exact: true })
  const priorityField = addDialog.getByRole('combobox', { name: '优先级', exact: true })
  const increase = addDialog.getByRole('button', { name: '增加 1 人天' })
  const decrease = addDialog.getByRole('button', { name: '减少 1 人天' })
  await expect(addDialog.getByText('人天', { exact: true })).toHaveCount(0)
  const estimateBox = (await estimateField.boundingBox())!
  const priorityBox = (await priorityField.boundingBox())!
  const increaseBox = (await increase.boundingBox())!
  expect(estimateBox.y).toBe(priorityBox.y)
  expect(estimateBox.x + estimateBox.width).toBeLessThan(priorityBox.x)
  expect(increaseBox.x + increaseBox.width).toBeLessThan(estimateBox.x + estimateBox.width)
  await expect(decrease).toBeDisabled()
  await increase.click()
  await expect(estimateField).toHaveValue('1')
  await expect(decrease).toBeDisabled()
  await estimateField.fill('0.125')
  await increase.click()
  await expect(estimateField).toHaveValue('1.125')
  await decrease.click()
  await expect(estimateField).toHaveValue('0.125')
  await expect(decrease).toBeDisabled()
  const save = addDialog.getByRole('button', { name: '保存' })
  for (const invalid of ['0', '-1', '无效', '1e2']) {
    await estimateField.fill(invalid)
    await save.click()
    await expect(addDialog.getByRole('alert')).toHaveText('预估工时须为大于 0 的整数或小数。')
    expect(submittedEstimates).toEqual([])
  }
  await estimateField.fill('0.5')
  await save.click()
  const newCard = board.getByRole('article', { name: '预估工时示例，优先级低' })
  await expect(newCard).toContainText('预估 0.5 人天')
  expect(submittedEstimates).toEqual(['0.5'])
  const buttonTop = (await addButton.boundingBox())!.y
  await lists.first().hover()
  await page.mouse.wheel(0, 600)
  await expect.poll(() => lists.first().evaluate(list => list.scrollTop)).toBeGreaterThan(0)
  expect(await lists.evaluateAll(elements => elements.slice(1).map(list => list.scrollTop))).toEqual([0, 0])
  expect(await board.evaluate(element => element.parentElement!.scrollTop)).toBe(0)
  expect((await addButton.boundingBox())!.y).toBe(buttonTop)
  await lists.first().getByRole('article').last().scrollIntoViewIfNeeded()
  await expect(lists.first().getByRole('article').last()).toBeInViewport()

  await page.setViewportSize({ width: 1440, height: 540 })
  const resized = await columnSizes()
  for (const [index, size] of resized.entries()) expect(size.height).toBeLessThan(original[index].height)

  const done = board.getByRole('region', { name: '已完成', exact: true })
  const thisWeek = done.getByRole('region', { name: '本周', exact: true })
  const lastWeek = done.getByRole('region', { name: '上周', exact: true })
  const earlier = done.getByRole('region', { name: '更早', exact: true })
  const history = done.getByRole('button', { name: '展开更多（2）' })
  await expect(thisWeek.getByRole('article')).toHaveCount(21)
  await expect(lastWeek.getByRole('article')).toContainText('已完成任务 3')
  await expect(earlier).toHaveCount(0)
  const meters = thisWeek.getByRole('meter', { name: '完成状态' })
  await expect(done.locator('.board-card-actions')).toHaveCount(0)
  await expect(meters.first()).toHaveText('100%')
  await expect(meters.first()).toHaveAttribute('aria-valuenow', '100')
  expect(await thisWeek.locator('.board-charge-fill').first().evaluate(fill =>
    Math.round(parseFloat(getComputedStyle(fill, '::before').width) / fill.getBoundingClientRect().width * 100),
  )).toBe(100)
  await history.click()
  await expect(earlier.getByRole('article')).toHaveCount(2)
  await expect(earlier.locator('.board-card-actions')).toHaveCount(0)
  await done.getByRole('button', { name: '收起更早任务' }).click()
  await expect(earlier).toHaveCount(0)

  await page.setViewportSize({ width: 390, height: 650 })
  const doneHeading = done.getByRole('heading', { name: '已完成', exact: true })
  await doneHeading.scrollIntoViewIfNeeded()
  await expect(doneHeading).toBeInViewport()
  await done.getByRole('article').last().scrollIntoViewIfNeeded()
  await expect(done.getByRole('article').last()).toBeInViewport()

  await page.goto('/task-board?task=50')
  await expect(earlier.getByRole('article', { name: '已完成任务 2，优先级低' })).toBeFocused()
})

test('进行中栏统一续做，电池显示各卡片的完成百分比', async ({ page }) => {
  const start = '2026-11-16'
  const tasks = [
    { id: 1, name: '接口联调与验收', status: '30%', priority: '高', has_current_detail: false },
    { id: 2, name: '采集数据清理', status: '70%', priority: '中', has_current_detail: false },
    { id: 3, name: '本周已有明细', status: '90%', priority: '低', has_current_detail: true },
    { id: 4, name: '接口联调与验收', status: null, priority: '高', has_current_detail: false },
  ].map((task, position) => ({ ...task, state: task.status ? 'in_progress' : 'inbox', category_name: '其他', position, revision: 0, has_other_details: false }))
  const user = { id: 42, username: 'member', display_name: '测试成员', role: 'user', is_active: true, status: '正常', must_change_password: false }
  let requests = 0
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/auth/me')) return route.fulfill({ json: { user, csrf_token: 'test' } })
    if (url.pathname.endsWith('/board-tasks')) return route.fulfill({ json: { current_week: start, tasks } })
    if (url.pathname.endsWith(`/weeks/${start}`)) return route.fulfill({ json: { revision: 8, tasks: [] } })
    if (url.pathname.endsWith(`/weeks/${start}/add-in-progress`)) {
      expect(route.request().method()).toBe('POST')
      expect(url.searchParams.get('revision')).toBe('8')
      requests++
      for (const task of tasks) task.has_current_detail = true
      return route.fulfill({ json: { revision: 9, tasks: [] } })
    }
    return route.fulfill({ json: [] })
  })
  await page.goto('/task-board')
  const ongoing = page.getByRole('region', { name: '进行中' })
  const inboxCard = page.getByRole('region', { name: '任务箱' }).getByRole('article').first()
  const ongoingCard = ongoing.getByRole('article').first()
  const expectSharedHeight = async () => {
    expect((await ongoingCard.boundingBox())?.height).toBe((await inboxCard.boundingBox())?.height)
  }
  const resume = ongoing.getByRole('button', { name: '添加到本周工作', exact: true })
  await expect(ongoing.getByRole('article').getByRole('button', { name: '添加到本周工作' })).toHaveCount(0)
  await expect(resume).toBeEnabled()
  await expectSharedHeight()
  const meter = ongoing.getByRole('meter', { name: '完成状态' })
  await expect(meter).toHaveText(['30%', '70%', '90%'])
  await expect(meter.nth(1)).toHaveAttribute('aria-valuenow', '70')
  const fillLayer = ongoing.locator('.board-charge-fill').nth(1)
  await expect.poll(() => fillLayer.evaluate(el => getComputedStyle(el, '::before').animationName)).toMatch(/^board-charge-in/)
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await expect.poll(() => fillLayer.evaluate(el => {
    const fill = getComputedStyle(el, '::before')
    return { width: Math.round(parseFloat(fill.width) / el.getBoundingClientRect().width * 100), animation: fill.animationName }
  })).toEqual({ width: 70, animation: 'none' })
  await resume.click()
  await expect(page.getByRole('status').filter({ hasText: '已将进行中的任务加入本周工作' })).toBeVisible()
  await expect(resume).toBeDisabled()
  expect(requests).toBe(1)
  await page.setViewportSize({ width: 390, height: 650 })
  await meter.first().scrollIntoViewIfNeeded()
  await expect(meter.first()).toBeInViewport()
  await expectSharedHeight()
})
