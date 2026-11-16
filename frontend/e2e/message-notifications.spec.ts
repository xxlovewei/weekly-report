import { test, expect } from './fixtures'
import { mondayOf, todayShanghai } from '../src/dates'
import type { WeekData } from '../src/types'

test('登录和刷新时检查权限，新消息同时支持站内和桌面通知', async ({ page }) => {
  await page.addInitScript(() => {
    const state = Object.assign(window, {
      notificationPermission: 'default',
      desktopMessages: [] as string[],
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
      constructor(_title: string, options: NotificationOptions) { state.desktopMessages.push(options.body || '') }
      close() {}
    } as unknown as typeof Notification
  })

  const user = { id: 3, role: 'user', display_name: '测试用户', must_change_password: false }
  await page.route('**/api/auth/me', route => route.fulfill({ json: { user, csrf_token: 'test' } }))
  await page.route('**/api/notifications/42', route => route.fulfill({ json: { ok: true } }))

  await page.goto('/work')
  const prompt = page.getByRole('group', { name: '桌面通知权限' })
  await expect(prompt).toBeVisible()
  await prompt.getByRole('button', { name: '稍后再说' }).click()
  await expect(prompt).toBeHidden()
  await page.reload()
  await expect(prompt).toBeVisible()

  async function receive(id: number) {
    await page.evaluate(messageId => {
      const stream = (window as unknown as { messageStream: EventSource }).messageStream
      stream.onmessage?.(new MessageEvent('message', { data: JSON.stringify({
        count: 1, messages: [{ id: messageId, kind: '代码审查', title: `审查日报 ${messageId}`, is_read: false, target: { date: '2026-11-12' } }],
      }) }))
    }, id)
  }

  const toast = (id: number) => page.getByRole('button', { name: new RegExp(`审查日报 ${id}`) })
  await receive(41)
  await expect(toast(41)).toBeVisible()
  await page.getByRole('button', { name: '关闭新消息提醒' }).click()
  await receive(41)
  await expect(toast(41)).toBeHidden()

  await prompt.getByRole('button', { name: '开启桌面通知' }).click()
  await expect(prompt).toBeHidden()
  await receive(42)
  await expect(toast(42)).toBeVisible()
  await expect.poll(() => page.evaluate(() => (window as unknown as { desktopMessages: string[] }).desktopMessages)).toEqual(['审查日报 42'])
  const marked = page.waitForRequest(request => request.url().endsWith('/api/notifications/42') && request.method() === 'PATCH')
  await toast(42).click()
  await expect(page).toHaveURL(/\/review-records\?date=2026-11-12$/)
  expect((await marked).postDataJSON()).toEqual({ is_read: true })
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
