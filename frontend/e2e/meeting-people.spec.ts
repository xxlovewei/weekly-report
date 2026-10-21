import { test, expect } from '@playwright/test'

test('会议列表显示创建人和多个更新人，并兼容历史记录与窄屏', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const alice = { id: 2, username: 'alice', display_name: '小王' }
  const bob = { id: 3, username: 'bob', display_name: '很长的更新人姓名'.repeat(12) }
  const meeting = { id: 1, meeting_date: '2026-10-14', meeting_type: '例会', content: '会议内容', needs_follow_up: false, tasks: [], creator: alice, updaters: [alice, bob] }
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    const json = path.endsWith('/auth/me')
      ? { user: { ...alice, role: 'user', is_active: true, must_change_password: false }, csrf_token: 'test' }
      : path.endsWith('/meetings')
        ? { items: [meeting, { ...meeting, id: 2, creator: null, updaters: [] }], total: 2, page: 1, page_size: 10 }
        : []
    await route.fulfill({ json })
  })
  await page.goto('/meetings')
  const cards = page.locator('.meeting-card')
  await expect(cards).toHaveCount(2)
  await expect(cards.first().locator('.meeting-person').first()).toHaveText('创建人：小王')
  await expect(cards.first().locator('.meeting-person').last()).toHaveText(`更新人：小王、${bob.display_name}`)
  await expect(cards.last().locator('.meeting-person').first()).toHaveText('创建人：未知')
  await expect(cards.last().locator('.meeting-person').last()).toHaveText('更新人：暂无')
  for (const width of [1440, 1024, 768, 320]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(cards.first().locator('.meeting-person').last()).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  }
  await page.screenshot({ path: 'test-results/meeting-people.png', fullPage: true })
  expect(errors).toEqual([])
})
