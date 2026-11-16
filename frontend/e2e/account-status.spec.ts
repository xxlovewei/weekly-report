import { test, expect } from './fixtures'
import { createDecipheriv, generateKeyPairSync, privateDecrypt } from 'node:crypto'

test('管理员保存锁定状态并可解锁，新用户默认正常', async ({ page }) => {
  await page.addLocatorHandler(page.getByRole('button', { name: '稍后再说', exact: true }), button => button.click())
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
  const { publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 })
  const key = publicKey.export({ type: 'spki', format: 'der' }).toString('base64')
  await page.route('**/api/**', route => route.request().url().endsWith('/auth/public-key')
    ? route.fulfill({ json: { key } })
    : route.fulfill({ status: 401, json: { detail: '账号已锁定，请联系管理员。' } }))
  await page.goto('/login')
  await page.getByLabel('用户名').fill('alice')
  await page.getByLabel('密码', { exact: true }).fill('wrong-password')
  await page.getByRole('button', { name: '进入工作台' }).click()
  await expect(page.getByRole('alert')).toHaveText('账号已锁定，请联系管理员。')
  await expect(page).toHaveURL(/\/login$/)
})

test('新增和编辑支持多个角色，移除管理员角色后可删除用户', async ({ page }) => {
  await page.addLocatorHandler(page.getByRole('button', { name: '稍后再说', exact: true }), button => button.click())
  const { publicKey, privateKey } = generateKeyPairSync('rsa', { modulusLength: 2048 })
  const key = publicKey.export({ type: 'spki', format: 'der' }).toString('base64')
  const admin = { id: 1, username: 'admin', display_name: '管理员', role: 'admin', roles: ['admin'], is_active: true, status: '正常', must_change_password: false }
  const alice = { ...admin, id: 2, username: 'alice', display_name: '小王', roles: ['admin', 'user'] }
  let users = [admin, alice]
  let createdRoles: string[] | undefined
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/auth/me')) return route.fulfill({ json: { user: admin, csrf_token: 'test' } })
    if (path.endsWith('/auth/public-key')) return route.fulfill({ json: { key } })
    if (path.endsWith('/users') && route.request().method() === 'POST') {
      const encrypted = route.request().postDataJSON()
      const aesKey = privateDecrypt({ key: privateKey, oaepHash: 'sha256' }, Buffer.from(encrypted.key, 'base64'))
      const data = Buffer.from(encrypted.data, 'base64')
      const decipher = createDecipheriv('aes-256-gcm', aesKey, Buffer.from(encrypted.iv, 'base64'))
      decipher.setAAD(Buffer.from('/users'))
      decipher.setAuthTag(data.subarray(-16))
      const payload: { username: string; roles: string[] } = JSON.parse(Buffer.concat([
        decipher.update(data.subarray(0, -16)), decipher.final(),
      ]).toString())
      createdRoles = payload.roles
      const newcomer = { ...alice, id: 3, username: payload.username, roles: payload.roles }
      users = [...users, newcomer]
      return route.fulfill({ status: 201, json: newcomer })
    }
    if (path.endsWith('/users/2') && route.request().method() === 'PATCH') {
      const update = route.request().postDataJSON()
      const updated = { ...alice, ...update, role: 'user' }
      users = users.map(item => item.id === 2 ? updated : item)
      return route.fulfill({ json: updated })
    }
    if (path.endsWith('/users/2') && route.request().method() === 'DELETE') {
      users = users.filter(item => item.id !== 2)
      return route.fulfill({ json: { ok: true } })
    }
    return route.fulfill({ json: path.endsWith('/users') ? users : [] })
  })
  await page.goto('/users')
  const create = page.locator('.user-create')
  await expect(create.getByRole('checkbox', { name: '普通用户' })).toBeChecked()
  await create.getByRole('checkbox', { name: '管理员' }).check()
  await create.getByLabel('用户名').fill('new')
  await create.getByLabel('显示姓名').fill('新人')
  await create.getByLabel('初始密码').fill('123456')
  await create.getByRole('button', { name: '创建用户' }).click()
  const newcomer = page.locator('.user-row').filter({ hasText: 'new' })
  await expect(newcomer.getByRole('checkbox', { name: '普通用户' })).toBeChecked()
  await expect(newcomer.getByRole('checkbox', { name: '管理员' })).toBeChecked()
  expect(createdRoles).toEqual(['user', 'admin'])
  await expect(create.getByRole('checkbox', { name: '管理员' })).not.toBeChecked()

  const aliceRow = page.locator('.user-row').filter({ hasText: 'alice' })
  await expect(aliceRow.getByRole('button', { name: '删除用户' })).toHaveCount(0)
  await aliceRow.getByRole('checkbox', { name: '管理员' }).uncheck()
  await aliceRow.getByRole('button', { name: '保存资料' }).click()
  page.once('dialog', dialog => dialog.accept())
  await aliceRow.getByRole('button', { name: '删除用户' }).click()
  await expect(aliceRow).toHaveCount(0)
})
