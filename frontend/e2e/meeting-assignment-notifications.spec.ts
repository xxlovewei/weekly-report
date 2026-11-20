import { test, expect, signIn, skipGuides } from './fixtures'
import { todayShanghai } from '../src/dates'

test('新增和编辑会议指派都会通知新增人员，消息和工作任务可跳转', async ({ page, browser, baseURL }) => {
  const { headers } = await signIn(page, 'alice')
  const receiver = await browser.newContext({ baseURL })
  const bob = await receiver.newPage()
  await skipGuides(bob)
  const date = todayShanghai()
  const content = `会议指派跳转 ${Date.now()}`
  const taskName = `${content}的任务`
  let meetingId: number | undefined

  try {
    const stream = bob.waitForResponse(response => new URL(response.url()).pathname.endsWith('/api/notifications/stream') && response.ok())
    await signIn(bob, 'bob')
    await stream
    await expect(bob.getByRole('group', { name: '桌面通知权限' })).toBeVisible()

    await page.getByRole('navigation').getByRole('button', { name: '会议记录' }).click()
    await page.getByRole('button', { name: '＋ 新增会议记录' }).click()
    const create = page.getByRole('dialog', { name: '新增会议记录' })
    await create.getByLabel('日期', { exact: true }).fill(date)
    await create.getByLabel('会议内容').fill(content)
    await create.getByLabel('是否需要跟踪完成情况').selectOption('true')
    await create.getByRole('button', { name: /添加任务/ }).click()
    await create.getByLabel('任务名称').fill(taskName)
    await create.getByRole('button', { name: '任务 1 指派人员' }).click()
    await page.getByRole('dialog', { name: '任务 1 指派人员' }).getByRole('checkbox', { name: '小李' }).check()
    const created = page.waitForResponse(response => response.url().endsWith('/api/meetings') && response.request().method() === 'POST')
    await create.getByRole('button', { name: '保存', exact: true }).click()
    const response = await created
    expect(response.status()).toBe(201)
    meetingId = (await response.json()).id
    await expect(create.getByRole('status')).toHaveText('会议记录已保存。')
    await create.locator('.modal-actions').getByRole('button', { name: '关闭' }).click()

    await expect(bob.locator('.live-message-reminder').getByRole('button', { name: new RegExp(taskName) })).toBeVisible()
    await bob.getByRole('button', { name: /消息中心/ }).click()
    await bob.getByRole('region', { name: '消息筛选' }).getByLabel('类型').selectOption('会议指派')
    const message = bob.locator('.message-row').filter({ hasText: taskName })
    await expect(message.locator('.message-kind')).toHaveText('会议指派')
    const marked = bob.waitForResponse(response => /\/api\/notifications\/\d+$/.test(response.url()) && response.request().method() === 'PATCH')
    await message.getByRole('button', { name: '跳转' }).click()
    expect((await marked).status()).toBe(200)
    await expect(bob).toHaveURL(/\/task-board\?task=\d+$/)
    const target = bob.getByRole('region', { name: '任务箱' }).locator('.board-target')
    await expect(target).toContainText(taskName)
    await expect(target).toBeFocused()
    const bobOngoing = bob.getByRole('region', { name: '进行中' })
    await target.dragTo(bobOngoing)
    await expect(bobOngoing.locator('.board-target')).toContainText(taskName)
    await bob.getByRole('navigation').getByRole('button', { name: '本周工作' }).click()
    const detail = bob.locator('.task-row').filter({ has: bob.getByRole('link', { name: /会议指派/ }) })
    await expect(detail.getByLabel('任务名称')).toHaveValue(taskName)
    const bulbText = `${date}会议指派，点击可跳转会议记录`
    const bulb = detail.getByRole('link', { name: bulbText })
    await expect(bulb).toHaveAttribute('title', bulbText)
    await bulb.click()
    await expect(bob).toHaveURL(new RegExp(`/meetings\\?meeting=${meetingId}$`))
    await expect(bob.locator('.meeting-card')).toHaveCount(1)
    await expect(bob.locator('.meeting-card')).toContainText(content)
    await bob.getByRole('button', { name: '返回会议列表' }).click()
    await expect(bob).toHaveURL(/\/meetings$/)

    const meeting = page.locator('.meeting-card').filter({ hasText: content })
    await meeting.getByRole('button', { name: '编辑' }).click()
    const edit = page.getByRole('dialog', { name: '编辑会议记录' })
    await edit.getByRole('button', { name: '任务 1 指派人员' }).click()
    await page.getByRole('dialog', { name: '任务 1 指派人员' }).getByRole('checkbox', { name: '小王' }).check()
    await edit.getByRole('button', { name: '保存', exact: true }).click()
    await expect(edit.getByRole('status')).toHaveText('会议记录已保存。')
    await edit.locator('.modal-actions').getByRole('button', { name: '关闭' }).click()
    await expect(page.locator('.live-message-reminder').getByRole('button', { name: new RegExp(taskName) })).toBeVisible()
    await page.locator('.live-message-reminder').getByRole('button', { name: new RegExp(taskName) }).click()
    const aliceTarget = page.getByRole('region', { name: '任务箱' }).locator('.board-target')
    await expect(aliceTarget.getByRole('link', { name: '查看指派会议' })).toBeVisible()
    const aliceOngoing = page.getByRole('region', { name: '进行中' })
    await aliceTarget.dragTo(aliceOngoing)
    await expect(aliceOngoing.locator('.board-target')).toContainText(taskName)
    await page.getByRole('navigation').getByRole('button', { name: '本周工作' }).click()
    const aliceDetail = page.locator('.task-row').filter({ has: page.getByRole('link', { name: bulbText }) })
    await expect(aliceDetail.getByLabel('任务名称')).toBeDisabled()
    await aliceDetail.getByLabel('本周任务进展').fill('仅本人填写的进展')
    await expect(page.getByText('✓ 已保存')).toBeVisible()
  } finally {
    try {
      if (meetingId) await expect(await page.request.delete(`/api/meetings/${meetingId}`, { headers })).toBeOK()
    } finally { await receiver.close() }
  }
})
