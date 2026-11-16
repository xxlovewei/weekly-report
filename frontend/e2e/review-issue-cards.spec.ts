import { test, expect } from './fixtures'
import type { ReviewIssue } from '../src/types'

test('审查问题默认收起，展开后可修改状态和备注', async ({ page }) => {
  const user = { id: 42, username: 'member', display_name: '测试成员', role: 'user', is_active: true, status: '正常', must_change_password: false }
  const issue: ReviewIssue = {
    id: 7, project_id: 1, author: 'member', author_name: '测试成员', mine: true, anonymous: false,
    title: '检查空值', severity: '高危', category: '', dimension: '', sha: 'abcd', commit_message: '修改校验流程',
    path: '', start_line: null, end_line: null, existing_code: '', risk: '这里可能抛出异常。',
    suggestion: '', suggestion_code: '', status: null, notes: '', task_added: false, editable: true,
  }
  await page.route('**/api/**', route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (path.endsWith('/auth/me')) return route.fulfill({ json: { user, csrf_token: 'test' } })
    if (path.includes('/reviews/days/')) return route.fulfill({ json: {
      projects: { 1: '项目甲' }, common_project_ids: [1], issues: [issue], summary: null,
    } })
    if (path.endsWith('/reviews/issues/7') && request.method() === 'PATCH') {
      Object.assign(issue, request.postDataJSON())
      return route.fulfill({ json: { status: issue.status, notes: issue.notes } })
    }
    if (path.endsWith('/notifications/unread')) return route.fulfill({ json: { count: 0 } })
    return route.fulfill({ json: [] })
  })

  await page.goto('/review-records')
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
