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
  await expect(description).toHaveValue('1. 内容\n   ')

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

test('中间插入重排与撤销重做是一组操作', async ({ page }) => {
  const description = page.getByRole('textbox', { name: '任务描述' })
  await description.fill('1. A\n2. B\n3. C')
  await description.evaluate(el => (el as HTMLTextAreaElement).setSelectionRange(4, 4))
  await description.press('Enter')
  await expect(description).toHaveValue('1. A\n2. \n3. B\n4. C')
  await description.press('Control+z')
  await expect(description).toHaveValue('1. A\n2. B\n3. C')
  expect(await description.evaluate(el => (el as HTMLTextAreaElement).selectionStart)).toBe(4)
  await description.press('Control+Shift+z')
  await expect(description).toHaveValue('1. A\n2. \n3. B\n4. C')
  await page.getByRole('button', { name: '撤销', exact: true }).click()
  await expect(description).toHaveValue('1. A\n2. B\n3. C')
  await page.getByRole('button', { name: '重做', exact: true }).click()
  await expect(description).toHaveValue('1. A\n2. \n3. B\n4. C')
  await expect(page.getByText('✓ 已保存')).toBeVisible()
  await page.reload()
  await expect(description).toHaveValue('1. A\n2. \n3. B\n4. C')
  await expect(page.getByRole('button', { name: '撤销', exact: true })).toBeDisabled()
})

test('删除、剪切及边界粘贴只维护原连续组', async ({ page, context }) => {
  const clipboardAvailable = await page.evaluate(() => !!navigator.clipboard)
  if (clipboardAvailable) await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  const description = page.getByRole('textbox', { name: '任务描述' })
  await description.fill('5. A\n6. B\n7. C\n说明\n1、D')
  await description.evaluate(el => (el as HTMLTextAreaElement).setSelectionRange(5, 10))
  await description.press('Control+x')
  await expect(description).toHaveValue('5. A\n6. C\n说明\n1、D')
  if (clipboardAvailable) {
    expect((await page.evaluate(() => navigator.clipboard.readText())).replace(/\r\n/g, '\n')).toBe('6. B\n')
    await page.evaluate(() => navigator.clipboard.writeText('1. X\n2. Y'))
  }
  await description.evaluate(el => (el as HTMLTextAreaElement).setSelectionRange(5, 5))
  if (clipboardAvailable) await description.press('Control+v')
  else await description.evaluate(el => {
    // LAN HTTP has no Clipboard API; exercise the same paste event without changing browser security.
    const transfer = new DataTransfer()
    transfer.setData('text/plain', '1. X\n2. Y')
    el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: transfer, bubbles: true, cancelable: true }))
  })
  await expect(description).toHaveValue('5. A\n6. X\n7. Y\n8. C\n说明\n1、D')
  await description.press('Control+z')
  await expect(description).toHaveValue('5. A\n6. C\n说明\n1、D')
  await description.evaluate(el => (el as HTMLTextAreaElement).setSelectionRange(5, 5))
  await description.press('Backspace')
  await expect(description).toHaveValue('5. AC\n说明\n1、D')
})

test('项内续行与空项保持同组，手动改号保留', async ({ page }) => {
  const description = page.getByRole('textbox', { name: '任务描述' })
  await description.fill('1. A\n2. B')
  await description.evaluate(el => (el as HTMLTextAreaElement).setSelectionRange(4, 4))
  await description.press('Shift+Enter')
  await description.pressSequentially('补充')
  await description.press('Enter')
  await description.press('Enter')
  await expect(description).toHaveValue('1. A\n   补充\n2. \n3. \n4. B')
  await description.fill('1. A\n2. B\n3. C')
  await description.evaluate(el => (el as HTMLTextAreaElement).setSelectionRange(5, 6))
  await description.pressSequentially('7')
  await expect(description).toHaveValue('1. A\n7. B\n3. C')
})

test('组合输入只提交一次，可整体撤销', async ({ page }) => {
  const description = page.getByRole('textbox', { name: '任务描述' })
  await description.fill('1. ')
  await expect(page.getByText('✓ 已保存')).toBeVisible()
  const patches: string[] = []
  page.on('request', request => { if (request.method() === 'PATCH') patches.push(request.postDataJSON().description) })
  await description.dispatchEvent('compositionstart')
  await description.fill('1. 中')
  await description.fill('1. 中文')
  expect(patches).toEqual([])
  await description.dispatchEvent('compositionend')
  await expect(page.getByText('✓ 已保存')).toBeVisible()
  expect(patches).toEqual(['1. 中文'])
  await description.press('Control+z')
  await expect(description).toHaveValue('1. ')
})

test('5000字符超限拒绝整次操作，撤销历史按任务隔离', async ({ page }) => {
  const first = page.getByRole('textbox', { name: '任务描述' }).first()
  await first.fill('1. ' + 'A'.repeat(4997))
  await first.press('End')
  await first.press('Enter')
  await expect(first).toHaveValue('1. ' + 'A'.repeat(4997))
  await expect(page.getByRole('alert')).toContainText('本次操作未应用')
  await first.fill('😀'.repeat(5000))
  await expect(first).toHaveValue('😀'.repeat(5000))
  await first.fill('原任务')
  await page.getByRole('button', { name: /新增任务/ }).click()
  const second = page.getByRole('textbox', { name: '任务描述' }).nth(1)
  await second.fill('新任务')
  await second.press('Control+z')
  await expect(second).toHaveValue('')
  await expect(first).toHaveValue('原任务')
})

test('保存失败重试保持重排文本和撤销能力，窄屏无溢出', async ({ page }) => {
  let fail = true
  await page.route('**/api/weeks/**', async route => {
    if (route.request().method() === 'PATCH' && fail) {
      fail = false
      await route.fulfill({ status: 500, json: { detail: '保存暂时失败' } })
    } else await route.fallback()
  })
  const description = page.getByRole('textbox', { name: '任务描述' })
  await description.fill('1. A\n2. B')
  await description.evaluate(el => (el as HTMLTextAreaElement).setSelectionRange(4, 4))
  await description.press('Enter')
  await expect(page.getByText('! 保存失败')).toBeVisible()
  await expect(description).toHaveValue('1. A\n2. \n3. B')
  await page.getByRole('button', { name: '重试', exact: true }).click()
  await expect(page.getByText('✓ 已保存')).toBeVisible()
  await description.press('Control+z')
  await expect(description).toHaveValue('1. A\n2. B')
  await page.setViewportSize({ width: 320, height: 800 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  await expect(page.getByRole('button', { name: '撤销', exact: true })).toBeVisible()
  await page.screenshot({ path: 'test-results/task-description-mobile.png', fullPage: true })
})

test('真实拖放整项移动只记录一次，可撤销', async ({ page }) => {
  const description = page.getByRole('textbox', { name: '任务描述' })
  await description.fill('1. A\n2. B\n3. C')
  await description.focus()
  await description.evaluate(el => (el as HTMLTextAreaElement).setSelectionRange(5, 10))
  const points = await description.evaluate(el => {
    const rect = el.getBoundingClientRect(), style = getComputedStyle(el)
    const canvas = document.createElement('canvas'), ctx = canvas.getContext('2d')!
    ctx.font = style.font
    const x = rect.left + parseFloat(style.borderLeftWidth) + parseFloat(style.paddingLeft)
    const y = rect.top + parseFloat(style.borderTopWidth) + parseFloat(style.paddingTop)
    const height = parseFloat(style.lineHeight)
    return { source: { x: x + ctx.measureText('2. ').width + 2, y: y + height * 1.5 }, target: { x: x + ctx.measureText('3. C').width + 8, y: y + height * 2.5 } }
  })
  await page.mouse.move(points.source.x, points.source.y)
  await page.mouse.down()
  await page.mouse.move(points.target.x, points.target.y, { steps: 15 })
  await page.mouse.up()
  await expect(description).toHaveValue('1. A\n2. C\n3. B')
  await description.press('Control+z')
  await expect(description).toHaveValue('1. A\n2. B\n3. C')
})

test('非可取消输入与浏览器撤销输入事件走同一事务', async ({ page }) => {
  const description = page.getByRole('textbox', { name: '任务描述' })
  await description.fill('1. A\n2. B\n3. C')
  await description.evaluate(el => {
    const textarea = el as HTMLTextAreaElement
    textarea.setSelectionRange(5, 10, 'backward')
    textarea.dispatchEvent(new InputEvent('beforeinput', { inputType: 'deleteByCut', bubbles: true, cancelable: false }))
    textarea.setRangeText('', 5, 10, 'start')
    textarea.dispatchEvent(new InputEvent('input', { inputType: 'deleteByCut', bubbles: true }))
  })
  await expect(description).toHaveValue('1. A\n2. C')
  await description.evaluate(el => el.dispatchEvent(new InputEvent('beforeinput', { inputType: 'historyUndo', cancelable: true, bubbles: true })))
  await expect(description).toHaveValue('1. A\n2. B\n3. C')
  expect(await description.evaluate(el => (el as HTMLTextAreaElement).selectionDirection)).toBe('backward')
})

test('只有input的续号与撤销、外部拖入清单仍能接入原组', async ({ page }) => {
  const description = page.getByRole('textbox', { name: '任务描述' })
  await description.fill('1. A\n2. B')
  await description.evaluate(el => {
    const textarea = el as HTMLTextAreaElement
    textarea.setRangeText('\n', 4, 4, 'end')
    textarea.dispatchEvent(new InputEvent('input', { inputType: 'insertLineBreak', bubbles: true }))
  })
  await expect(description).toHaveValue('1. A\n2. \n3. B')
  await description.evaluate(el => el.dispatchEvent(new InputEvent('input', { inputType: 'historyUndo', bubbles: true })))
  await expect(description).toHaveValue('1. A\n2. B')
  await description.evaluate(el => {
    const textarea = el as HTMLTextAreaElement, transfer = new DataTransfer()
    transfer.setData('text/plain', '1. X\n2. Y')
    textarea.setSelectionRange(5, 5)
    textarea.dispatchEvent(new InputEvent('beforeinput', { inputType: 'insertFromDrop', dataTransfer: transfer, bubbles: true, cancelable: false }))
    textarea.setRangeText('1. X\n2. Y', 5, 5, 'end')
    textarea.dispatchEvent(new InputEvent('input', { inputType: 'insertFromDrop', bubbles: true }))
  })
  await expect(description).toHaveValue('1. A\n2. X\n3. Y\n4. B')
})

test('内容冲突重试不丢编号，切周清除旧历史，只读汇总无编辑控件', async ({ page }) => {
  let conflict = true
  await page.route('**/api/weeks/**', async route => {
    if (route.request().method() === 'PATCH' && conflict) {
      conflict = false
      await route.fulfill({ status: 409, json: { detail: '内容已发生变化' } })
    } else await route.fallback()
  })
  await page.route('**/api/reports/**', async route => {
    const path = new URL(route.request().url()).pathname
    await route.fulfill({ json: path.includes('/users/') ? { revision: 1, tasks: [{ id: 1, position: 1, category_name: null, task_group: '', description: '1. A\n2. B', status: null, work_days: [], notes: '' }] } : [{ id: 1, name: '测试用户', is_active: true }] })
  })
  const description = page.getByRole('textbox', { name: '任务描述' })
  await description.fill('1. A\n2. B')
  await description.evaluate(el => (el as HTMLTextAreaElement).setSelectionRange(4, 4))
  await description.press('Enter')
  await expect(page.getByText('! 内容冲突')).toBeVisible()
  await page.getByRole('button', { name: '用当前修改重试' }).click()
  await expect(page.getByText('✓ 已保存')).toBeVisible()
  await expect(description).toHaveValue('1. A\n2. \n3. B')
  const current = (await page.locator('.calendar-caption').textContent())!.slice(0, 10)
  const previous = new Date(`${current}T00:00:00Z`)
  previous.setUTCDate(previous.getUTCDate() - 7)
  await page.getByRole('button', { name: `${previous.toISOString().slice(0, 10)}，选择该周`, exact: true }).click()
  await expect(page.getByRole('button', { name: '撤销', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: /周报汇总/ }).click()
  await expect(page.getByText('1. A\n2. B', { exact: true })).toBeVisible()
  await expect(page.getByRole('textbox', { name: '任务描述' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '撤销', exact: true })).toHaveCount(0)
})
