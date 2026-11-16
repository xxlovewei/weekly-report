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

test('审查问题默认收起，展开后可修改状态和备注', async ({ page }) => {
  const issue = await openReview(page)
  const card = page.locator('.review-issue')
  const toggle = card.getByRole('button', { name: /ISSUE-07/ })
  const tags = card.locator('.review-tags')
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  expect((await toggle.boundingBox())?.x).toBe((await card.boundingBox())?.x)
  expect((await toggle.boundingBox())?.y).toBe((await card.boundingBox())?.y)
  await expect(tags).toHaveText('ISSUE-07 高危 项目甲 测试成员 未开始', { useInnerText: true })
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
  await expect(tags).toHaveText('ISSUE-07 高危 项目甲 测试成员 已完成', { useInnerText: true })
  await expect.poll(() => issue.notes).toBe('已补上校验')
  await toggle.click()
  await expect(status).toHaveValue('已完成')
  await expect(notes).toHaveValue('已补上校验')
})

test('筛选收起时显示文本摘要，项目操作按钮共用样式', async ({ page }) => {
  await openReview(page, 1, 2)
  const card = page.getByRole('region', { name: '筛选审查记录' })
  const summary = card.getByRole('group', { name: '当前筛选条件' })
  const collapse = card.getByRole('button', { name: '收起筛选' })
  const expand = card.getByRole('button', { name: '展开筛选' })
  await collapse.click()
  await expect(summary.locator('span')).toHaveText(['修改人：全部', '完成状态：全部', '严重程度：全部', '审查项目：全部'])
  await expect(card.getByRole('button')).toHaveCount(1)
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
