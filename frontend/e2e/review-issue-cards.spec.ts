import type { Page } from '@playwright/test'
import { test, expect } from './fixtures'
import type { ReviewIssue } from '../src/types'

async function openReview(page: Page, issueCount = 1, projectCount = 1, overrides: Partial<ReviewIssue>[] = []) {
  const user = { id: 42, username: 'member', display_name: '测试成员', role: 'user', is_active: true, status: '正常', must_change_password: false }
  const issue: ReviewIssue = {
    id: 7, project_id: 1, author: 'member', author_name: '测试成员', mine: true, anonymous: false,
    title: '检查空值', severity: '高危', category: '', dimension: '', sha: 'abcd', commit_message: '修改校验流程',
    path: '', start_line: null, end_line: null, existing_code: '', risk: '这里可能抛出异常。',
    suggestion: '', suggestion_code: '', status: null, notes: '', task_added: false, editable: true,
  }
  const projects = Object.fromEntries(Array.from({ length: projectCount }, (_, index) => [index + 1, index ? `项目 ${index + 1}` : '项目甲']))
  const issues = Array.from({ length: issueCount }, (_, index) => ({ ...issue, id: issue.id + index, ...overrides[index] }))
  await page.route('**/api/**', route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (path.endsWith('/auth/me')) return route.fulfill({ json: { user, csrf_token: 'test' } })
    if (path.includes('/reviews/days/')) return route.fulfill({ json: {
      projects, common_project_ids: [1],
      issues, summary: null,
    } })
    const target = issues.find(item => path.endsWith(`/reviews/issues/${item.id}`))
    if (target && request.method() === 'PATCH') {
      Object.assign(target, request.postDataJSON())
      return route.fulfill({ json: { status: target.status, notes: target.notes } })
    }
    if (path.endsWith('/notifications/unread')) return route.fulfill({ json: { count: 0 } })
    return route.fulfill({ json: [] })
  })

  await page.goto('/review-records')
  return issues[0]!
}

test('页头可收成一行，保留日期和功能按钮', async ({ page }) => {
  await openReview(page)
  const header = page.locator('.page-top')
  const heading = header.getByRole('heading', { name: '审查记录' })
  await expect(heading).toBeVisible()
  const expandedHeight = (await header.boundingBox())!.height

  await header.getByRole('button', { name: '收起页头' }).press('Enter')
  await expect(heading).toBeHidden()
  const title = header.locator('.eyebrow')
  const date = header.locator('.date-range')
  await expect(title).toHaveCSS('font-size', '16px')
  await expect(date).toHaveCSS('font-size', '16px')
  const titleBox = (await title.boundingBox())!
  const dateBox = (await date.boundingBox())!
  expect(dateBox.y + dateBox.height / 2).toBeCloseTo(titleBox.y + titleBox.height / 2, 0)
  expect(dateBox.x).toBeGreaterThan(titleBox.x + titleBox.width)
  expect((await header.boundingBox())!.height).toBeLessThan(expandedHeight)
  await expect(header.getByRole('button', { name: '审查总结' })).toBeVisible()
  await expect(header.getByRole('button', { name: '消息中心' })).toBeVisible()

  await header.getByRole('button', { name: '展开页头' }).click()
  await expect(heading).toBeVisible()
  expect((await header.boundingBox())!.height).toBe(expandedHeight)
})

test('审查问题默认收起，展开后可修改状态和备注', async ({ page }) => {
  const issue = await openReview(page)
  const card = page.locator('.review-issue')
  const toggle = card.getByRole('button', { name: /ISSUE-07/ })
  const tags = card.locator('.review-tags')
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  expect((await toggle.boundingBox())?.x).toBe((await card.boundingBox())?.x)
  expect((await toggle.boundingBox())?.y).toBe((await card.boundingBox())?.y)
  await expect(tags).toHaveText('ISSUE-07 高危 项目甲 测试成员 未开始 检查空值', { useInnerText: true })
  await expect(card.getByLabel('完成状态', { exact: true })).toBeHidden()
  await tags.getByText('项目甲').click()
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')

  await toggle.press('Enter')
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  await expect(tags).toHaveText('ISSUE-07 高危 项目甲 测试成员', { useInnerText: true })
  await expect(card.getByRole('heading', { name: '检查空值' })).toBeVisible()
  await expect(card.getByText('这里可能抛出异常。')).toBeVisible()
  const status = card.getByLabel('完成状态', { exact: true })
  await status.selectOption('已完成')
  await expect.poll(() => issue.status).toBe('已完成')
  const notes = card.getByRole('textbox', { name: '备注' })
  await notes.fill('已补上校验')
  await toggle.click()
  await expect(tags).toHaveText('ISSUE-07 高危 项目甲 测试成员 已完成 检查空值', { useInnerText: true })
  await expect.poll(() => issue.notes).toBe('已补上校验')
  await toggle.click()
  await expect(status).toHaveValue('已完成')
  await expect(notes).toHaveValue('已补上校验')
})

test('筛选栏可批量展开或收起问题，详情的四项元数据共用一行', async ({ page }) => {
  await openReview(page, 3, 1, [{ category: '边界异常', dimension: '正确性', path: 'src/review/very-long-file-name.ts', start_line: 12 }])
  const filters = page.getByRole('region', { name: '筛选审查记录' })
  const cards = page.locator('.review-issue')
  const expand = filters.getByRole('button', { name: '展开列表', exact: true })
  const collapse = filters.getByRole('button', { name: '收起列表', exact: true })
  await expect(cards.getByRole('button', { name: /展开 ISSUE-/ })).toHaveCount(3)
  await expand.click()
  await expect(cards.getByRole('button', { name: /收起 ISSUE-/ })).toHaveCount(3)
  await expect(collapse).toHaveAttribute('aria-expanded', 'true')
  const metadata = cards.first().locator('.review-metadata')
  await expect(metadata.locator('dt')).toHaveText(['问题类型', '审查维度', '提交', '涉及文件'])
  const columns = await metadata.locator(':scope > div').evaluateAll(cells => cells.map(cell => {
    const { y, width } = cell.getBoundingClientRect()
    return { y, width }
  }))
  expect(columns.map(column => column.y)).toEqual(Array(4).fill(columns[0]?.y))
  expect(columns.slice(0, 2).map(column => column.width)).toEqual([80, 80])
  expect(columns[2]!.width).toBeCloseTo(columns[3]!.width, 1)
  await expect(cards.nth(1).locator('.review-metadata dt')).toHaveText(['问题类型', '审查维度', '提交', '涉及文件'])
  await filters.getByRole('button', { name: '收起筛选', exact: true }).click()
  await collapse.click()
  await expect(cards.getByRole('button', { name: /展开 ISSUE-/ })).toHaveCount(3)
  await expect(expand).toHaveAttribute('aria-expanded', 'false')
  await expect(cards.getByRole('heading', { name: '风险说明' })).toHaveCount(0)
})

test('审查记录的说明和代码等宽并排，内容分别滚动', async ({ page }) => {
  const text = '风险及处理方式'.repeat(250)
  const code = `const value = '${'x'.repeat(200)}'\n`.repeat(24)
  await openReview(page, 2, 1, [
    { path: 'src/review.ts', risk: text, existing_code: code, suggestion: text, suggestion_code: code },
    { risk: '短说明', suggestion_code: 'return true' },
  ])
  await page.getByRole('button', { name: '展开列表', exact: true }).click()
  const cards = page.locator('.review-issue')
  const longCard = cards.first()
  const shortCard = cards.nth(1)
  await expect(longCard.locator('.review-code pre')).toHaveCount(2)
  await expect(shortCard.getByRole('heading', { name: '修改建议的代码', exact: true })).toBeVisible()

  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 800 })
    for (const [textLabel, codeLabel] of [['风险说明', '相关代码'], ['修改建议', '修改建议的代码']]) {
      const textSection = longCard.locator('section').filter({ has: page.getByRole('heading', { name: textLabel, exact: true }) })
      const codeSection = longCard.locator('section').filter({ has: page.getByRole('heading', { name: codeLabel, exact: true }) })
      const textBox = (await textSection.boundingBox())!
      const codeBox = (await codeSection.boundingBox())!
      expect(textBox.y).toBe(codeBox.y)
      expect(textBox.x).toBeLessThan(codeBox.x)
      expect(textBox.width).toBeCloseTo(codeBox.width, 1)
      expect((await codeSection.locator('.review-code').boundingBox())!.height).toBe(300)

      const description = await textSection.locator('p').evaluate(el => ({
        height: el.clientHeight, vertical: el.scrollHeight > el.clientHeight, horizontal: el.scrollWidth > el.clientWidth,
      }))
      expect(description).toEqual({ height: 300, vertical: true, horizontal: false })
      const codeScroll = await codeSection.locator('pre').evaluate(el => {
        el.scrollLeft = 100
        el.scrollTop = 100
        return { x: el.scrollLeft, y: el.scrollTop, whiteSpace: getComputedStyle(el).whiteSpace }
      })
      expect(codeScroll).toEqual({ x: 100, y: 100, whiteSpace: 'pre' })
    }
    expect((await shortCard.getByText('短说明', { exact: true }).boundingBox())!.height).toBeLessThan(300)
    expect((await shortCard.locator('.review-code').boundingBox())!.height).toBeLessThan(300)
  }
})

test('相关代码和建议代码去掉共同缩进，保留内部层级', async ({ page }) => {
  await openReview(page, 1, 1, [{
    path: 'src/review.py',
    existing_code: '    if ready:\r\n        run()\r\n\r\n    done()',
    suggestion_code: '  ```text\n\tif ready:\n\t\trun()\n  ```',
  }])
  await page.getByRole('button', { name: '展开列表', exact: true }).click()
  const blocks = page.locator('.review-issue .review-code pre code')
  await expect(blocks).toHaveCount(2)
  // 直接读取文本，保留断言中的行首空格和制表符。
  await expect.poll(() => blocks.allTextContents()).toEqual([
    'if ready:\n    run()\n\ndone()',
    'if ready:\n\trun()',
  ])
})

test('筛选收起时显示文本摘要，项目操作按钮共用样式', async ({ page }) => {
  await openReview(page, 1, 2)
  const card = page.getByRole('region', { name: '筛选审查记录' })
  const summary = card.getByRole('group', { name: '当前筛选条件' })
  const collapse = card.getByRole('button', { name: '收起筛选' })
  const expand = card.getByRole('button', { name: '展开筛选' })
  await expect(card.locator('.review-filter-top > [role="group"]')).toHaveCount(4)
  await expect(card.locator('[aria-label="严重程度"] + [aria-label="审查项目"]')).toHaveCSS('border-top-width', '0px')
  await expect(collapse).toHaveClass(/review-card-toggle/)
  await collapse.click()
  await expect(summary.locator('span')).toHaveText(['修改人：全部', '完成状态：全部', '严重程度：全部', '审查项目：全部'])
  await expect(card.getByRole('button')).toHaveCount(2)
  await expand.click()
  await card.getByRole('button', { name: '仅看我' }).click()
  await card.getByRole('button', { name: '未完成', exact: true }).click()
  await card.getByRole('button', { name: '高危', exact: true }).click()
  await card.getByRole('button', { name: '中危', exact: true }).click()

  const projects = card.getByRole('group', { name: '审查项目' })
  const expandProjects = projects.getByRole('button', { name: '展开全部' })
  const cancelAll = projects.getByRole('button', { name: '取消全选', exact: true })
  const selectAll = projects.getByRole('button', { name: '全选', exact: true })
  const actionColor = await cancelAll.evaluate(el => getComputedStyle(el).backgroundColor)
  await expect(expandProjects).toHaveCSS('background-color', actionColor)
  await expect(projects.getByRole('button', { name: '项目甲' })).not.toHaveCSS('background-color', actionColor)
  await expect(selectAll).toHaveCount(0)
  await cancelAll.click()
  await expect(cancelAll).toHaveCount(0)
  await selectAll.click()
  await cancelAll.click()
  await expandProjects.click()
  await projects.getByRole('button', { name: '项目 2' }).click()
  await projects.getByRole('button', { name: '收起', exact: true }).click()
  await collapse.click()
  await expect(summary.locator('span')).toHaveText(['修改人：仅看我', '完成状态：未完成', '严重程度：高危、中危', '审查项目：项目 2'])
})

test('未完成优先且组内按严重程度排序，保存状态后更新顺序', async ({ page }) => {
  await openReview(page, 7, 1, [
    { status: '已完成', severity: '严重' }, { severity: '低危' },
    { status: '80%', severity: '高危' }, { status: '已完成', severity: '低危' },
    { severity: '严重' }, { status: '忽略', severity: '中危' }, { status: '10%', severity: '高危' },
  ])
  const order = page.locator('.review-results .review-number')
  await expect(order).toHaveText(['ISSUE-11', 'ISSUE-09', 'ISSUE-13', 'ISSUE-12', 'ISSUE-08', 'ISSUE-07', 'ISSUE-10'])
  const card = page.locator('.review-issue').filter({ hasText: 'ISSUE-11' })
  await card.getByRole('button', { name: /展开 ISSUE-11/ }).click()
  await card.getByLabel('完成状态').selectOption('已完成')
  await expect(order).toHaveText(['ISSUE-09', 'ISSUE-13', 'ISSUE-12', 'ISSUE-08', 'ISSUE-07', 'ISSUE-11', 'ISSUE-10'])
  await expect(card.getByLabel('完成状态')).toHaveValue('已完成')
})

for (const viewport of [{ width: 1280, height: 800 }, { width: 390, height: 740 }]) {
  test(`筛选卡片保持置顶并可展开收起（${viewport.width}px）`, async ({ page }) => {
    await page.setViewportSize(viewport)
    const mobile = viewport.width < 800
    await openReview(page, 25, mobile ? 40 : 1)
    const card = page.getByRole('region', { name: '筛选审查记录' })
    const collapse = card.getByRole('button', { name: '收起筛选' })
    const mine = card.getByRole('button', { name: '仅看我' })
    await expect(collapse).toHaveAttribute('aria-expanded', 'true')
    await mine.click()

    const results = page.getByRole('region', { name: '审查问题列表' })
    const pinnedTop = (await card.boundingBox())!.y
    if (mobile) {
      await card.getByRole('button', { name: '展开全部' }).click()
      const lastProject = card.getByRole('button', { name: '项目 40', exact: true })
      await lastProject.scrollIntoViewIfNeeded()
      await expect(lastProject).toBeInViewport()
      await expect(collapse).toBeInViewport()
    }
    const resultsHeight = (await results.boundingBox())!.height
    await results.evaluate(el => { el.scrollTop = 600 })
    await expect.poll(() => results.evaluate(el => el.scrollTop)).toBeGreaterThan(100)
    expect((await card.boundingBox())!.y).toBe(pinnedTop)

    await collapse.click()
    const expand = card.getByRole('button', { name: '展开筛选' })
    await expect(expand).toHaveAttribute('aria-expanded', 'false')
    await expect(mine).toBeHidden()
    expect((await card.boundingBox())!.y).toBe(pinnedTop)
    expect((await results.boundingBox())!.height).toBeGreaterThan(resultsHeight)
    await expand.press('Enter')
    if (mobile) await mine.scrollIntoViewIfNeeded()
    await expect(mine).toHaveAttribute('aria-pressed', 'true')
  })
}
