import type { Page } from '@playwright/test'
import { test, expect } from './fixtures'
import type { ReviewIssue } from '../src/types'

async function openReview(page: Page, issueCount = 1, projectCount = 1) {
  const user = { id: 42, username: 'member', display_name: '测试成员', role: 'user', is_active: true, status: '正常', must_change_password: false }
  const issue: ReviewIssue = {
    id: 7, project_id: 1, author: 'member', author_name: '测试成员', mine: true, anonymous: false,
    title: '检查空值', severity: '高危', category: '', dimension: '', sha: 'abcd', commit_message: '修改校验流程',
    path: '', start_line: null, end_line: null, existing_code: '', risk: '这里可能抛出异常。',
    suggestion: '', suggestion_code: '', status: null, notes: '', task_added: false, editable: true,
  }
  const projects = Object.fromEntries(Array.from({ length: projectCount }, (_, index) => [index + 1, index ? `项目 ${index + 1}` : '项目甲']))
  await page.route('**/api/**', route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (path.endsWith('/auth/me')) return route.fulfill({ json: { user, csrf_token: 'test' } })
    if (path.includes('/reviews/days/')) return route.fulfill({ json: {
      projects, common_project_ids: [1],
      issues: Array.from({ length: issueCount }, (_, index) => ({ ...issue, id: issue.id + index })), summary: null,
    } })
    if (path.endsWith('/reviews/issues/7') && request.method() === 'PATCH') {
      Object.assign(issue, request.postDataJSON())
      return route.fulfill({ json: { status: issue.status, notes: issue.notes } })
    }
    if (path.endsWith('/notifications/unread')) return route.fulfill({ json: { count: 0 } })
    return route.fulfill({ json: [] })
  })

  await page.goto('/review-records')
  return issue
}

test('审查问题默认收起，展开后可修改状态和备注', async ({ page }) => {
  const issue = await openReview(page)
  const card = page.locator('.review-issue')
  const toggle = card.getByRole('button', { name: /ISSUE-07/ })
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await expect(card).toHaveText('ISSUE-07 高危 项目甲 未开始', { useInnerText: true })
  await expect(card.getByLabel('完成状态', { exact: true })).toBeHidden()

  await toggle.press('Enter')
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  await expect(toggle).toHaveText('ISSUE-07 高危 项目甲 测试成员', { useInnerText: true })
  await expect(card.getByRole('heading', { name: '检查空值' })).toBeVisible()
  await expect(card.getByText('这里可能抛出异常。')).toBeVisible()
  const status = card.getByLabel('完成状态', { exact: true })
  await status.selectOption('已完成')
  await expect.poll(() => issue.status).toBe('已完成')
  const notes = card.getByRole('textbox', { name: '备注' })
  await notes.fill('已补上校验')
  await toggle.click()
  await expect(card).toHaveText('ISSUE-07 高危 项目甲 已完成', { useInnerText: true })
  await expect.poll(() => issue.notes).toBe('已补上校验')
  await toggle.click()
  await expect(status).toHaveValue('已完成')
  await expect(notes).toHaveValue('已补上校验')
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
