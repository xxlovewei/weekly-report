import { test as base, type Page } from '@playwright/test'

export { expect } from '@playwright/test'

export async function skipGuides(page: Page) {
  for (const name of ['跳过引导', '关闭引导']) {
    await page.addLocatorHandler(page.getByRole('button', { name, exact: true }), button => button.click())
  }
}

export const test = base.extend({
  page: async ({ page }, use) => {
    // 业务用例直接进入工作台，引导交互由专用用例验证。
    await skipGuides(page)
    await use(page)
  },
})
