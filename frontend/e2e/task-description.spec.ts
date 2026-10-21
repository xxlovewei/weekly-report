import { test, expect } from '@playwright/test'
import packageInfo from '../package.json' with { type: 'json' }
import type { Task } from '../src/types'

test.beforeEach(async ({ page }) => {
  const tasks: Task[] = [{ id: 1, position: 1, category_name: null, task_group: '', description: '7、原有工作', status: null, work_days: [], notes: '' }]
  let revision = 0
  // Keep keyboard and autosave verification independent of business data.
  await page.route('**/api/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    let data: unknown
    if (path.endsWith('/auth/me')) {
      data = { user: { id: 1, username: 'test', display_name: '测试用户', role: 'user', is_active: true, status: '正常', must_change_password: false }, csrf_token: 'test-csrf' }
    } else if (path.endsWith('/categories') || path.endsWith('/calendar/marks')) {
      data = []
    } else if (/\/weeks\/\d{4}-\d{2}-\d{2}(\/tasks(\/\d+)?)?$/.test(path)) {
      if (request.method() === 'POST') {
        tasks.push({ id: tasks.length + 1, position: tasks.length + 1, category_name: null, task_group: '', description: '', status: null, work_days: [], notes: '' })
        revision++
      } else if (request.method() === 'PATCH') {
        Object.assign(tasks.find(task => task.id === Number(path.split('/').at(-1)))!, request.postDataJSON())
        revision++
      }
      data = { tasks, revision }
    } else {
      await route.fulfill({ status: 404, json: { detail: '测试未提供此接口' } })
      return
    }
    await route.fulfill({ json: data })
  })
  await page.goto('work')
  await expect(page.getByRole('heading', { name: '本周工作' })).toBeVisible()
  await expect(page.getByText(`当前版本：v${packageInfo.version}`)).toBeVisible()
})

test('新增与修改任务回车续编号并自动保存', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const existing = page.getByRole('textbox', { name: '任务描述' }).first()
  await existing.press('End')
  await existing.press('Enter')
  await existing.pressSequentially('继续工作')
  await expect(existing).toHaveValue('7、原有工作\n8、继续工作')
  await expect(page.getByText('✓ 已保存')).toBeVisible()
  await page.reload()
  await expect(existing).toHaveValue('7、原有工作\n8、继续工作')

  await page.getByRole('button', { name: /新增任务/ }).click()
  const added = page.getByRole('textbox', { name: '任务描述' }).nth(1)
  await added.fill('1. 开发')
  await added.press('End')
  await added.press('Enter')
  await added.pressSequentially('测试')
  await added.press('Enter')
  await expect(added).toHaveValue('1. 开发\n2. 测试\n3. ')
  expect(await added.evaluate(el => (el as HTMLTextAreaElement).selectionStart)).toBe(15)
  expect(await added.evaluate(el => el.clientHeight >= el.scrollHeight)).toBe(true)
  await expect(page.getByText('✓ 已保存')).toBeVisible()
  await page.reload()
  await expect(added).toHaveValue('1. 开发\n2. 测试\n3. ')
  await page.screenshot({ path: 'test-results/task-numbering.png', fullPage: true })
  expect(errors).toEqual([])
})

test('行中续号、选区替换、普通换行及输入法确认', async ({ page }) => {
  const description = page.getByRole('textbox', { name: '任务描述' })
  await description.fill('1. 接口联调\n9. 后续')
  await description.press('Control+Home')
  for (let i = 0; i < 5; i++) await description.press('ArrowRight')
  await description.press('Enter')
  await description.pressSequentially('补充')
  await expect(description).toHaveValue('1. 接口\n2. 补充联调\n9. 后续')

  await description.fill('1. 接口联调')
  await description.press('End')
  await description.press('Shift+ArrowLeft')
  await description.press('Shift+ArrowLeft')
  await description.press('Enter')
  await expect(description).toHaveValue('1. 接口\n2. ')

  await description.fill('普通文字')
  await description.press('End')
  await description.press('Enter')
  await expect(description).toHaveValue('普通文字\n')
  await description.fill('1. 内容')
  await description.press('End')
  await description.press('Shift+Enter')
  await expect(description).toHaveValue('1. 内容\n')

  await description.fill('1. 输入法')
  await description.dispatchEvent('keydown', { key: 'Enter', isComposing: true, bubbles: true, cancelable: true })
  await expect(description).toHaveValue('1. 输入法')
  await description.dispatchEvent('keydown', { key: 'Enter', keyCode: 229, bubbles: true, cancelable: true })
  await expect(description).toHaveValue('1. 输入法')
  const notes = page.getByRole('textbox', { name: '备注' })
  await notes.fill('1. 备注')
  await notes.press('End')
  await notes.press('Enter')
  await expect(notes).toHaveValue('1. 备注\n')
  await expect(page.getByText('✓ 已保存')).toBeVisible()
})
