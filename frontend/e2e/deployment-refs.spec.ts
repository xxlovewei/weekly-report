import { test, expect } from './fixtures'
import { mondayOf, todayShanghai } from '../src/dates'

function planPage(items: unknown[] = [], total = items.length, page = 1) {
  return { items, total, page, page_size: 20 }
}

for (const mode of ['补录部署基线', '新增发版计划'] as const) {
  test(`${mode}使用 GitLab 查询结果选择分支和标签`, async ({ page }) => {
    const admin = { id: 42, username: 'admin', display_name: '管理员', roles: ['admin'], is_active: true, status: '正常' }
    const branch = { name: 'release/1.2.3', sha: 'a'.repeat(40) }
    const tag = { name: 'prod/1.2.3', sha: 'b'.repeat(40) }
    const requests: string[] = []
    const saved: unknown[] = []
    const savedTargets: unknown[] = []
    const commitRequests: unknown[] = []
    const messages = ['更新升级流程\n补充说明', '修复上线校验']
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
      if (path.endsWith('/commit-messages')) {
        const data = request.postDataJSON()
        commitRequests.push(data)
        return route.fulfill({ json: data.allow_recent ? { messages } : { requires_recent_confirmation: true } })
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
      if (path.endsWith('/deployments/plans')) return route.fulfill({ json: planPage() })
      if (path.endsWith('/notifications/unread')) return route.fulfill({ json: { count: 0 } })
      return route.fulfill({ json: [] })
    })
    await page.goto('/deployments')
    await page.getByRole('button', { name: '发版计划', exact: true }).click()
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
    const commits = dialog.getByRole('button', { name: '获取提交记录' })
    if (mode === '新增发版计划') {
      let prompt = ''
      page.once('dialog', confirmation => { prompt = confirmation.message(); return confirmation.dismiss() })
      await commits.click()
      await expect(commits).toBeEnabled()
      expect(prompt).toContain('最近 2 周')
      expect(commitRequests).toHaveLength(1)
      await expect(dialog.getByLabel('升级内容')).toHaveValue('')

      page.once('dialog', confirmation => confirmation.accept())
      await commits.click()
      await expect(dialog.getByLabel('升级内容')).toHaveValue(messages.join('\n\n'))
      expect(commitRequests).toHaveLength(3)
      expect(commitRequests.at(-1)).toMatchObject({ allow_recent: true, version: { branch: branch.name, tag: tag.name } })
    } else {
      await expect(commits).toHaveCount(0)
    }
    await dialog.getByRole('button', { name: '保存', exact: true }).click()
    await expect(dialog).toBeHidden()
    expect(saved).toEqual([{ number: '1.2.3', branch: branch.name, sha: branch.sha, tag: tag.name, tag_sha: tag.sha }])
    expect(savedTargets[0]).toMatchObject({ sites: ['national'] })
    if (mode === '新增发版计划') expect(savedTargets[0]).toMatchObject({ upgrade_content: messages.join('\n\n') })
  })
}

test('路局发版计划显示当前版本并可省略 GitLab 引用，升级内容保留换行', async ({ page }) => {
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
    if (pathname.endsWith('/deployments/plans')) return route.fulfill({ json: planPage() })
    if (pathname.endsWith('/notifications/unread')) return route.fulfill({ json: { count: 0 } })
    return route.fulfill({ json: [] })
  })
  await page.goto('/deployments')
  await page.getByRole('button', { name: '发版计划', exact: true }).click()
  await page.getByRole('button', { name: '新增发版计划', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '新增发版计划' })
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
    if (pathname.endsWith('/deployments/plans')) return route.fulfill({ json: planPage(
      (url.searchParams.has('history') === (plan.status === 'failed')) ? [plan] : [],
    ) })
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
  await expect(page.locator('#deployment-submenu').getByRole('button')).toHaveText(['部署总览', '发版计划', '发版备忘'])
  await page.getByRole('button', { name: '发版备忘', exact: true }).click()
  await expect(page).toHaveURL(/\/deployments\/memos$/)
  await expect(page.getByRole('button', { name: '发版备忘', exact: true })).toHaveAttribute('aria-current', 'page')
  await page.getByRole('button', { name: '发版计划', exact: true }).click()
  await expect(page).toHaveURL(/\/deployments\/plans$/)
  const row = page.getByRole('row').filter({ has: page.getByRole('rowheader', { name: '示例项目' }) })
  await expect(row.getByRole('button', { name: '示例项目' })).toHaveCount(0)
  await expect(row.getByRole('button', { name: '确认发版' })).toBeDisabled()
  await row.getByRole('button', { name: '修改' }).click()
  const edit = page.getByRole('dialog', { name: '修改发版计划' })
  await expect(edit.locator('input, textarea, select')).toHaveCount(2)
  await edit.getByLabel('升级内容').fill('新的上线说明')
  await edit.getByRole('button', { name: '保存', exact: true }).click()
  await expect(edit).toBeHidden()
  await expect(row.getByText('新的上线说明')).toBeVisible()

  await row.getByRole('button', { name: '备忘检查' }).click()
  const checklist = page.getByRole('dialog', { name: '备忘检查清单' })
  await expect(page).toHaveURL(new RegExp(`/deployments/plans\\?plan=${plan.id}$`))
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
  await expect(page).toHaveURL(/\/deployments\/plans$/)

  await row.getByRole('button', { name: '确认发版' }).click()
  const confirmation = page.getByRole('dialog', { name: '确认发版' })
  await expect(confirmation.getByRole('radio', { name: '发版成功' })).toBeVisible()
  await confirmation.getByRole('radio', { name: '发版失败' }).check()
  await confirmation.getByLabel('实际回滚时间（北京时间）').fill('2026-11-26T15:00')
  await confirmation.getByRole('button', { name: '保存', exact: true }).click()
  await expect(confirmation).toBeHidden()
  await page.getByRole('checkbox', { name: '发版历史' }).check()
  await expect(row.getByText('发版失败')).toBeVisible()
  await expect(row.getByRole('button', { name: '删除', exact: true })).toHaveCount(0)
  await page.goto(`/deployments?plan=${plan.id}`)
  await expect(page).toHaveURL(new RegExp(`/deployments/plans\\?plan=${plan.id}$`))
  await expect(checklist).toBeVisible()
})

test('部署总览按项目列展示，零检查项直接确认，未派发计划可编辑版本引用', async ({ page }) => {
  const version = { id: 1, number: '1.0.0', branch: 'main', sha: 'a'.repeat(40), tag: null, tag_sha: null }
  const plan = { id: 3, project_id: 1, project_name: '项目甲', site: 'beijing', network: 'internal', version,
    status: 'draft', scheduled_at: '2026-11-26T14:00:00+08:00', upgrade_content: '', checklist_count: 0, can_confirm: true, revision: 0 }
  const projects = ['项目甲', '项目乙'].map((name, index) => ({ id: index + 1, name, level: 'regional', network: 'internal', sites: ['beijing', 'shanghai'] }))
  const extraSites = Object.fromEntries(Array.from({ length: 30 }, (_, index) => [`region-${index}`, `机房 ${index + 1}`]))
  await page.route('**/api/**', route => {
    const request = route.request(), { pathname } = new URL(request.url())
    if (pathname.endsWith('/auth/me')) return route.fulfill({ json: { user: { id: 42, display_name: '管理员', roles: ['admin'] }, csrf_token: 'test' } })
    if (pathname.endsWith('/deployments/overview')) return route.fulfill({ json: { projects, history_projects: [],
      sites: { national: '国铁侧', beijing: '北京局', shanghai: '上海局', ...extraSites }, networks: { internal: '内服网' },
      targets: [{ project_id: 2, site: 'shanghai', current: { version: { ...version, number: '2.0.0' }, deployed_at: null } }],
    } })
    if (pathname.endsWith('/plans')) return route.fulfill({ json: planPage([plan]) })
    if (pathname.endsWith('/tags')) return route.fulfill({ json: { items: [{ name: 'v1.1.0', sha: 'b'.repeat(40) }], has_more: false } })
    if (pathname.endsWith('/schedule')) {
      expect(request.postDataJSON().version).toEqual({ number: '1.1.0', branch: 'main', sha: 'a'.repeat(40), tag: 'v1.1.0', tag_sha: 'b'.repeat(40) })
      Object.assign(version, request.postDataJSON().version)
      return route.fulfill({ json: plan })
    }
    if (pathname.endsWith('/notifications/unread')) return route.fulfill({ json: { count: 0 } })
    return route.fulfill({ json: [] })
  })
  await page.goto('/deployments?tab=overview')
  await expect(page).toHaveURL(/\/deployments\/overview$/)
  const overview = page.getByLabel('项目与机房部署总览')
  await expect(overview.getByRole('columnheader')).toHaveText(['部署机房', /项目甲/, /项目乙/])
  await expect(page.getByRole('button', { name: '新增发版计划' })).toHaveCount(0)
  const filter = page.getByRole('combobox', { name: '部署级别' })
  const header = overview.getByRole('columnheader', { name: '部署机房' })
  const filterY = (await filter.boundingBox())?.y, headerY = (await header.boundingBox())?.y
  expect(await overview.evaluate(element => { element.scrollTop = 240; return element.scrollTop })).toBeGreaterThan(0)
  expect((await header.boundingBox())?.y).toBe(headerY)
  expect((await filter.boundingBox())?.y).toBe(filterY)
  await overview.evaluate(element => { element.scrollTop = 0 })
  const shanghai = overview.getByRole('row').filter({ has: page.getByRole('rowheader', { name: '上海局' }) })
  await expect(shanghai.getByRole('cell').nth(1)).toContainText('2.0.0')
  await shanghai.getByRole('button', { name: '2.0.0', exact: true }).click()
  await expect(page).toHaveURL(/\/deployments\/plans\?history=true&project_id=2&site=shanghai$/)
  await page.reload()
  await expect(page.getByRole('checkbox', { name: '发版历史' })).toBeChecked()
  await expect(page.getByRole('checkbox', { name: '待执行' })).not.toBeChecked()
  await expect(page.getByRole('combobox', { name: '项目', exact: true })).toHaveValue('2')
  await expect(page.getByRole('combobox', { name: '机房', exact: true })).toHaveValue('shanghai')
  await page.goBack()
  await expect(overview).toBeVisible()
  await page.getByRole('button', { name: '发版计划', exact: true }).click()
  await expect(page.getByRole('button', { name: '备忘检查', exact: true })).toBeDisabled()
  await expect(page.getByTitle('无需检查')).toBeVisible()
  await expect(page.getByRole('button', { name: '确认发版', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: '修改', exact: true }).click()
  const edit = page.getByRole('dialog', { name: '修改发版计划' })
  await expect(edit).toHaveCSS('border-top-width', '4px')
  await edit.getByLabel('版本号', { exact: true }).fill('1.1.0')
  await expect(edit.getByRole('combobox', { name: 'GitLab 分支（选填）' })).toHaveValue('main')
  await edit.getByRole('combobox', { name: 'GitLab 标签（选填）' }).click()
  await edit.getByRole('option', { name: /v1\.1\.0/ }).click()
  await edit.getByRole('button', { name: '保存', exact: true }).click()
  await expect(edit).toBeHidden()
  await expect(page.getByRole('cell', { name: '1.1.0', exact: true })).toBeVisible()
})

test('任务看板和任务列表的发版检查直达命名子路由', async ({ page }) => {
  const week = mondayOf(todayShanghai())
  const task = { id: 8, task_group: '核对配置', deployment_plan_id: 7, category_name: '发版检查',
    description: '', work_days: [], notes: '', status: '未开始', position: 0, priority: '高' }
  await page.route('**/api/**', route => {
    const { pathname } = new URL(route.request().url())
    if (pathname.endsWith('/auth/me')) return route.fulfill({ json: {
      user: { id: 42, username: 'member', display_name: '测试成员', role: 'user' }, csrf_token: 'test',
    } })
    if (pathname.endsWith('/work-context')) return route.fulfill({ json: { current_week: week, members: [] } })
    if (pathname.endsWith(`/weeks/${week}`)) return route.fulfill({ json: { revision: 0, tasks: [task] } })
    if (pathname.endsWith('/board-tasks')) return route.fulfill({ json: {
      current_week: week, tasks: [{ ...task, name: task.task_group, state: 'inbox' }],
    } })
    if (pathname.endsWith('/deployments/overview')) return route.fulfill({ json: {
      projects: [], history_projects: [], sites: { beijing: '北京局' }, networks: {}, targets: [],
    } })
    if (pathname.endsWith('/deployments/plans')) return route.fulfill({ json: planPage() })
    if (pathname.endsWith('/deployments/plans/7')) return route.fulfill({ json: {
      id: 7, project_name: '计划项目', site: 'beijing', version: { number: '1.0.0' }, status: 'ready', items: [],
    } })
    return route.fulfill({ json: [] })
  })
  for (const source of ['/task-board', '/work']) {
    await page.goto(source)
    const link = page.getByRole('link', { name: '查看机房发版计划' })
    await expect(link).toHaveAttribute('href', '/deployments/plans?plan=7')
    await link.click()
    await expect(page).toHaveURL(/\/deployments\/plans\?plan=7$/)
    await expect(page.getByRole('dialog', { name: '备忘检查清单' })).toContainText('计划项目')
  }
})

test('发版计划共用筛选条件，混合范围支持分页', async ({ page }) => {
  const plans = [
    { id: 1, project_name: '待执行项目', status: 'ready' },
    { id: 2, project_name: '历史项目', status: 'succeeded' },
    { id: 3, project_name: '第二页历史', status: 'failed' },
  ].map(row => ({ ...row, version: { number: '1.0.0' }, site: 'beijing', network: 'internal', checklist_count: 0 }))
  await page.route('**/api/**', route => {
    const { pathname, searchParams } = new URL(route.request().url())
    if (pathname.endsWith('/auth/me')) return route.fulfill({ json: { user: { id: 1, role: 'admin' }, csrf_token: 'test' } })
    if (pathname.endsWith('/deployments/overview')) return route.fulfill({ json: {
      projects: [], history_projects: [], sites: { beijing: '北京局' }, networks: { internal: '内服网' }, targets: [],
    } })
    if (pathname.endsWith('/deployments/plans')) {
      if (!searchParams.has('history')) return route.fulfill({ json: planPage([plans[0]]) })
      expect(searchParams.get('include_open')).toBe('true')
      if (searchParams.get('status') === 'ready') return route.fulfill({ json: planPage([plans[0]]) })
      if (searchParams.get('page') === '2') return route.fulfill({ json: planPage([plans[2]], 21, 2) })
      return route.fulfill({ json: planPage(plans.slice(0, 2), 21) })
    }
    return route.fulfill({ json: [] })
  })
  await page.goto('/deployments/plans')
  await expect(page.locator('.page-top .top-actions button')).toHaveText(['新增发版计划', '补录部署基线', '消息中心'])
  await expect(page.getByRole('checkbox', { name: '待执行' })).toBeChecked()
  const history = page.getByRole('checkbox', { name: '发版历史' })
  await expect(history).not.toBeChecked()
  const names = page.getByRole('rowheader')
  await expect(names).toHaveText(['待执行项目'])
  await history.check()
  await expect(names).toHaveText(['待执行项目', '历史项目'])
  await page.getByRole('button', { name: '下一页' }).click()
  await expect(names).toHaveText(['第二页历史'])
  await expect(page).toHaveURL(/page=2$/)
  await page.getByRole('combobox', { name: '发版状态' }).selectOption('ready')
  await page.getByRole('button', { name: '查询', exact: true }).click()
  await expect(names).toHaveText(['待执行项目'])
  await expect(page.getByRole('button', { name: '上一页' })).toBeDisabled()
})

test('备忘页头显示状态和新增入口，可确认删除备忘', async ({ page }) => {
  let removed = false
  await page.route('**/api/**', route => {
    const { pathname } = new URL(route.request().url())
    if (pathname.endsWith('/auth/me')) return route.fulfill({ json: { user: { id: 1, role: 'user' }, csrf_token: 'test' } })
    if (pathname.endsWith('/deployments/overview')) return route.fulfill({ json: {
      projects: [{ id: 1, name: '项目甲', network: 'internal', sites: ['beijing'] }], history_projects: [],
      sites: { beijing: '北京局' }, networks: { internal: '内服网' }, targets: [],
    } })
    if (pathname.endsWith('/deployments/memos/5')) {
      expect(route.request().method()).toBe('DELETE')
      removed = true
      return route.fulfill({ status: 204 })
    }
    if (pathname.endsWith('/deployments/memos')) return route.fulfill({ json: removed ? [] : [{ id: 5, project_id: 1,
      title: '升级前核对', done: false, targets: [{ site: 'beijing', done: false }] }] })
    return route.fulfill({ json: [] })
  })
  await page.goto('/deployments/memos')
  const top = page.locator('.page-top .top-actions')
  await expect(top.getByRole('combobox', { name: '备忘状态' })).toHaveValue('pending')
  await expect(top.getByRole('button')).toHaveText(['新增备忘', '消息中心'])
  const memo = page.getByRole('article').filter({ hasText: '升级前核对' })
  await expect(memo.getByText('发版进度（0/1）')).toBeVisible()
  page.once('dialog', dialog => dialog.dismiss())
  await memo.getByRole('button', { name: '删除' }).click()
  await expect(memo).toBeVisible()
  expect(removed).toBe(false)
  page.once('dialog', dialog => dialog.accept())
  await memo.getByRole('button', { name: '删除' }).click()
  await expect(memo).toHaveCount(0)
  await expect(page.getByRole('status')).toHaveText('备忘已删除')
})
