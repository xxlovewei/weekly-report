import { test, expect } from './fixtures'
import { mondayOf, todayShanghai } from '../src/dates'
import type { LiveMessage, WeekData } from '../src/types'

test('消息中心在标题旁显示通知状态，并默认筛选未读消息', async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(Notification, 'permission', { value: 'granted' }))
  const user = { id: 3, role: 'user', display_name: '测试用户', must_change_password: false }
  await page.route('**/api/auth/me', route => route.fulfill({ json: { user, csrf_token: 'test' } }))
  await page.route('**/api/notifications/unread', route => route.fulfill({ json: { count: 1 } }))
  await page.route('**/api/notifications/stream', route => route.abort())
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
    const ready = page.waitForResponse(response => response.url().endsWith('/api/notifications/stream') && response.ok())
    const bob = await login(page, 'bob')
    receiverHeaders = bob.headers
    await ready
    // 等待初始消息游标建立，避免把本次转交当成历史消息。
    await expect(page.getByRole('group', { name: '桌面通知权限' })).toBeVisible()
    const alice = await login(senderPage, 'alice')
    senderHeaders = alice.headers
    const original: WeekData = await (await sender.request.get(weekPath)).json()
    const created = await sender.request.post(`${weekPath}/tasks?revision=${original.revision}`, { headers: alice.headers })
    await expect(created).toBeOK()
    const updated: WeekData = await created.json()
    taskId = updated.tasks.at(-1)!.id
    const transferred = await sender.request.post(`${weekPath}/tasks/${taskId}/transfer?revision=${updated.revision}`, {
      headers: alice.headers, data: { user_id: bob.user.id },
    })
    await expect(transferred).toBeOK()
    const toast = page.locator('.live-message-reminder').getByRole('button', { name: /转交任务/ })
    await expect(toast).toBeVisible()
    const read = page.waitForResponse(response => /\/api\/notifications\/\d+$/.test(response.url()) && response.request().method() === 'PATCH')
    await toast.click()
    expect((await read).status()).toBe(200)
    await expect(page).toHaveURL(new RegExp(`task=${taskId}(?:&|$)`))
  } finally {
    try {
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
