import { test, expect } from './fixtures'

for (const mode of ['补录部署基线', '新增升级计划'] as const) {
  test(`${mode}使用 GitLab 查询结果选择分支和标签`, async ({ page }) => {
    const admin = { id: 42, username: 'admin', display_name: '管理员', roles: ['admin'], is_active: true, status: '正常' }
    const branch = { name: 'release/1.2.3', sha: 'a'.repeat(40) }
    const tag = { name: 'prod/1.2.3', sha: 'b'.repeat(40) }
    const requests: string[] = []
    const saved: unknown[] = []
    const savedTargets: unknown[] = []
    await page.route('**/api/**', route => {
      const request = route.request(), url = new URL(request.url())
      const path = url.pathname
      if (path.endsWith('/auth/me')) return route.fulfill({ json: { user: admin, csrf_token: 'test' } })
      if (path.endsWith('/deployments/overview')) return route.fulfill({ json: {
        projects: [{ id: 1, name: '示例项目', level: 'national', network: 'internal', sites: ['national'] }],
        history_projects: [], sites: { national: '国铁侧' }, networks: { internal: '内服网' }, targets: [],
      } })
      if (/(branches|tags)$/.test(path)) {
        const kind = path.endsWith('branches') ? 'branches' : 'tags'
        const search = url.searchParams.get('search') || ''
        requests.push(`${kind}:${search}:${url.searchParams.get('page')}`)
        const results = kind === 'branches' ? [branch, { name: 'main', sha: 'c'.repeat(40) }] : [tag]
        return route.fulfill({ json: { items: results.filter(item => item.name.includes(search)), has_more: false } })
      }
      if (path.includes('/projects/1/') && request.method() === 'POST') {
        const data = request.postDataJSON()
        saved.push(data)
        return route.fulfill({ json: { id: 1, ...data } })
      }
      if (request.method() === 'POST' && /\/(plans|baselines)$/.test(path)) {
        savedTargets.push(request.postDataJSON())
        return route.fulfill({ json: [{ id: 1 }] })
      }
      if (path.endsWith('/notifications/unread')) return route.fulfill({ json: { count: 0 } })
      return route.fulfill({ json: [] })
    })
    await page.goto('/deployments')
    await page.getByRole('button', { name: '升级计划', exact: true }).click()
    await page.getByRole('button', { name: mode, exact: true }).click()

    const dialog = page.getByRole('dialog', { name: mode })
    await dialog.getByLabel('版本号', { exact: true }).fill('1.2.3')
    const branches = dialog.getByRole('combobox', { name: 'GitLab 分支（选填）', exact: true })
    const tags = dialog.getByRole('combobox', { name: 'GitLab 标签（选填）', exact: true })
    await expect(dialog.getByRole('group', { name: '部署机房' })).toHaveCount(0)
    await expect(dialog.getByRole('button', { name: '查询分支' })).toHaveCount(0)
    await branches.click()
    await expect(dialog.getByRole('option', { name: 'main', exact: false })).toBeVisible()
    const branchY = await branches.evaluate(element => element.getBoundingClientRect().y)
    const tagY = await tags.evaluate(element => element.getBoundingClientRect().y)
    expect(tagY).toBe(branchY)
    await expect(dialog.getByRole('listbox', { name: 'GitLab 分支' }).locator('..')).toHaveCSS('position', 'fixed')
    expect(requests).toContain('branches::1')
    await branches.fill('release/')
    await expect(dialog.getByRole('option', { name: /release\/1\.2\.3/ })).toBeVisible()
    await expect(dialog.getByRole('option', { name: 'main', exact: false })).toHaveCount(0)
    expect(requests).toContain('branches:release/:1')
    // 模拟前一次提交留下的原生自定义错误，选中选项应立即清除。
    await branches.evaluate(input => (input as HTMLInputElement).setCustomValidity('请输入有效内容。'))
    await branches.press('ArrowDown')
    await branches.press('Enter')
    await expect(branches).toHaveValue(branch.name)
    expect(await branches.evaluate(input => (input as HTMLInputElement).validity.valid)).toBe(true)
    await dialog.getByRole('button', { name: '清空GitLab 分支' }).click()
    await expect(branches).toHaveValue('')
    await expect(dialog.getByRole('option', { name: /release\/1\.2\.3/ })).toBeVisible()
    await dialog.getByRole('option', { name: /release\/1\.2\.3/ }).click()

    await tags.click()
    await expect(dialog.getByRole('option', { name: /prod\/1\.2\.3/ })).toBeVisible()
    expect(requests).toContain('tags::1')
    await tags.fill('不存在')
    await expect(dialog.getByText('没有匹配的标签')).toBeVisible()
    await dialog.getByRole('button', { name: '保存', exact: true }).click()
    expect(saved).toHaveLength(0)
    await dialog.getByRole('button', { name: '清空GitLab 标签' }).click()
    await expect(tags).toHaveValue('')
    await tags.fill('prod/')
    await dialog.getByRole('option', { name: /prod\/1\.2\.3/ }).click()
    await expect(tags).toHaveValue(tag.name)
    await dialog.getByRole('button', { name: '保存', exact: true }).click()
    await expect(dialog).toBeHidden()
    expect(saved).toEqual([{ number: '1.2.3', branch: branch.name, sha: branch.sha, tag: tag.name, tag_sha: tag.sha }])
    expect(savedTargets[0]).toMatchObject({ sites: ['national'] })
  })
}

test('路局升级计划显示当前版本并可省略 GitLab 引用，升级内容保留换行', async ({ page }) => {
  const sites = Object.fromEntries(Array.from({ length: 18 }, (_, index) => [`site-${index}`, `路局 ${index + 1}`]))
  const saved: Record<string, unknown>[] = []
  const content = '更新运行配置\n补充数据库索引'
  await page.route('**/api/**', route => {
    const request = route.request(), { pathname } = new URL(request.url())
    if (pathname.endsWith('/auth/me')) return route.fulfill({ json: { user: { id: 42, display_name: '管理员', roles: ['admin'] }, csrf_token: 'test' } })
    if (pathname.endsWith('/deployments/overview')) return route.fulfill({ json: {
      projects: [{ id: 1, name: '路局项目', level: 'regional', network: 'internal', sites: Object.keys(sites) }],
      history_projects: [], sites, networks: { internal: '内服网' },
      targets: [{ project_id: 1, site: 'site-0', current: { version: { number: '1.0.0' } }, planned: { version: { number: '9.0.0' } } }],
    } })
    if (request.method() === 'POST') {
      saved.push(request.postDataJSON())
      if (pathname.endsWith('/versions')) return route.fulfill({ json: { id: 2, ...saved.at(-1) } })
      return route.fulfill({ json: [{ id: 5 }] })
    }
    if (pathname.endsWith('/notifications/unread')) return route.fulfill({ json: { count: 0 } })
    return route.fulfill({ json: [] })
  })
  await page.goto('/deployments')
  await page.getByRole('button', { name: '升级计划', exact: true }).click()
  await page.getByRole('button', { name: '新增升级计划', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '新增升级计划' })
  const rooms = dialog.getByRole('group', { name: '部署机房' })
  await expect(rooms.getByRole('checkbox')).toHaveCount(18)
  await expect(rooms.getByText('1.0.0', { exact: true })).toBeVisible()
  await expect(rooms.getByText('9.0.0', { exact: true })).toHaveCount(0)
  await rooms.getByRole('checkbox', { name: /路局 1 1\.0\.0/ }).check()
  const version = dialog.getByLabel('版本号', { exact: true })
  const time = dialog.getByLabel('计划时间（北京时间）', { exact: true })
  await version.fill('1.1.0')
  expect((await version.boundingBox())?.y).toBe((await time.boundingBox())?.y)
  await dialog.getByLabel('升级内容').fill(content)
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await expect(dialog).toBeHidden()
  expect(saved[0]).toMatchObject({ number: '1.1.0', branch: null, tag: null })
  expect(saved[1]).toMatchObject({ version_id: 2, sites: ['site-0'], upgrade_content: content })
})

test('发版管理二级菜单分开计划编辑、备忘卡片和发版结果', async ({ page }) => {
  const longNote = '完整备忘说明 '.repeat(30)
  const plan = {
    id: 5, project_id: 1, project_name: '示例项目', site: 'beijing', network: 'internal',
    version: { id: 2, number: '2.0.0', branch: null, tag: null }, from_version: null,
    status: 'ready', scheduled_at: '2026-11-26T14:00:00+08:00', deployed_at: null,
    rolled_back_at: '', upgrade_content: '原上线说明', revision: 0, can_confirm: false,
  }
  const item = { id: 1, title: '核对运行配置', notes: longNote, author: '小王', source_version: null,
    removed: false, done: false, dispatched: true, can_complete: true }
  let refreshes = 0
  await page.route('**/api/**', route => {
    const request = route.request(), url = new URL(request.url()), pathname = url.pathname
    if (pathname.endsWith('/auth/me')) return route.fulfill({ json: { user: { id: 42, display_name: '管理员', roles: ['admin'] }, csrf_token: 'test' } })
    if (pathname.endsWith('/deployments/overview')) return route.fulfill({ json: {
      projects: [], history_projects: [], sites: { beijing: '北京局' }, networks: { internal: '内服网' }, targets: [],
    } })
    if (pathname.endsWith('/deployments/plans')) return route.fulfill({ json: (url.searchParams.has('history') === (plan.status === 'failed')) ? [plan] : [] })
    if (pathname.endsWith('/plans/5/schedule')) {
      expect(request.postDataJSON()).toEqual({ revision: 0, scheduled_at: '2026-11-26T14:00:00+08:00', upgrade_content: '新的上线说明' })
      plan.upgrade_content = request.postDataJSON().upgrade_content
    }
    if (pathname.endsWith('/plans/5/items/1')) plan.can_confirm = item.done = request.postDataJSON().done
    if (pathname.endsWith('/plans/5/checklist/refresh')) refreshes++
    if (pathname.endsWith('/plans/5/result')) {
      expect(request.postDataJSON()).toEqual({ revision: 0, result: 'failed', actual_at: '2026-11-26T15:00:00+08:00' })
      plan.status = 'failed'; plan.rolled_back_at = request.postDataJSON().actual_at
    }
    if (pathname.includes('/plans/5')) return route.fulfill({ json: { ...plan, items: [item] } })
    if (pathname.endsWith('/notifications/unread')) return route.fulfill({ json: { count: 0 } })
    return route.fulfill({ json: [] })
  })
  await page.goto('/categories')
  const menu = page.getByRole('button', { name: '发版管理', exact: true })
  await expect(menu).toHaveAttribute('aria-expanded', 'false')
  await menu.click()
  await expect(menu).toHaveAttribute('aria-expanded', 'true')
  await expect(page.locator('#deployment-submenu').getByRole('button')).toHaveText(['部署总览', '升级计划', '发版备忘'])
  await page.getByRole('button', { name: '升级计划', exact: true }).click()
  const row = page.getByRole('row').filter({ has: page.getByRole('rowheader', { name: '示例项目' }) })
  await expect(row.getByRole('button', { name: '示例项目' })).toHaveCount(0)
  await expect(row.getByRole('button', { name: '确认发版' })).toBeDisabled()
  await row.getByRole('button', { name: '修改' }).click()
  const edit = page.getByRole('dialog', { name: '修改升级计划' })
  await expect(edit.locator('input, textarea, select')).toHaveCount(2)
  await edit.getByLabel('升级内容').fill('新的上线说明')
  await edit.getByRole('button', { name: '保存', exact: true }).click()
  await expect(edit).toBeHidden()
  await expect(row.getByText('新的上线说明')).toBeVisible()

  await row.getByRole('button', { name: '备忘检查' }).click()
  const checklist = page.getByRole('dialog', { name: '备忘检查清单' })
  const card = checklist.getByRole('article')
  await expect(card.getByRole('img', { name: '待检查' })).toBeVisible()
  await card.hover()
  await expect(checklist.getByRole('tooltip')).toContainText(longNote.trim())
  await card.getByRole('button', { name: '标记已完成' }).click()
  await expect(card.getByRole('img', { name: '已完成', exact: true })).toBeVisible()
  await card.getByRole('button', { name: '标记为未完成' }).click()
  await expect(card.getByRole('img', { name: '待检查' })).toBeVisible()
  await card.getByRole('button', { name: '标记已完成' }).click()
  await card.getByRole('button', { name: '本次移除' }).click()
  await expect(card.getByRole('img', { name: '本次已移除' })).toBeVisible()
  await expect(card.getByText('核对运行配置')).toHaveCSS('text-decoration-line', 'line-through')
  await card.getByRole('button', { name: '取消移除' }).click()
  await expect(card.getByRole('img', { name: '已完成', exact: true })).toBeVisible()
  await checklist.getByRole('button', { name: '刷新', exact: true }).click()
  await expect.poll(() => refreshes).toBe(1)
  await expect(checklist.getByLabel('实际发版时间', { exact: false })).toHaveCount(0)
  await checklist.getByRole('button', { name: '关闭', exact: true }).click()

  await row.getByRole('button', { name: '确认发版' }).click()
  const confirmation = page.getByRole('dialog', { name: '确认发版' })
  await expect(confirmation.getByRole('radio', { name: '发版成功' })).toBeVisible()
  await confirmation.getByRole('radio', { name: '发版失败' }).check()
  await confirmation.getByLabel('实际回滚时间（北京时间）').fill('2026-11-26T15:00')
  await confirmation.getByRole('button', { name: '保存', exact: true }).click()
  await expect(confirmation).toBeHidden()
  await page.getByLabel('计划范围').selectOption('history')
  await expect(row.getByText('发版失败')).toBeVisible()
  await expect(row.getByRole('button', { name: '删除', exact: true })).toHaveCount(0)
})

test('部署总览按项目列展示，零检查项直接确认，未派发计划可编辑版本引用', async ({ page }) => {
  const version = { id: 1, number: '1.0.0', branch: 'main', sha: 'a'.repeat(40), tag: null, tag_sha: null }
  const plan = { id: 3, project_id: 1, project_name: '项目甲', site: 'beijing', network: 'internal', version,
    status: 'draft', scheduled_at: '2026-11-26T14:00:00+08:00', upgrade_content: '', checklist_count: 0, can_confirm: true, revision: 0 }
  const projects = ['项目甲', '项目乙'].map((name, index) => ({ id: index + 1, name, level: 'regional', network: 'internal', sites: ['beijing', 'shanghai'] }))
  await page.route('**/api/**', route => {
    const request = route.request(), { pathname } = new URL(request.url())
    if (pathname.endsWith('/auth/me')) return route.fulfill({ json: { user: { id: 42, display_name: '管理员', roles: ['admin'] }, csrf_token: 'test' } })
    if (pathname.endsWith('/deployments/overview')) return route.fulfill({ json: { projects, history_projects: [],
      sites: { national: '国铁侧', beijing: '北京局', shanghai: '上海局' }, networks: { internal: '内服网' },
      targets: [{ project_id: 2, site: 'shanghai', current: { version: { ...version, number: '2.0.0' }, deployed_at: null } }],
    } })
    if (pathname.endsWith('/plans')) return route.fulfill({ json: [plan] })
    if (pathname.endsWith('/tags')) return route.fulfill({ json: { items: [{ name: 'v1.1.0', sha: 'b'.repeat(40) }], has_more: false } })
    if (pathname.endsWith('/schedule')) {
      expect(request.postDataJSON().version).toEqual({ number: '1.1.0', branch: 'main', sha: 'a'.repeat(40), tag: 'v1.1.0', tag_sha: 'b'.repeat(40) })
      Object.assign(version, request.postDataJSON().version)
      return route.fulfill({ json: plan })
    }
    if (pathname.endsWith('/notifications/unread')) return route.fulfill({ json: { count: 0 } })
    return route.fulfill({ json: [] })
  })
  await page.goto('/deployments')
  const overview = page.getByLabel('项目与机房部署总览')
  await expect(overview.getByRole('columnheader')).toHaveText(['部署机房', /项目甲/, /项目乙/])
  const shanghai = overview.getByRole('row').filter({ has: page.getByRole('rowheader', { name: '上海局' }) })
  await expect(shanghai.getByRole('cell').nth(1)).toContainText('2.0.0')
  await page.getByRole('button', { name: '升级计划', exact: true }).click()
  await expect(page.getByRole('button', { name: '备忘检查', exact: true })).toBeDisabled()
  await expect(page.getByTitle('无需检查')).toBeVisible()
  await expect(page.getByRole('button', { name: '确认发版', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: '修改', exact: true }).click()
  const edit = page.getByRole('dialog', { name: '修改升级计划' })
  await expect(edit).toHaveCSS('border-top-width', '4px')
  await edit.getByLabel('版本号', { exact: true }).fill('1.1.0')
  await expect(edit.getByRole('combobox', { name: 'GitLab 分支（选填）' })).toHaveValue('main')
  await edit.getByRole('combobox', { name: 'GitLab 标签（选填）' }).click()
  await edit.getByRole('option', { name: /v1\.1\.0/ }).click()
  await edit.getByRole('button', { name: '保存', exact: true }).click()
  await expect(edit).toBeHidden()
  await expect(page.getByRole('cell', { name: '1.1.0', exact: true })).toBeVisible()
})
