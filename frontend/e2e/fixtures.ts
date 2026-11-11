import { test as base, type Page } from '@playwright/test'

export { expect } from '@playwright/test'

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
