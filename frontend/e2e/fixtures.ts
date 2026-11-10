import { test as base } from '@playwright/test'

export { expect } from '@playwright/test'

export const test = base.extend({
  page: async ({ page }, use) => {
    // 业务用例直接进入工作台，侧栏引导的交互由专用用例验证。
    await page.addLocatorHandler(page.getByRole('button', { name: '跳过引导' }), button => button.click())
    await use(page)
  },
})
