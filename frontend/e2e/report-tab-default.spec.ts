import { test, expect } from '@playwright/test'

test('进入周报汇总时选中用户保存顺序的首个姓名并加载其周报', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('用户名').fill('alice')
  await page.getByLabel('密码', { exact: true }).fill('e2e-password-123')
  await page.getByRole('button', { name: /进入工作台/ }).click()
  await expect(page.getByRole('heading', { name: '本周工作' })).toBeVisible()

  const membersResponse = page.waitForResponse(response => /\/api\/reports\/\d{4}-\d{2}-\d{2}$/.test(response.url()))
  await page.getByRole('button', { name: /周报汇总/ }).click()
  const members: { id: number; name: string }[] = await (await membersResponse).json()
  const tabs = page.getByRole('tab')
  await expect(tabs).toHaveCount(2)

  const originalFirst = await tabs.nth(0).innerText()
  const originalSecond = await tabs.nth(1).innerText()
  await tabs.nth(1).dragTo(tabs.nth(0), { targetPosition: { x: 1, y: 20 } })
  await expect(tabs.nth(0)).toContainText(originalSecond)

  const firstOrderedName = (await tabs.nth(0).innerText()).trim()
  await page.getByRole('button', { name: /本周工作/ }).click()
  const requestedReport = page.waitForRequest(request => /\/api\/reports\/\d{4}-\d{2}-\d{2}\/users\/\d+$/.test(request.url()))
  await page.getByRole('button', { name: /周报汇总/ }).click()
  const request = await requestedReport

  await expect(page.locator('[role="tab"][aria-selected="true"]')).toContainText(firstOrderedName)
  const expectedMember = members.find(member => member.name === firstOrderedName)
  expect(expectedMember).toBeTruthy()
  expect(Number(request.url().match(/\/users\/(\d+)$/)?.[1])).toBe(expectedMember!.id)
  expect(firstOrderedName).not.toBe(originalFirst)
})
