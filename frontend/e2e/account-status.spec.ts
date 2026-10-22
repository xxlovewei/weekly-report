import { test, expect } from '@playwright/test'

test('管理员保存锁定状态并可解锁，新用户默认正常', async ({ page }) => {
  const admin = { id: 1, username: 'admin', display_name: '管理员', role: 'admin', is_active: true, status: '正常', must_change_password: false }
  let alice = { ...admin, id: 2, username: 'alice', display_name: '小王', role: 'user' }
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/auth/me')) return route.fulfill({ json: { user: admin, csrf_token: 'test' } })
    if (path.endsWith('/users/2') && route.request().method() === 'PATCH') {
      alice = { ...alice, ...route.request().postDataJSON() }
      return route.fulfill({ json: alice })
    }
    return route.fulfill({ json: path.endsWith('/users') ? [admin, alice] : [] })
  })
  await page.goto('/users')
  await expect(page.locator('.user-create').getByLabel('状态')).toHaveValue('正常')
  const row = page.locator('.user-row').filter({ has: page.locator('.user-header strong', { hasText: 'alice' }) })
  await expect(row.getByLabel('状态')).toHaveValue('正常')
  await row.getByLabel('状态').selectOption('锁定')
  await row.getByRole('button', { name: '保存资料' }).click()
  await expect(row.locator('.user-header span')).toHaveText('锁定')
  await row.getByLabel('状态').selectOption('正常')
  await row.getByRole('button', { name: '保存资料' }).click()
  await expect(row.locator('.user-header span')).toHaveText('正常')
  for (const width of [1440, 768, 320]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(row.getByLabel('状态')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  }
  expect(errors).toEqual([])
})

test('登录显示账号锁定提示', async ({ page }) => {
  await page.route('**/api/**', route => route.fulfill({ status: 401, json: { detail: '账号已锁定，请联系管理员。' } }))
  await page.goto('/login')
  await page.getByLabel('用户名').fill('alice')
  await page.getByLabel('密码', { exact: true }).fill('wrong-password')
  await page.getByRole('button', { name: '进入工作台' }).click()
  await expect(page.getByRole('alert')).toHaveText('账号已锁定，请联系管理员。')
  await expect(page).toHaveURL(/\/login$/)
})

test('只能创建普通用户，管理员角色和删除受限，删除后列表隐藏用户', async ({ page }) => {
  const admin = { id: 1, username: 'admin', display_name: '管理员', role: 'admin', is_active: true, status: '正常', must_change_password: false }
  const alice = { ...admin, id: 2, username: 'alice', display_name: '小王', role: 'user' }
  let users = [admin, alice]
  let createdRole: string | undefined
  let created = false
  let deleted = false
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/auth/me')) return route.fulfill({ json: { user: admin, csrf_token: 'test' } })
    if (path.endsWith('/users') && route.request().method() === 'POST') {
      created = true
      createdRole = route.request().postDataJSON().role
      return route.fulfill({ status: 201, json: { ...alice, id: 3, username: 'new' } })
    }
    if (path.endsWith('/users/2') && route.request().method() === 'DELETE') {
      deleted = true
      users = [admin]
      return route.fulfill({ json: { ok: true } })
    }
    return route.fulfill({ json: path.endsWith('/users') ? users : [] })
  })
  await page.goto('/users')
  const create = page.locator('.user-create')
  await expect(create.locator('label').filter({ hasText: '角色' })).toContainText('普通用户')
  const adminRow = page.locator('.user-row').filter({ hasText: 'admin' })
  await expect(adminRow.locator('label').filter({ hasText: '角色' })).toContainText('管理员')
  await expect(adminRow.getByRole('button', { name: '删除用户' })).toHaveCount(0)
  await create.getByLabel('用户名').fill('new')
  await create.getByLabel('显示姓名').fill('新人')
  await create.getByLabel('初始密码').fill('123456')
  await create.getByRole('button', { name: '创建用户' }).click()
  await expect.poll(() => created).toBe(true)
  expect(createdRole).toBeUndefined()
  page.once('dialog', dialog => dialog.accept())
  await page.locator('.user-row').filter({ hasText: 'alice' }).getByRole('button', { name: '删除用户' }).click()
  await expect(page.locator('.user-row').filter({ hasText: 'alice' })).toHaveCount(0)
  expect(deleted).toBe(true)
})
