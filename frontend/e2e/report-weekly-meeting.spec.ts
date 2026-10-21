import { test, expect } from '@playwright/test'
import { todayShanghai } from '../src/dates'

test('周报汇总按当天周会记录显示新增或修改入口，并可重新打开', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('用户名').fill('alice')
  await page.getByLabel('密码', { exact: true }).fill('e2e-password-123')
  await page.getByRole('button', { name: /进入工作台/ }).click()
  await expect(page.getByRole('heading', { name: '本周工作' })).toBeVisible()

  await page.getByRole('button', { name: /周报汇总/ }).click()
  const reportMeetingButton = page.locator('.sidebar-meeting')
  await expect(reportMeetingButton).toBeEnabled()
  const hasMeeting = /修改会议记录/.test(await reportMeetingButton.innerText())
  await reportMeetingButton.click()

  const dialog = page.getByRole('dialog', { name: hasMeeting ? '编辑会议记录' : '新增会议记录' })
  let content: string
  if (hasMeeting) {
    await expect(dialog.getByLabel('日期')).toHaveValue(todayShanghai())
    await expect(dialog.getByLabel('会议类型')).toHaveValue('周会')
    content = await dialog.getByLabel('会议内容').inputValue()
    await dialog.getByRole('button', { name: '取消' }).click()
  } else {
    await expect(dialog.getByLabel('会议类型')).toHaveValue('周会')
    await expect(dialog.getByLabel('日期')).toHaveValue(todayShanghai())
    await dialog.getByLabel('会议内容').fill('自动化测试周会记录')
    content = '自动化测试周会记录'
    await dialog.getByRole('button', { name: '保存会议记录' }).click()
    await expect(reportMeetingButton).toHaveText(/修改会议记录/)
  }

  await page.getByRole('button', { name: /本周工作/ }).click()
  await page.getByRole('button', { name: /周报汇总/ }).click()
  await expect(reportMeetingButton).toHaveText(/修改会议记录/)
  await reportMeetingButton.click()
  await expect(page.getByRole('dialog', { name: '编辑会议记录' }).getByLabel('会议内容')).toHaveValue(content)
})
