import { test, expect } from './fixtures'

test('审查配置可切换常用，审查记录默认折叠非常用项目', async ({ page }) => {
  const admin = { id: 42, username: 'admin', display_name: '管理员', role: 'admin', is_active: true, status: '正常', must_change_password: false }
  const projects = ['项目甲', '项目乙'].map((name, index) => ({
    id: index + 1, name, alias: name, url: `https://git.example.com/project-${index + 1}`,
    owner: '旧项目属主', visibility: 'private', gitlab_url: null, gitlab_id: null, skip_slash_branches: true, is_common: false,
  }))
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (path.endsWith('/auth/me')) return route.fulfill({ json: { user: admin, csrf_token: 'test' } })
    if (path.endsWith('/reviews/projects')) return route.fulfill({ json: projects })
    if (path.endsWith('/reviews/projects/1') && request.method() === 'PATCH') {
      projects[0]!.is_common = request.postDataJSON().is_common
      return route.fulfill({ json: projects[0] })
    }
    if (path.includes('/reviews/days/')) return route.fulfill({ json: {
      projects: Object.fromEntries(projects.map(project => [project.id, project.alias])),
      common_project_ids: projects.filter(project => project.is_common).map(project => project.id),
      issues: [], summary: null,
    } })
    if (path.endsWith('/notifications/unread')) return route.fulfill({ json: { count: 0 } })
    return route.fulfill({ json: [] })
  })

  await page.goto('/review-config')
  const firstProject = page.locator('.review-project').filter({ hasText: '项目甲' })
  await expect(firstProject).toBeVisible()
  await expect(firstProject).not.toContainText(/私有|旧项目属主/)
  for (const button of [firstProject.getByRole('button', { name: '编辑' }), page.getByRole('button', { name: '手动新增' })]) {
    await button.click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByLabel('项目名称')).toBeVisible()
    await expect(dialog.getByLabel('可见性')).toHaveCount(0)
    await expect(dialog.getByLabel('项目所属用户或命名空间')).toHaveCount(0)
    await dialog.getByRole('button', { name: '取消', exact: true }).click()
  }
  await firstProject.getByRole('button', { name: '设为常用' }).click({ timeout: 6000 })
  await expect(firstProject.getByRole('button', { name: '取消常用' })).toBeVisible()
  await page.getByRole('button', { name: '审查记录', exact: true }).click()
  const filters = page.getByRole('group', { name: '审查项目' })
  const projectA = filters.getByRole('button', { name: '项目甲' })
  const projectB = filters.getByRole('button', { name: '项目乙' })
  await expect(projectA).toBeVisible()
  await expect(projectB).toBeHidden()
  await filters.getByRole('button', { name: '展开全部' }).click()
  await expect(projectB).toBeVisible()
  await projectB.click()
  await filters.getByRole('button', { name: '收起非常用' }).click()
  await expect(projectB).toBeHidden()
  await filters.getByRole('button', { name: '展开全部' }).click()
  await expect(projectB).toHaveAttribute('aria-pressed', 'false')

  await page.getByRole('button', { name: '审查配置', exact: true }).click()
  await firstProject.getByRole('button', { name: '取消常用' }).click()
  await expect(firstProject.getByRole('button', { name: '设为常用' })).toBeVisible()
  await page.getByRole('button', { name: '审查记录', exact: true }).click()
  await expect(filters.getByRole('button', { name: '展开全部' })).toBeVisible()
  await expect(projectA).toBeHidden()
  await expect(projectB).toBeHidden()
})
