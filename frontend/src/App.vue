<script setup lang="ts">
import { version } from '../package.json'
const brandLogo = `${import.meta.env.BASE_URL}logo.png`
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import MonthCalendar from './MonthCalendar.vue'
import MeetingEditor from './MeetingEditor.vue'
import TaskTable from './TaskTable.vue'
import { api, ApiError, newIdempotencyKey, setCsrf } from './api'
import { mondayOf, mondayToWeekInput, todayShanghai, weekInputToMonday, weeksInRange } from './dates'
import { moveReportTab, restoreReportTabOrder } from './reportTabOrder'
import type { Category, Meeting, MeetingPage, ReportTab, Task, TaskField, User, WeekData } from './types'

const route = useRoute(), router = useRouter()
const user = ref<User | null>(null), ready = ref(false), mobileOpen = ref(false)
const selectedWeek = ref(mondayOf(todayShanghai()))
const week = ref<WeekData>({ revision: 0, tasks: [] })
const categories = ref<Category[]>([]), users = ref<User[]>([]), tabs = ref<ReportTab[]>([])
const activeTab = ref<number | null>(null), reportTasks = ref<Task[]>([])
const draggedReportTabId = ref<number | null>(null)
const calendarKey = ref(0)
const meetings = ref<MeetingPage>({ items: [], total: 0, page: 1, page_size: 10 })
const meetingPage = ref(1), meetingOpen = ref(false), meetingDraft = ref<Meeting | null>(null)
const meetingFilter = reactive({ date_from: '', date_to: '', content: '', status: '' })
const notice = ref(''), saveStatus = ref<'saved' | 'saving' | 'failed' | 'conflict'>('saved')
const mutating = ref(false)
const newCategory = ref(''), categoryDrafts = reactive<Record<number, string>>({})
const newUser = reactive({ username: '', display_name: '', password: '', role: 'user' as 'user' | 'admin', status: '正常' as User['status'] })
const userDrafts = reactive<Record<number, { username: string; display_name: string; role: 'user' | 'admin'; status: User['status']; password: string }>>({})
const passwordForm = reactive({ old_password: '', new_password: '', confirm_password: '' })
const modal = ref<null | { kind: 'delete'; taskId: number } | { kind: 'carry' }>(null)
const modalFirst = ref<HTMLButtonElement | null>(null)
const reportExportOpen = ref(false), reportExporting = ref(false), reportExportError = ref('')
const reportExportStart = ref(''), reportExportEnd = ref('')
const reportExportStartInput = ref<HTMLInputElement | null>(null)
const page = computed(() => String(route.name || 'work'))
const title = computed(() => ({ work: '本周工作', reports: '周报汇总', categories: '我的任务类型', meetings: '会议记录', users: '用户管理', password: '修改密码' }[page.value] || '周报'))
let timer: ReturnType<typeof setTimeout> | null = null
let maxWaitTimer: ReturnType<typeof setTimeout> | null = null
let flushPromise: Promise<void> | null = null
let structuralPromise: Promise<void> | null = null
let queue: Promise<unknown> = Promise.resolve()
let loadSerial = 0
let signingOut = false
const drafts = new Map<number, Partial<TaskField>>()

function showError(error: unknown) { notice.value = error instanceof ApiError ? error.message : '操作失败，请重试。' }
function storedReportTabOrder() {
  try {
    const saved = JSON.parse(localStorage.getItem(`zhoubao.report-tabs.${user.value?.id}`) || '[]')
    return Array.isArray(saved) ? saved.filter((id): id is number => Number.isInteger(id)) : []
  } catch { return [] }
}
function saveReportTabOrder() {
  try { localStorage.setItem(`zhoubao.report-tabs.${user.value?.id}`, JSON.stringify(tabs.value.map(tab => tab.id))) } catch { /* 本地存储不可用时仍保留当前页面顺序。 */ }
}
function startReportTabDrag(event: DragEvent, id: number) {
  draggedReportTabId.value = id
  if (event.dataTransfer) { event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', String(id)) }
}
function allowReportTabDrop(event: DragEvent) {
  if (draggedReportTabId.value !== null) { event.preventDefault(); if (event.dataTransfer) event.dataTransfer.dropEffect = 'move' }
}
function dropReportTab(event: DragEvent, targetId: number) {
  const draggedId = draggedReportTabId.value
  if (draggedId === null) return
  event.preventDefault()
  const target = event.currentTarget as HTMLElement, rect = target.getBoundingClientRect()
  const next = moveReportTab(tabs.value, draggedId, targetId, event.clientX > rect.left + rect.width / 2)
  if (next !== tabs.value) { tabs.value = next; saveReportTabOrder() }
  draggedReportTabId.value = null
}
function localizeInvalid(event: Event) {
  const field = event.target as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
  field.setCustomValidity('')
  if (field.validity.valueMissing) field.setCustomValidity('请填写此项。')
  else if (field.validity.tooShort) field.setCustomValidity(`至少输入 ${field.getAttribute('minlength')} 个字符。`)
  else if (field.validity.patternMismatch) field.setCustomValidity('输入格式不正确。')
  else field.setCustomValidity('请输入有效内容。')
}
function clearValidation(event: Event) { (event.target as HTMLInputElement).setCustomValidity?.('') }
function enqueue<T>(job: () => Promise<T>) {
  const result = queue.then(job)
  queue = result.catch(() => undefined)
  return result
}
function hasPending() { return drafts.size > 0 || !!flushPromise || !!structuralPromise || saveStatus.value === 'failed' || saveStatus.value === 'conflict' }
function beforeUnload(event: BeforeUnloadEvent) { if (hasPending()) { event.preventDefault(); event.returnValue = '' } }

async function flushPending(): Promise<void> {
  if (timer) { clearTimeout(timer); timer = null }
  if (maxWaitTimer) { clearTimeout(maxWaitTimer); maxWaitTimer = null }
  if (flushPromise) return flushPromise
  flushPromise = (async () => {
    while (drafts.size) {
      const entry = drafts.entries().next().value as [number, Partial<TaskField>]
      const [id, patch] = entry
      drafts.delete(id)
      saveStatus.value = 'saving'
      try {
        const response = await enqueue(() => api<WeekData>(`/weeks/${selectedWeek.value}/tasks/${id}?revision=${week.value.revision}`, 'PATCH', patch))
        week.value.revision = response.revision
        calendarKey.value++
      } catch (error) {
        drafts.set(id, { ...patch, ...drafts.get(id) })
        saveStatus.value = error instanceof ApiError && error.status === 409 ? 'conflict' : 'failed'
        showError(error)
        throw error
      }
    }
    saveStatus.value = 'saved'
  })()
  try { await flushPromise } finally {
    flushPromise = null
    if (drafts.size && saveStatus.value !== 'failed' && saveStatus.value !== 'conflict' && !timer) timer = setTimeout(() => { void flushPending().catch(() => undefined) }, 500)
  }
}
async function resolveConflict() {
  try {
    const latest = await api<WeekData>(`/weeks/${selectedWeek.value}`)
    for (const [id, patch] of drafts) {
      const row = latest.tasks.find(item => item.id === id)
      if (!row) { notice.value = '该任务已在其他标签页删除，请复制当前内容后刷新页面。'; return }
      Object.assign(row, patch)
    }
    week.value = latest
    saveStatus.value = 'saving'
    await flushPending()
    notice.value = ''
  } catch (error) { showError(error) }
}

function editTask(id: number, patch: Partial<TaskField>) {
  const task = week.value.tasks.find(item => item.id === id)
  if (!task) return
  Object.assign(task, patch)
  drafts.set(id, { ...drafts.get(id), ...patch })
  if (saveStatus.value === 'conflict') return
  saveStatus.value = 'saving'
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => { void flushPending().catch(() => undefined) }, 500)
  if (!maxWaitTimer) maxWaitTimer = setTimeout(() => { void flushPending().catch(() => undefined) }, 2000)
}

async function structural(job: () => Promise<WeekData>) {
  if (structuralPromise) return structuralPromise
  mutating.value = true
  structuralPromise = (async () => {
    try {
      await flushPending()
      const response = await enqueue(job)
      week.value = response
      calendarKey.value++
      notice.value = response.no_source ? '上周没有未完成任务，本周未作修改。' : ''
    } catch (error) { showError(error) } finally { mutating.value = false }
  })()
  try { await structuralPromise } finally { structuralPromise = null }
}
function addTask() { void structural(() => api(`/weeks/${selectedWeek.value}/tasks?revision=${week.value.revision}`, 'POST', undefined, newIdempotencyKey())) }
function duplicateTask(id: number) { void structural(() => api(`/weeks/${selectedWeek.value}/tasks/${id}/duplicate?revision=${week.value.revision}`, 'POST', undefined, newIdempotencyKey())) }
function reorderTasks(ids: number[]) { void structural(() => api(`/weeks/${selectedWeek.value}/tasks/order?revision=${week.value.revision}`, 'PUT', { task_ids: ids })) }
function askDelete(id: number) { openModal({ kind: 'delete', taskId: id }) }
function openModal(value: NonNullable<typeof modal.value>) { modal.value = value; void nextTick(() => modalFirst.value?.focus()) }
async function confirmDelete(id: number) {
  modal.value = null
  await structural(() => api(`/weeks/${selectedWeek.value}/tasks/${id}?revision=${week.value.revision}`, 'DELETE'))
}
async function startCarry() {
  try {
    if (structuralPromise) await structuralPromise
    await flushPending()
    const requestedWeek = selectedWeek.value
    const sourceWeek = new Date(`${selectedWeek.value}T12:00:00Z`)
    sourceWeek.setUTCDate(sourceWeek.getUTCDate() - 7)
    const previous = await api<WeekData>(`/weeks/${sourceWeek.toISOString().slice(0,10)}`)
    if (selectedWeek.value !== requestedWeek || page.value !== 'work') return
    if (!previous.tasks.some(task => task.status !== '已完成')) { notice.value = '上周没有未完成任务，本周未作修改。'; return }
    if (week.value.tasks.length) openModal({ kind: 'carry' })
    else await carry('append')
  } catch (error) { showError(error) }
}
async function carry(mode: 'append' | 'overwrite') {
  modal.value = null
  await structural(() => api(`/weeks/${selectedWeek.value}/carry-over?revision=${week.value.revision}`, 'POST', { mode }, newIdempotencyKey()))
}

async function loadPage() {
  if (!user.value || page.value === 'login') return
  const serial = ++loadSerial
  try {
    if (page.value === 'work') {
      week.value = { revision: 0, tasks: [] }
      const [weekData, categoryData] = await Promise.all([api<WeekData>(`/weeks/${selectedWeek.value}`), api<Category[]>('/categories')])
      if (serial !== loadSerial) return
      week.value = weekData; categories.value = categoryData
    } else if (page.value === 'reports') {
      reportTasks.value = []
      const newTabs = await api<ReportTab[]>(`/reports/${selectedWeek.value}`)
      if (serial !== loadSerial) return
      tabs.value = restoreReportTabOrder(newTabs, storedReportTabOrder())
      if (!newTabs.some(tab => tab.id === activeTab.value)) activeTab.value = newTabs[0]?.id || null
      if (activeTab.value) {
        const requestedTab = activeTab.value
        const response = await api<WeekData>(`/reports/${selectedWeek.value}/users/${requestedTab}`)
        if (serial === loadSerial && activeTab.value === requestedTab) reportTasks.value = response.tasks
      }
    } else if (page.value === 'categories') {
      categories.value = await api<Category[]>('/categories')
      categories.value.forEach(item => { categoryDrafts[item.id] = item.name })
    } else if (page.value === 'users' && user.value.role === 'admin') {
      users.value = await api<User[]>('/users')
      users.value.forEach(item => { userDrafts[item.id] = { username: item.username, display_name: item.display_name, role: item.role, status: item.status, password: '' } })
    } else if (page.value === 'meetings') {
      await loadMeetings()
    }
    notice.value = ''
  } catch (error) { showError(error) }
}
async function loadMeetings() {
  const params = new URLSearchParams({ page: String(meetingPage.value), page_size: '10' })
  if (meetingFilter.date_from) params.set('date_from', meetingFilter.date_from)
  if (meetingFilter.date_to) params.set('date_to', meetingFilter.date_to)
  if (meetingFilter.content.trim()) params.set('content', meetingFilter.content.trim())
  if (meetingFilter.status) params.set('status', meetingFilter.status)
  meetings.value = await api<MeetingPage>(`/meetings?${params}`)
}
async function searchMeetings() { meetingPage.value = 1; try { await loadMeetings() } catch (error) { showError(error) } }
async function turnMeetingPage(offset: number) { meetingPage.value += offset; try { await loadMeetings() } catch (error) { meetingPage.value -= offset; showError(error) } }
function openMeeting(meeting: Meeting | null = null) { meetingDraft.value = meeting; meetingOpen.value = true }
async function meetingSaved() { meetingOpen.value = false; notice.value = '会议记录已保存。'; if (page.value === 'meetings') { meetingPage.value = 1; try { await loadMeetings() } catch (error) { showError(error) } } }
async function removeMeeting(meeting: Meeting) {
  if (!window.confirm(`删除 ${meeting.meeting_date} 的会议记录？`)) return
  try { await api(`/meetings/${meeting.id}`, 'DELETE'); await loadMeetings() } catch (error) { showError(error) }
}
async function chooseTab(id: number) {
  activeTab.value = id; reportTasks.value = []
  const requestedWeek = selectedWeek.value
  try {
    const response = await api<WeekData>(`/reports/${requestedWeek}/users/${id}`)
    if (activeTab.value === id && selectedWeek.value === requestedWeek && page.value === 'reports') reportTasks.value = response.tasks
  } catch (error) { showError(error) }
}
function openReportExport() {
  reportExportStart.value = mondayToWeekInput(selectedWeek.value)
  reportExportEnd.value = reportExportStart.value
  reportExportError.value = ''
  reportExportOpen.value = true
  void nextTick(() => reportExportStartInput.value?.focus())
}
async function exportReports() {
  const start = weekInputToMonday(reportExportStart.value), end = weekInputToMonday(reportExportEnd.value)
  if (!start || !end || !weeksInRange(start, end).length) { reportExportError.value = '请选择有效的起止周，且起始周不能晚于结束周。'; return }
  reportExporting.value = true
  reportExportError.value = ''
  try {
    const people = new Map<number, { name: string; rows: (string | number)[][] }>()
    const dayNames = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    for (const weekStart of weeksInRange(start, end)) {
      const members = await api<ReportTab[]>(`/reports/${weekStart}`)
      const reports = await Promise.all(members.map(async member => ({ member, tasks: (await api<WeekData>(`/reports/${weekStart}/users/${member.id}`)).tasks })))
      for (const { member, tasks } of reports) {
        const person = people.get(member.id) || { name: member.name, rows: [] }
        for (const task of tasks) person.rows.push([weekStart, task.category_name || '', task.task_group, task.description, task.status || '未开始', task.work_days.map(day => dayNames[day - 1]).join('、'), task.notes])
        people.set(member.id, person)
      }
    }
    if (!people.size) { reportExportError.value = '所选周范围内没有可导出的成员。'; return }
    const { downloadReportWorkbook } = await import('./reportExport')
    downloadReportWorkbook([...people.values()], `周报汇总_${start}_${end}.xlsx`)
    reportExportOpen.value = false
  } catch (error) { reportExportError.value = error instanceof ApiError ? error.message : '生成 Excel 失败，请重试。' }
  finally { reportExporting.value = false }
}
async function selectWeek(value: string, refresh = false) {
  if (value === selectedWeek.value && !refresh) return
  try { if (structuralPromise) await structuralPromise; await flushPending(); selectedWeek.value = value; if (refresh) calendarKey.value++; await loadPage() } catch { notice.value = '当前修改尚未保存，请先重试。' }
}
async function navigate(name: string) {
  if (page.value === name) { mobileOpen.value = false; return }
  try { if (structuralPromise) await structuralPromise; await flushPending(); await router.push(`/${name}`); mobileOpen.value = false } catch { notice.value = '当前修改尚未保存，请先重试。' }
}
async function login(event: Event) {
  try {
    const form = new FormData(event.currentTarget as HTMLFormElement)
    const result = await api<{ user: User; csrf_token: string }>('/auth/login', 'POST', { username: form.get('username'), password: form.get('password') })
    user.value = result.user; setCsrf(result.csrf_token); notice.value = ''
    await router.replace(result.user.must_change_password ? '/password' : '/work')
    await loadPage()
  } catch (error) { showError(error) }
}
async function logout() {
  try { if (structuralPromise) await structuralPromise; await flushPending(); await api('/auth/logout', 'POST'); signingOut = true; await router.replace('/login'); user.value = null; setCsrf('') } catch (error) { showError(error) } finally { signingOut = false }
}
async function showLoginAfterRevocation() {
  signingOut = true
  try { await router.replace('/login'); user.value = null; setCsrf('') } finally { signingOut = false }
}
async function changePassword() {
  if (passwordForm.new_password !== passwordForm.confirm_password) { notice.value = '两次输入的新密码不一致。'; return }
  try { await api('/auth/password', 'POST', { old_password: passwordForm.old_password, new_password: passwordForm.new_password }); await showLoginAfterRevocation(); passwordForm.old_password = ''; passwordForm.new_password = ''; passwordForm.confirm_password = ''; notice.value = '密码已更新，请重新登录。' } catch (error) { showError(error) }
}
async function addCategory() {
  try { await api('/categories', 'POST', { name: newCategory.value }); newCategory.value = ''; await loadPage() } catch (error) { showError(error) }
}
async function renameCategory(id: number) {
  try { await api(`/categories/${id}`, 'PATCH', { name: categoryDrafts[id] }); await loadPage() } catch (error) { showError(error) }
}
async function deleteCategory(id: number) {
  if (!window.confirm('删除这个任务类型？已有任务仍保留原名称。')) return
  try { await api(`/categories/${id}`, 'DELETE'); await loadPage() } catch (error) { showError(error) }
}
async function createUser() {
  try { await api('/users', 'POST', newUser); Object.assign(newUser, { username: '', display_name: '', password: '', role: 'user', status: '正常' }); await loadPage() } catch (error) { showError(error) }
}
async function saveUser(id: number) {
  try {
    const updated = await api<User>(`/users/${id}`, 'PATCH', { username: userDrafts[id].username, display_name: userDrafts[id].display_name, role: userDrafts[id].role, status: userDrafts[id].status })
    if (user.value?.id === id && (user.value.role !== updated.role || updated.status === '锁定')) { await showLoginAfterRevocation(); return }
    if (user.value?.id === id) user.value = updated
    await loadPage()
  } catch (error) { showError(error) }
}
async function toggleUser(item: User) {
  if (item.is_active && !window.confirm(`停用 ${item.display_name}？历史周报会保留。`)) return
  try { await api(`/users/${item.id}`, 'PATCH', { is_active: !item.is_active }); if (user.value?.id === item.id && item.is_active) await showLoginAfterRevocation(); else await loadPage() } catch (error) { showError(error) }
}
async function resetPassword(id: number) {
  try { await api(`/users/${id}/password`, 'POST', { password: userDrafts[id].password }); userDrafts[id].password = ''; if (user.value?.id === id) await showLoginAfterRevocation(); notice.value = '密码已重置，用户需重新登录。' } catch (error) { showError(error) }
}

const removeRouteGuard = router.beforeEach(async (to, from) => {
  if (!ready.value || !user.value || to.path === from.path) return
  if (to.name === 'login' && !signingOut) return user.value.must_change_password ? '/password' : '/work'
  if (user.value.must_change_password && to.name !== 'password' && !signingOut) return '/password'
  if (to.name === 'users' && user.value.role !== 'admin') return '/work'
  if (hasPending()) {
    try { if (structuralPromise) await structuralPromise; await flushPending() } catch { notice.value = '当前修改尚未保存，请先重试。'; return false }
  }
})
onMounted(async () => {
  window.addEventListener('beforeunload', beforeUnload)
  document.addEventListener('invalid', localizeInvalid, true)
  document.addEventListener('input', clearValidation, true)
  document.addEventListener('change', clearValidation, true)
  try { const result = await api<{ user: User; csrf_token: string }>('/auth/me'); user.value = result.user; setCsrf(result.csrf_token) }
  catch { await router.replace('/login') }
  ready.value = true
  if (user.value?.must_change_password) await router.replace('/password')
  else if (user.value && (page.value === 'login' || (page.value === 'users' && user.value.role !== 'admin'))) await router.replace('/work')
  if (user.value) await loadPage()
})
onUnmounted(() => { removeRouteGuard(); window.removeEventListener('beforeunload', beforeUnload); document.removeEventListener('invalid', localizeInvalid, true); document.removeEventListener('input', clearValidation, true); document.removeEventListener('change', clearValidation, true); if (timer) clearTimeout(timer); if (maxWaitTimer) clearTimeout(maxWaitTimer) })
watch(() => route.name, () => { if (ready.value && user.value) void loadPage() })
</script>

<template>
  <div v-if="!ready" class="loading">正在加载周报…</div>
  <main v-else-if="!user" class="login-screen"><div class="login-poster"><span class="eyebrow">每周工作 / 团队周报</span><h1>把一周<br>写成进展。</h1><p>清晰记录每一天，也看见整个团队。</p></div><form class="login-panel" @submit.prevent="login"><span class="eyebrow">01 / 用户登录</span><h2>登录周报</h2><label>用户名<input name="username" autocomplete="username" required /></label><label>密码<input name="password" type="password" autocomplete="current-password" required /></label><button class="primary-button" type="submit">进入工作台 →</button><p v-if="notice" class="message error" role="alert">{{ notice }}</p></form></main>
  <div v-else class="shell">
    <button class="mobile-toggle" type="button" :aria-expanded="mobileOpen" aria-label="打开或关闭导航" @click="mobileOpen = !mobileOpen">☰ 菜单</button>
    <aside class="sidebar" :class="{ open: mobileOpen }"><div class="brand"><img class="brand-mark" :src="brandLogo" alt="周报" /><div><strong>周报</strong><small>当前版本：v{{ version }}</small></div></div>
      <nav v-if="!user.must_change_password" aria-label="主导航"><button type="button" :class="{ active: page === 'work' }" @click="navigate('work')">▣ 本周工作</button><button type="button" :class="{ active: page === 'reports' }" @click="navigate('reports')">▤ 周报汇总</button><button type="button" :class="{ active: page === 'categories' }" @click="navigate('categories')">▥ 任务类型</button><button type="button" :class="{ active: page === 'meetings' }" @click="navigate('meetings')">▧ 会议记录</button><button v-if="user.role === 'admin'" type="button" :class="{ active: page === 'users' }" @click="navigate('users')">▦ 用户管理</button></nav>
      <MonthCalendar v-if="page === 'work' || page === 'reports'" :selected="selectedWeek" :scope="page" :refresh-key="calendarKey" @select="selectWeek" />
      <button v-if="page === 'reports'" class="primary-button sidebar-meeting" type="button" @click="openMeeting()">＋ 新增会议记录</button>
      <div class="sidebar-bottom"><div class="identity"><strong>{{ user.display_name }}</strong><span>{{ user.role === 'admin' ? '管理员' : '普通用户' }} · {{ user.username }}</span></div><button type="button" @click="navigate('password')">修改密码</button><button type="button" @click="logout">退出登录 ↗</button></div>
    </aside>
    <main class="content"><div class="page-top"><div><span class="eyebrow">周报系统 / {{ title }}</span><h1>{{ title }}</h1><p v-if="page === 'work' || page === 'reports'" class="date-range">{{ selectedWeek }} 至 {{ new Date(new Date(`${selectedWeek}T12:00:00Z`).getTime() + 6 * 86400000).toISOString().slice(0,10) }}</p></div><div v-if="page === 'work' || page === 'reports'" class="top-actions"><template v-if="page === 'work'"><button class="secondary-button" type="button" :disabled="mutating" @click="startCarry">↖ 复制上周未完成</button><button class="primary-button" type="button" :disabled="mutating" @click="addTask">＋ 新增任务</button></template><button v-else class="primary-button" type="button" :disabled="reportExporting" @click="openReportExport">⇩ 导出Excel</button></div></div>
      <p v-if="notice" class="message" :class="{ error: saveStatus === 'failed' || saveStatus === 'conflict' }" role="alert">{{ notice }}</p>
      <div v-if="page === 'work'" class="work-area"><div class="section-head"><strong>任务清单 <span>{{ week.tasks.length }}</span></strong><div class="save-indicator" role="status">{{ { saved:'✓ 已保存', saving:'… 保存中', failed:'! 保存失败', conflict:'! 内容冲突' }[mutating ? 'saving' : saveStatus] }}<button v-if="saveStatus === 'failed'" type="button" @click="flushPending">重试</button><button v-if="saveStatus === 'conflict'" type="button" @click="resolveConflict">用当前修改重试</button></div></div><TaskTable :key="selectedWeek" :tasks="week.tasks" :categories="categories" :busy="mutating" @edit="editTask" @duplicate="duplicateTask" @remove="askDelete" @reorder="reorderTasks" /></div>
      <div v-else-if="page === 'reports'"><div v-if="tabs.length" class="tabs" role="tablist" aria-label="成员"><button v-for="tab in tabs" :key="tab.id" type="button" role="tab" draggable="true" title="拖动调整成员顺序" :aria-selected="activeTab === tab.id" :class="{ selected: activeTab === tab.id, dragging: draggedReportTabId === tab.id }" @click="chooseTab(tab.id)" @dragstart="startReportTabDrag($event, tab.id)" @dragover="allowReportTabDrop" @drop="dropReportTab($event, tab.id)" @dragend="draggedReportTabId = null">{{ tab.name }}<small v-if="!tab.is_active">（已停用）</small></button></div><div v-else class="empty">暂无成员记录。</div><TaskTable v-if="activeTab" :tasks="reportTasks" readonly /></div>
      <section v-else-if="page === 'categories'" class="panel"><p>为自己的任务维护类型；修改或删除后，历史任务名称保持原样。系统内置类型所有人可直接选择。</p><form class="inline-form" @submit.prevent="addCategory"><label>新任务类型<input v-model="newCategory" maxlength="100" required placeholder="例如：产品开发" /></label><button class="primary-button" type="submit">新增类型</button></form><div v-for="category in categories" :key="category.id" class="list-row"><input v-model="categoryDrafts[category.id]" :aria-label="`任务类型 ${category.name}`" maxlength="100" /><button class="mini-button" type="button" @click="renameCategory(category.id)">保存名称</button><button class="mini-button danger" type="button" @click="deleteCategory(category.id)">删除</button></div><div v-if="!categories.length" class="empty">还没有个人任务类型，可在上方新增。</div></section>
      <section v-else-if="page === 'meetings'" class="meetings-page"><form class="meeting-filters panel" @submit.prevent="searchMeetings"><label>开始日期<input v-model="meetingFilter.date_from" type="date" /></label><label>结束日期<input v-model="meetingFilter.date_to" type="date" /></label><label>会议内容<input v-model="meetingFilter.content" placeholder="模糊搜索" /></label><label>任务状态<select v-model="meetingFilter.status"><option value="">全部</option><option value="已完成">已完成</option><option value="未完成">未完成</option><option value="未选择">未选择</option></select></label><button class="secondary-button" type="submit">查询</button><button class="primary-button" type="button" @click="openMeeting()">＋ 新增会议记录</button></form><div class="meeting-list"><article v-for="item in meetings.items" :key="item.id" class="meeting-card"><div class="meeting-card-head"><div><strong>{{ item.meeting_date }}</strong><span>{{ item.meeting_type }}</span><small class="meeting-person">创建人：{{ item.creator?.display_name || '未知' }}</small><small class="meeting-person">更新人：{{ item.updaters.map(person => person.display_name).join('、') || '暂无' }}</small></div><div class="top-actions"><button class="mini-button" type="button" @click="openMeeting(item)">编辑</button><button class="mini-button danger" type="button" @click="removeMeeting(item)">删除</button></div></div><p class="preline">{{ item.content }}</p><div v-if="item.needs_follow_up" class="meeting-tasks"><strong>跟踪任务</strong><div v-for="task in item.tasks" :key="task.id" class="meeting-task-line"><span>{{ task.position }}. {{ task.name }}</span><b>{{ task.status || '未选择' }}</b></div><p v-if="!item.tasks.length">暂无关联任务</p></div></article><div v-if="!meetings.items.length" class="empty">没有符合条件的会议记录。</div></div><div class="meeting-pagination"><span>共 {{ meetings.total }} 条 · 第 {{ meetings.page }} 页</span><button class="mini-button" type="button" :disabled="meetingPage <= 1" @click="turnMeetingPage(-1)">上一页</button><button class="mini-button" type="button" :disabled="meetingPage * meetings.page_size >= meetings.total" @click="turnMeetingPage(1)">下一页</button></div></section>
      <section v-else-if="page === 'users' && user.role === 'admin'" class="panel"><h2>新增用户</h2><form class="user-create" @submit.prevent="createUser"><label>用户名<input v-model="newUser.username" required pattern="[A-Za-z0-9_.-]+" /></label><label>显示姓名<input v-model="newUser.display_name" required /></label><label>初始密码<input v-model="newUser.password" type="password" minlength="6" required /></label><label>角色<select v-model="newUser.role"><option value="user">普通用户</option><option value="admin">管理员</option></select></label><label>状态<select v-model="newUser.status"><option>正常</option><option>锁定</option></select></label><button class="primary-button" type="submit">创建用户</button></form><h2>现有用户</h2><div v-for="item in users" :key="item.id" class="user-row"><div class="user-header"><strong>{{ item.username }}</strong><span>{{ item.is_active ? item.status : '已停用' }}</span></div><div class="user-controls"><label>用户名<input v-model="userDrafts[item.id].username" pattern="[A-Za-z0-9_.-]+" /></label><label>姓名<input v-model="userDrafts[item.id].display_name" /></label><label>角色<select v-model="userDrafts[item.id].role"><option value="user">普通用户</option><option value="admin">管理员</option></select></label><label>状态<select v-model="userDrafts[item.id].status"><option>正常</option><option>锁定</option></select></label><button class="mini-button" type="button" @click="saveUser(item.id)">保存资料</button><button class="mini-button danger" type="button" @click="toggleUser(item)">{{ item.is_active ? '删除用户' : '重新启用' }}</button></div><form class="inline-form" @submit.prevent="resetPassword(item.id)"><label>重置密码<input v-model="userDrafts[item.id].password" type="password" minlength="6" required placeholder="至少 6 位" /></label><button class="mini-button" type="submit">设置新密码</button></form></div></section>
      <section v-else-if="page === 'password'" class="panel narrow"><h2>{{ user.must_change_password ? '首次登录，请修改初始密码' : '修改我的密码' }}</h2><p v-if="user.must_change_password">新密码不能与初始密码相同。修改成功后请重新登录。</p><form class="stack-form" @submit.prevent="changePassword"><label>当前密码<input v-model="passwordForm.old_password" type="password" autocomplete="current-password" required /></label><label>新密码（至少 6 位）<input v-model="passwordForm.new_password" type="password" autocomplete="new-password" minlength="6" required /></label><label>确认新密码<input v-model="passwordForm.confirm_password" type="password" autocomplete="new-password" minlength="6" required /></label><button class="primary-button" type="submit">更新密码</button></form></section>
    </main>
    <div v-if="reportExportOpen" class="modal-scrim" @click.self="reportExportOpen = false" @keydown.esc="reportExportOpen = false"><form class="modal export-modal" role="dialog" aria-modal="true" aria-labelledby="report-export-title" @submit.prevent="exportReports"><span class="eyebrow">周报汇总</span><h2 id="report-export-title">导出 Excel</h2><p>选择起止周，每位成员将单独生成一个工作表。</p><div class="export-weeks"><label>起始周<input ref="reportExportStartInput" v-model="reportExportStart" type="week" required /></label><label>结束周<input v-model="reportExportEnd" type="week" required /></label></div><p v-if="reportExportError" class="message error" role="alert">{{ reportExportError }}</p><div class="modal-actions"><button class="secondary-button" type="button" :disabled="reportExporting" @click="reportExportOpen = false">取消</button><button class="primary-button" type="submit" :disabled="reportExporting">{{ reportExporting ? '生成中…' : '确定并导出' }}</button></div></form></div>
    <div v-if="modal" class="modal-scrim" @keydown.esc="modal = null"><div class="modal" role="dialog" aria-modal="true" :aria-label="modal.kind === 'delete' ? '确认删除任务' : '复制上周任务'"><span class="eyebrow">操作确认</span><h2>{{ modal.kind === 'delete' ? '删除这项任务？' : '本周已有任务' }}</h2><p>{{ modal.kind === 'delete' ? '删除后，该任务将从本周移除。' : '请选择覆盖本周任务，或将上周未完成任务追加到末尾。' }}</p><div class="modal-actions"><template v-if="modal.kind === 'delete'"><button ref="modalFirst" class="secondary-button" type="button" @click="modal = null">取消</button><button class="primary-button" type="button" @click="confirmDelete((modal as { taskId: number }).taskId)">确认删除</button></template><template v-else><button ref="modalFirst" class="secondary-button" type="button" @click="modal = null">取消</button><button class="secondary-button" type="button" @click="carry('append')">新增</button><button class="primary-button" type="button" @click="carry('overwrite')">覆盖</button></template></div></div></div>
    <MeetingEditor v-if="meetingOpen" :meeting="meetingDraft" @close="meetingOpen = false" @saved="meetingSaved" />
  </div>
</template>

