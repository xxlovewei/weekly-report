import { test, expect, skipGuides } from './fixtures'
import { mondayOf, todayShanghai } from '../src/dates'
import type { LiveMessage, WeekData } from '../src/types'

test('消息中心在标题旁显示通知状态，并默认筛选未读消息', async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(Notification, 'permission', { value: 'granted' }))
  const user = { id: 3, role: 'user', display_name: '测试用户', must_change_password: false }
  await page.route('**/api/auth/me', route => route.fulfill({ json: { user, csrf_token: 'test' } }))
  await page.route('**/api/notifications/unread', route => route.fulfill({ json: { count: 1 } }))
  await page.route('**/api/notifications/stream*', route => route.abort())
  const created_at = '2026-11-16T01:30:00Z'
  const messages = [
    { id: 41, kind: '转交任务', title: '待查看的转交任务', is_read: false, created_at },
    { id: 42, kind: '代码审查', title: '已查看的审查日报', is_read: true, created_at },
  ]
  // 按实际请求的状态返回消息，覆盖默认筛选和手动切换。
  await page.route('**/api/notifications?*', route => {
    const filter = new URL(route.request().url()).searchParams.get('is_read')
    const items = messages.filter(message => filter === null || String(message.is_read) === filter)
    return route.fulfill({ json: { items, total: items.length } })
  })

  await page.goto('/messages')
  await expect(page.getByRole('heading', { name: '消息中心' }).locator('+ small')).toHaveText('已开启桌面通知')
  const filters = page.getByRole('region', { name: '消息筛选' })
  await expect(filters.getByText('已开启桌面通知')).toHaveCount(0)
  const status = filters.getByLabel('状态')
  await expect(status).toHaveValue('false')
  const rows = page.getByRole('article')
  await expect(rows).toHaveCount(1)
  const time = rows.first().locator('.review-tags > :first-child')
  await expect(time).toHaveAttribute('datetime', created_at)
  await expect(time).toHaveCSS('font-weight', '900')
  await expect(rows.first().locator('.status-tag')).toHaveText(['转交任务', '未读'])

  await status.selectOption('true')
  await expect(rows.first().locator('.status-tag')).toHaveText(['代码审查', '已读'])
  await status.selectOption('')
  await expect(rows).toHaveCount(2)
})

test('版本更新提醒无需桌面授权，稍后关闭，同一页签可刷新', async ({ page, context }) => {
  const user = { id: 3, role: 'user', display_name: '测试用户', must_change_password: false }
  let release: { version: string; message: string } | null = { version: '99.0.0', message: '旧版客户端提示文案' }
  await page.addInitScript(() => Object.defineProperty(Notification, 'permission', { value: 'denied' }))
  await page.route('**/api/auth/me', route => route.fulfill({ json: { user, csrf_token: 'test' } }))
  await page.route('**/api/notifications?*', route => route.fulfill({ json: { items: [], total: 0 } }))
  await page.route('**/api/notifications/unread', route => route.fulfill({ json: { count: 0 } }))
  let deliveries = 0
  await page.route('**/api/notifications/stream*', route => {
    deliveries++
    return route.fulfill({
      contentType: 'text/event-stream',
      body: `retry: 50\ndata: ${JSON.stringify({ release, count: 0, messages: [], unread_reminder: { enabled: false, interval_minutes: 5 } })}\n\n`,
    })
  })
  await page.setViewportSize({ width: 320, height: 720 })
  await page.goto('/messages#updates')
  const notice = page.getByRole('group', { name: '版本更新' })
  await expect(notice.getByText('有新版 v99.0.0 已就绪', { exact: true })).toBeVisible()
  await expect(notice.getByRole('button', { name: '刷新页面' })).toBeVisible()
  const viewport = page.viewportSize()!
  const bounds = (await notice.boundingBox())!
  expect(bounds.x).toBeGreaterThanOrEqual(0)
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(viewport.width)
  expect(bounds.y + bounds.height).toBeGreaterThan(viewport.height - 48)
  const firstDelivery = deliveries
  await notice.getByRole('button', { name: '稍后', exact: true }).click()
  await expect.poll(() => deliveries).toBeGreaterThan(firstDelivery)
  await expect(notice).toBeHidden()

  release = { version: '99.0.1', message: '旧版客户端提示文案' }
  await expect(notice.getByText('有新版 v99.0.1 已就绪', { exact: true })).toBeVisible()
  release = null
  const reloaded = page.waitForEvent('domcontentloaded')
  await notice.getByRole('button', { name: '刷新页面' }).click()
  await reloaded
  await expect(page).toHaveURL(/\/messages#updates$/)
  await expect(notice).toBeHidden()
  expect(context.pages()).toEqual([page])
})

test('发版桌面通知在多个页签只显示一次，点击回到系统并恢复右下角提示', async ({ page, context }) => {
  await context.addInitScript(() => {
    const state = Object.assign(window, { releaseNotices: [] as Notification[], releaseFocused: false })
    window.focus = () => { state.releaseFocused = true }
    window.Notification = class {
      static permission = 'granted'
      onclick: Notification['onclick'] = null
      body: string
      constructor(readonly title: string, { body }: NotificationOptions) {
        this.body = body || ''
        state.releaseNotices.push(this as unknown as Notification)
      }
      close() {}
    } as unknown as typeof Notification
  })
  const user = { id: 3, role: 'user', display_name: '测试用户', must_change_password: false }
  await context.route('**/api/auth/me', route => route.fulfill({ json: { user, csrf_token: 'test' } }))
  await context.route('**/api/notifications?*', route => route.fulfill({ json: { items: [], total: 0 } }))
  await context.route('**/api/notifications/unread', route => route.fulfill({ json: { count: 0 } }))
  await context.route('**/api/notifications/stream*', route => route.fulfill({
    contentType: 'text/event-stream',
    body: `retry: 50\ndata: ${JSON.stringify({ release: { version: '99.0.0' }, count: 0, messages: [], unread_reminder: { enabled: false, interval_minutes: 5 } })}\n\n`,
  }))
  const second = await context.newPage()
  const tabs = [page, second]
  await Promise.all(tabs.map(tab => tab.goto('/messages#release')))
  const notice = (tab: typeof page) => tab.getByRole('group', { name: '版本更新' })
  await Promise.all(tabs.map(tab => expect(notice(tab)).toBeVisible()))

  const desktopCounts = () => Promise.all(tabs.map(tab => tab.evaluate(() =>
    (window as unknown as { releaseNotices: Notification[] }).releaseNotices.length,
  )))
  await expect.poll(async () => (await desktopCounts()).reduce((sum, count) => sum + count, 0)).toBe(1)
  const recipient = tabs[(await desktopCounts()).indexOf(1)]
  await notice(recipient).getByRole('button', { name: '稍后', exact: true }).click()
  await expect(notice(recipient)).toBeHidden()
  const desktop = await recipient.evaluate(() => {
    const state = window as unknown as { releaseNotices: Notification[]; releaseFocused: boolean }
    const notification = state.releaseNotices[0]
    notification.onclick?.(new Event('click'))
    return { title: notification.title, body: notification.body, focused: state.releaseFocused }
  })
  expect(desktop).toEqual({ title: '🎉 周报系统已更新', body: 'v99.0.0 已就绪，点击返回周报系统查看更新提示。', focused: true })
  await expect(notice(recipient)).toHaveText(/有新版 v99\.0\.0 已就绪/)
  await expect(recipient).toHaveURL(/\/messages#release$/)
  expect(context.pages()).toHaveLength(2)
  expect((await desktopCounts()).reduce((sum, count) => sum + count, 0)).toBe(1)
})

test('发版检查派发同时展示桌面通知和站内提醒', async ({ page }) => {
  await page.addInitScript(() => {
    const state = Object.assign(window, { deploymentDesktopTitles: [] as string[] })
    window.Notification = class {
      static permission = 'granted'
      constructor(title: string) { state.deploymentDesktopTitles.push(title) }
      close() {}
    } as unknown as typeof Notification
  })
  const user = { id: 3, role: 'user', display_name: '测试用户', must_change_password: false }
  const message = { id: 99, kind: '发版检查', title: '项目 1.1.0 · 【北京局】核对配置', is_read: false, target: { board_task: 8 }, created_at: '2026-11-26T08:00:00Z' }
  await page.route('**/api/auth/me', route => route.fulfill({ json: { user, csrf_token: 'test' } }))
  await page.route('**/api/notifications/unread', route => route.fulfill({ json: { count: 1 } }))
  await page.route('**/api/notifications?*', route => route.fulfill({ json: { items: [message], total: 1 } }))
  await page.route('**/api/notifications/stream*', route => route.fulfill({ contentType: 'text/event-stream',
    body: `retry: 50\ndata: ${JSON.stringify({ count: 1, messages: [message], unread_reminder: { enabled: false } })}\n\n`,
  }))
  await page.goto('/messages')
  await expect(page.locator('.live-message-reminder').getByRole('button', { name: /发版检查.*核对配置/ })).toBeVisible()
  await expect.poll(() => page.evaluate(() => (window as unknown as { deploymentDesktopTitles: string[] }).deploymentDesktopTitles)).toEqual(['收到发版检查任务'])
  await page.getByRole('region', { name: '消息筛选' }).getByLabel('类型').selectOption('发版检查')
  await expect(page.getByRole('article').getByText(message.title)).toBeVisible()
})

test('未读轮询和即时消息按权限选择提醒，点击桌面通知后标记已读', async ({ page }) => {
  await page.addInitScript(() => {
    const state = Object.assign(window, {
      notificationPermission: 'default',
      desktopMessages: [] as Notification[],
      messageStream: new EventTarget(),
    })
    window.EventSource = function () {
      return Object.assign(state.messageStream, { close() {}, onmessage: null })
    } as unknown as typeof EventSource
    window.Notification = class {
      static get permission() { return state.notificationPermission }
      static async requestPermission() {
        if (!navigator.userActivation.isActive) throw new Error('missing user activation')
        return (state.notificationPermission = 'granted')
      }
      onclick: Notification['onclick'] = null
      body: string
      constructor(readonly title: string, options: NotificationOptions) {
        this.body = options.body || ''
        state.desktopMessages.push(this as unknown as Notification)
      }
      close() {}
    } as unknown as typeof Notification
  })

  const user = { id: 3, role: 'user', display_name: '测试用户', must_change_password: false }
  const unread: LiveMessage[] = [
    { id: 45, kind: '代码审查', title: '定时提醒的审查日报', is_read: false, target: { date: '2026-11-13' } },
    { id: 44, kind: '转交任务', title: '仍未阅读的转交任务', is_read: false },
  ]
  const marked: number[] = []
  await page.clock.install()
  await page.route('**/api/auth/me', route => route.fulfill({ json: { user, csrf_token: 'test' } }))
  await page.route('**/api/notifications/unread', route => route.fulfill({ json: { count: unread.length } }))
  await page.route('**/api/notifications?is_read=false', route => route.fulfill({ json: { items: unread, total: unread.length } }))
  await page.route(/\/api\/notifications\/\d+$/, route => {
    expect(route.request().method()).toBe('PATCH')
    expect(route.request().postDataJSON()).toEqual({ is_read: true })
    const id = Number(route.request().url().split('/').at(-1))
    marked.push(id)
    const index = unread.findIndex(message => message.id === id)
    if (index !== -1) unread.splice(index, 1)
    return route.fulfill({ json: { ok: true } })
  })

  await page.goto('/work')
  const prompt = page.getByRole('group', { name: '桌面通知权限' })
  await expect(prompt).toBeVisible()
  await prompt.getByRole('button', { name: '稍后再说' }).click()
  await expect(prompt).toBeHidden()
  await page.reload()
  await expect(prompt).toBeVisible()

  async function receive(id: number, unread_reminder = { enabled: true, interval_minutes: 5 }) {
    await page.evaluate(({ messageId, unread_reminder, count }) => {
      const stream = (window as unknown as { messageStream: EventSource }).messageStream
      stream.onmessage?.(new MessageEvent('message', { data: JSON.stringify({
        count, unread_reminder, messages: [{ id: messageId, kind: '代码审查', title: `审查日报 ${messageId}`, is_read: false, target: { date: '2026-11-12' } }],
      }) }))
    }, { messageId: id, unread_reminder, count: unread.length })
  }

  const toast = (id: number) => page.getByRole('button', { name: new RegExp(`审查日报 ${id}`) })
  await receive(41)
  await expect(toast(41)).toBeVisible()
  await page.getByRole('button', { name: '关闭新消息提醒' }).click()
  await receive(41)
  await expect(toast(41)).toBeHidden()

  const desktopNotifications = () => page.evaluate(() =>
    (window as unknown as { desktopMessages: Notification[] }).desktopMessages.map(({ title, body }) => ({ title, body })),
  )
  const clickDesktop = () => page.evaluate(() => {
    const notification = (window as unknown as { desktopMessages: Notification[] }).desktopMessages.at(-1)!
    notification.onclick?.(new Event('click'))
  })
  const reminder = page.getByRole('button', { name: /你有 2 条未读消息/ })
  await prompt.getByRole('button', { name: '稍后再说' }).click()
  await expect(reminder).toBeHidden()
  await page.clock.fastForward(5 * 60 * 1000)
  await expect(reminder).toBeVisible()
  await expect(prompt).toBeVisible()
  expect(await desktopNotifications()).toEqual([])
  await reminder.click()
  await expect(page).toHaveURL(/\/messages$/)
  await expect(reminder).toBeHidden()

  await prompt.getByRole('button', { name: '开启桌面通知' }).click()
  await expect(prompt).toBeHidden()
  await receive(42)
  const liveNotice = { title: expect.any(String), body: '审查日报 42' }
  await expect.poll(desktopNotifications).toEqual([liveNotice])
  await expect(toast(42)).toBeHidden()
  await clickDesktop()
  await expect(page).toHaveURL(/\/review-records\?date=2026-11-12$/)
  await expect.poll(() => marked).toEqual([42])

  await page.clock.fastForward(5 * 60 * 1000)
  const unreadNotice = { title: '你有 2 条未读消息', body: '定时提醒的审查日报' }
  await expect.poll(desktopNotifications).toEqual([liveNotice, unreadNotice])
  await expect(reminder).toBeHidden()
  await expect(prompt).toBeHidden()
  await clickDesktop()
  await expect(page).toHaveURL(/\/review-records\?date=2026-11-13$/)
  await expect.poll(() => marked).toEqual([42, 45])
  await expect(page.getByLabel('未读 1 条')).toBeVisible()

  // 权限从浏览器设置撤销后，下一次定时检查恢复站内提醒。
  await page.evaluate(() => { (window as unknown as { notificationPermission: string }).notificationPermission = 'denied' })
  await page.clock.fastForward(5 * 60 * 1000)
  await expect(page.getByRole('button', { name: /你有 1 条未读消息/ })).toBeVisible()
  await expect(prompt.getByText(/请在地址栏的站点设置中允许通知/)).toBeVisible()
  expect(await desktopNotifications()).toEqual([liveNotice, unreadNotice])

  const remainingReminder = page.getByRole('button', { name: /你有 1 条未读消息/ })
  // 在线关闭后清除站内提醒并停止定时扫描，即时消息仍然送达。
  await receive(46, { enabled: false, interval_minutes: 1 })
  await expect(toast(46)).toBeVisible()
  await page.clock.fastForward(5 * 60 * 1000)
  await expect(remainingReminder).toBeHidden()
  await receive(46, { enabled: true, interval_minutes: 1 })
  await page.clock.fastForward(60 * 1000)
  await expect(remainingReminder).toBeVisible()
})

test('真实任务转交通知通过消息流即时送达', async ({ page, browser, baseURL }) => {
  const sender = await browser.newContext({ baseURL })
  const senderPage = await sender.newPage()
  const week = mondayOf(todayShanghai())
  const weekPath = `/api/weeks/${week}`
  let taskId: number | undefined
  let boardTaskId: number | undefined
  let receiverHeaders: Record<string, string> | undefined
  let senderHeaders: Record<string, string> | undefined

  async function login(target: typeof page, username: string) {
    await target.goto('/login')
    await target.getByLabel('用户名').fill(username)
    const password = username === 'alice' ? process.env.E2E_ALICE_PASSWORD : process.env.E2E_BOB_PASSWORD
    await target.getByLabel('密码', { exact: true }).fill(password || 'e2e-password-123')
    const signedIn = target.waitForResponse(response => response.url().endsWith('/api/auth/login'))
    await target.getByRole('button', { name: '进入工作台 →', exact: true }).click()
    const response = await signedIn
    expect(response.status()).toBe(200)
    const { csrf_token, user } = await response.json()
    return { headers: { 'X-CSRF-Token': csrf_token as string }, user }
  }

  try {
    const ready = page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/api/notifications/stream') && response.ok())
    const bob = await login(page, 'bob')
    receiverHeaders = bob.headers
    await ready
    // 等待初始消息游标建立，避免把本次转交当成历史消息。
    await expect(page.getByRole('group', { name: '桌面通知权限' })).toBeVisible()
    await page.getByRole('button', { name: '任务看板', exact: true }).click()
    await expect(page.getByRole('region', { name: '任务箱' })).toBeVisible()
    const alice = await login(senderPage, 'alice')
    senderHeaders = alice.headers
    await skipGuides(senderPage)
    const original: WeekData = await (await sender.request.get(weekPath)).json()
    const created = await sender.request.post(`${weekPath}/tasks?revision=${original.revision}`, { headers: alice.headers })
    await expect(created).toBeOK()
    const updated: WeekData = await created.json()
    const task = updated.tasks[0]
    taskId = task.id
    const name = '看板接口交接'
    await expect(await sender.request.patch(`${weekPath}/tasks/${taskId}?revision=${updated.revision}`, {
      headers: alice.headers, data: { task_group: name, status: '30%' },
    })).toBeOK()
    await senderPage.goto('/task-board')
    const sourceCard = senderPage.locator(`#board-task-${task.board_task_id}`)
    await sourceCard.getByRole('button', { name: '转交任务' }).click()
    const transfer = senderPage.getByRole('dialog', { name: '转交任务' })
    await transfer.getByLabel('接收人').selectOption(String(bob.user.id))
    await transfer.getByRole('button', { name: '确认转交' }).click()
    await expect(sourceCard).toHaveCount(0)
    const toast = page.locator('.live-message-reminder').getByRole('button', { name: /转交任务/ })
    await expect(toast).toBeVisible()
    const read = page.waitForResponse(response => /\/api\/notifications\/\d+$/.test(response.url()) && response.request().method() === 'PATCH')
    await toast.click()
    expect((await read).status()).toBe(200)
    await expect(page).toHaveURL(/\/task-board\?task=\d+$/)
    const target = page.getByRole('region', { name: '任务箱' }).locator('.board-target')
    boardTaskId = Number(await target.getAttribute('data-card-id'))
    await expect(target).toContainText(name)
    const guide = page.getByRole('dialog', { name: '收到转交任务' })
    await expect(guide).toContainText(name)
    await expect(target).toHaveClass(/driver-active-element/)
    await guide.getByRole('button', { name: '完成' }).click()
    await expect(guide).toHaveCount(0)
  } finally {
    try {
      if (boardTaskId && receiverHeaders) {
        const board = await (await page.request.get('/api/board-tasks')).json()
        const card = board.tasks.find((item: { id: number }) => item.id === boardTaskId)
        if (card) await expect(await page.request.delete(
          `/api/board-tasks/${boardTaskId}?revision=${card.revision}&week_start=${board.current_week}`,
          { headers: receiverHeaders },
        )).toBeOK()
      }
      if (taskId) {
        for (const [request, headers] of [[sender.request, senderHeaders], [page.request, receiverHeaders]] as const) {
          if (!headers) continue
          const current: WeekData = await (await request.get(weekPath)).json()
          if (current.tasks.some(task => task.id === taskId)) {
            await expect(await request.delete(`${weekPath}/tasks/${taskId}?revision=${current.revision}`, { headers })).toBeOK()
          }
        }
      }
    } finally { await sender.close() }
  }
})
