import { expect, test as base, type Page } from '@playwright/test'
import type { User } from '../src/types'

export { expect }

export async function signIn(page: Page, username: 'alice' | 'bob') {
  await page.goto('/login')
  await page.getByLabel('用户名').fill(username)
  const password = username === 'alice' ? process.env.E2E_ALICE_PASSWORD : process.env.E2E_BOB_PASSWORD
  await page.getByLabel('密码', { exact: true }).fill(password || 'e2e-password-123')
  // 通过登录页面提交凭据，复用应用的加密登录流程。
  const signedIn = page.waitForResponse(response => response.url().endsWith('/api/auth/login'))
  await page.getByRole('button', { name: '进入工作台 →', exact: true }).click()
  const response = await signedIn
  expect(response.status()).toBe(200)
  const { csrf_token, user }: { csrf_token: string; user: User } = await response.json()
  await expect(page).toHaveURL(/\/work$/)
  return { headers: { 'X-CSRF-Token': csrf_token }, user }
}

export async function skipGuides(page: Page) {
  await page.addLocatorHandler(page.getByRole('button', { name: '跳过引导', exact: true }), button => button.click())
  const taskGuide = page.getByRole('dialog', { name: '任务卡片右键菜单', exact: true })
  await page.addLocatorHandler(taskGuide.getByRole('button', { name: '完成', exact: true }), button => button.click())
}

export const test = base.extend({
  page: async ({ page }, use) => {
    // 业务用例直接进入工作台，引导交互由专用用例验证。
    await skipGuides(page)
    await use(page)
  },
})
