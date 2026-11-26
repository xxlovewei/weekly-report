<script setup lang="ts">
import { taskStatuses, progressStyle } from './taskStatuses'
import { version } from '../package.json'
const brandLogo = `${import.meta.env.BASE_URL}logo.png`
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { isNavigationFailure, NavigationFailureType, useRoute, useRouter } from 'vue-router'
import MonthCalendar from './MonthCalendar.vue'
import MeetingEditor from './MeetingEditor.vue'
import ReleaseNotes from './ReleaseNotes.vue'
import ReviewConfig from './ReviewConfig.vue'
import ReviewRecords from './ReviewRecords.vue'
import MessageCenter from './MessageCenter.vue'
import ScheduledTasks from './ScheduledTasks.vue'
import TaskTable from './TaskTable.vue'
import TaskBoard from './TaskBoard.vue'
import PlanTaskBoard from './PlanTaskBoard.vue'
import { api, ApiError, credentialApi, newIdempotencyKey, setCsrf } from './api'
import { addDays, mondayOf, mondayToWeekInput, todayShanghai, weekInputToMonday, weeksInRange } from './dates'
import { moveReportTab, restoreReportTabOrder } from './reportTabOrder'
import { desktopNotificationPermission, subscribeToMessages } from './notificationStream'
import type { Category, LiveMessage, Meeting, MeetingPage, ReportTab, Task, TaskField, User, UserRole, WeekData } from './types'

const route = useRoute(), router = useRouter()
const user = ref<User | null>(null), ready = ref(false), mobileOpen = ref(false)
const mobileSidebarQuery = window.matchMedia('(max-width: 800px)')
const desktopSidebar = ref(!mobileSidebarQuery.matches), sidebarCollapsed = ref(false)
const compactSidebar = computed(() => desktopSidebar.value && sidebarCollapsed.value)
function updateSidebarViewport(event: MediaQueryListEvent) { desktopSidebar.value = !event.matches }
const navItems = [
  { name: 'work', label: '本周工作', icon: 'M8 7V3h8v4 M3 7h18v13H3z M3 12h18 M10 12v2h4v-2' },
  { name: 'task-board', label: '任务看板', icon: 'M3 5h5v14H3z M10 5h4v10h-4z M16 5h5v7h-5z' },
  { name: 'reports', label: '周报汇总', icon: 'M5 3h14v18H5z M8 16v-3 M12 16V8 M16 16v-5' },
  { name: 'categories', label: '任务类型', icon: 'M3 4h7v7H3z M14 4h7v7h-7z M3 15h7v6H3z M14 15h7v6h-7z' },
  { name: 'meetings', label: '会议记录', icon: 'M4 4h16v12H9l-5 4z M8 8h8 M8 12h5' },
  { name: 'review-records', label: '审查记录', icon: 'M8 5 3 12l5 7 M16 5l5 7-5 7 M14 4l-4 16' },
  { name: 'review-config', label: '审查配置', icon: 'M4 6h16 M4 12h16 M4 18h16 M8 4v4 M16 10v4 M10 16v4' },
  { name: 'scheduled-tasks', label: '定时任务', icon: 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z M12 7v5l3 2' },
  { name: 'users', label: '用户管理', icon: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0z M22 21v-2a4 4 0 0 0-3-4 M17 3a4 4 0 0 1 0 8' },
] as const
const adminPages = ['users', 'review-config', 'scheduled-tasks']
function userRoles(item: User): UserRole[] {
  return item.roles ?? [item.role]
}
function sameRoles(left: UserRole[], right: UserRole[]) {
  return left.length === right.length && left.every(role => right.includes(role))
}
const isAdmin = computed(() => !!user.value && userRoles(user.value).includes('admin'))
const visibleNavItems = computed(() => navItems.filter(item => !adminPages.includes(item.name) || isAdmin.value))
const sidebarTourActive = ref(false)
const seenGuides = new Set<string>()
const selectedWeek = ref(mondayOf(todayShanghai()))
const currentWorkWeek = ref('')
const workMembers = ref<ReportTab[]>([])
const workMember = ref<number | null>(null)
const workLoading = ref(false)
const delegatedWork = computed(() => workMember.value !== null && workMember.value !== user.value?.id)
const futureWork = computed(() => !!currentWorkWeek.value && selectedWeek.value > currentWorkWeek.value)
const workReadonly = computed(() => futureWork.value
  ? delegatedWork.value || selectedWeek.value !== addDays(currentWorkWeek.value, 7)
  : !isAdmin.value && selectedWeek.value !== currentWorkWeek.value)
const canManageOwnWork = computed(() => !workReadonly.value && !delegatedWork.value && !workLoading.value)
const workMemberQuery = computed(() => delegatedWork.value ? `user_id=${workMember.value}` : '')
function workPath(suffix = '', revision = false) {
  const query = [workMemberQuery.value, revision ? `revision=${week.value.revision}` : ''].filter(Boolean).join('&')
  const path = futureWork.value && suffix.startsWith('/tasks') ? suffix.replace('/tasks', '/plans') : suffix
  return `/weeks/${selectedWeek.value}${path}${query ? `?${query}` : ''}`
}
const reviewToday = ref(todayShanghai()), summaryRequest = ref(0), unreadMessages = ref(0)
const showUnreadReminder = ref(false)
const releaseVersion = ref(''), releaseRefreshing = ref(false)
const notificationPermission = ref<ReturnType<typeof desktopNotificationPermission>>(desktopNotificationPermission())
const showPermissionReminder = ref(false), requestingPermission = ref(false)
const liveMessages = ref<LiveMessage[]>([])
const messagesRefresh = ref(0), reviewRefresh = ref(0)
let unreadVersion = 0
const reviewRecords = ref<InstanceType<typeof ReviewRecords> | null>(null)
const reviewDay = computed(() => validDay(route.query.date) || reviewToday.value)
const targetTask = computed(() => typeof route.query.task === 'string' && /^[1-9]\d*$/.test(route.query.task) ? Number(route.query.task) : null)
const targetMeeting = computed(() => typeof route.query.meeting === 'string' && /^[1-9]\d*$/.test(route.query.meeting) ? Number(route.query.meeting) : null)
function validDay(value: unknown) {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value))
    && new Date(value).toISOString().slice(0, 10) === value ? value : null
}
function selectReviewDay(value: string, refresh = false) {
  if (refresh) calendarKey.value++
  reviewToday.value = todayShanghai()
  mobileOpen.value = false
  void router.replace({ name: 'review-records', query: { date: value } })
}
async function refreshUnread() {
  const account = user.value?.id
  const version = ++unreadVersion
  if (!account || user.value?.must_change_password) { unreadMessages.value = 0; return }
  try {
    const { count } = await api<{ count: number }>('/notifications/unread')
    if (user.value?.id !== account || user.value.must_change_password) return
    if (version === unreadVersion) unreadMessages.value = count
  } catch { /* 消息数刷新失败时保留上一次的值。 */ }
}
async function openUnreadReminder() {
  await navigate('messages')
  if (page.value === 'messages') showUnreadReminder.value = false
}
function checkNotificationPermission() {
  notificationPermission.value = desktopNotificationPermission()
  if (notificationPermission.value === 'granted') {
    showPermissionReminder.value = false
    showUnreadReminder.value = false
    liveMessages.value = []
  }
}
async function enableNotifications() {
  checkNotificationPermission()
  if (notificationPermission.value !== 'default' || requestingPermission.value) return
  requestingPermission.value = true
  try { await Notification.requestPermission() }
  catch { /* 浏览器拒绝请求时重新读取当前权限。 */ }
  finally { checkNotificationPermission(); requestingPermission.value = false }
}
function dismissLiveMessage(id: number) {
  liveMessages.value = liveMessages.value.filter(message => message.id !== id)
}
async function openLiveMessage(message: LiveMessage) {
  dismissLiveMessage(message.id)
  await jumpToMessage(message)
}
async function jumpToMessage(item: LiveMessage) {
  const account = user.value?.id
  if (!account) return
  const target = item.target
  const destination = item.kind === '代码审查'
    ? { name: 'review-records', query: { date: target?.date || todayShanghai() } }
    : item.kind === '系统通知' || !target?.board_task ? { name: 'messages' }
      : { name: 'task-board', query: { task: target.board_task } }
  try {
    if (page.value === 'work' && hasPending()) {
      if (structuralPromise) await structuralPromise
      await flushPending()
    }
    const sameReviewDay = page.value === 'review-records' && reviewDay.value === destination.query?.date
    if (sameReviewDay && reviewRecords.value && !await reviewRecords.value.flushReview()) return
    const failure = await router.push(destination)
    const sameLocation = isNavigationFailure(failure, NavigationFailureType.duplicated)
    if (failure && !sameLocation) return
    if (sameReviewDay) reviewRefresh.value++
    if (sameLocation && destination.name === 'task-board') boardTargetRefresh.value++
  } catch (error) {
    showError(error)
    return
  }
  if (item.is_read || user.value?.id !== account) return
  // 跳转后消息组件会卸载，已读请求和徽标刷新由应用继续处理。
  try {
    await api(`/notifications/${item.id}`, 'PATCH', { is_read: true })
    await refreshUnread()
  } catch {
    messageJumpNotice.value = '已打开目标页面，但消息未能标为已读。请回到消息中心重试。'
  }
}
const messageJumpNotice = ref('')
const boardTargetRefresh = ref(0)
watch(() => route.fullPath, () => {
  messageJumpNotice.value = ''
  if (route.name === 'work' && route.query.task) workMember.value = null
}, { flush: 'sync' })
watch(() => user.value?.id, () => {
  workMember.value = null
  currentWorkWeek.value = ''
  workMembers.value = []
})
const week = ref<WeekData>({ revision: 0, tasks: [] })
const workTasks = computed(() => futureWork.value ? week.value.plans ?? [] : week.value.tasks)
const planBoardOpen = ref(false), planBoardTrigger = ref<HTMLButtonElement | null>(null)
const draggedPlanCard = ref<number | null>(null), planDropActive = ref(false)
const plannedCardIds = computed(() => new Set((week.value.plans ?? []).flatMap(plan => plan.board_task_id == null ? [] : [plan.board_task_id])))
const categories = ref<Category[]>([]), users = ref<User[]>([]), tabs = ref<ReportTab[]>([])
const activeTab = ref<number | null>(null), reportTasks = ref<Task[]>([])
const draggedReportTabId = ref<number | null>(null)
const calendarKey = ref(0)
const meetings = ref<MeetingPage>({ items: [], total: 0, page: 1, page_size: 10 })
const visibleMeetings = computed(() => targetMeeting.value
  ? meetings.value.items.filter(item => item.id === targetMeeting.value) : meetings.value.items)
const meetingPage = ref(1), meetingOpen = ref(false), meetingDraft = ref<Meeting | null>(null)
const todayWeeklyMeeting = ref<Meeting | null>(null), todayWeeklyMeetingLoading = ref(false)
const meetingActionLabel = computed(() => todayWeeklyMeeting.value ? '修改会议记录' : '新增会议记录')
const meetingFilter = reactive({ date_from: '', date_to: '', content: '', status: '' })
const notice = ref(''), saveStatus = ref<'saved' | 'saving' | 'failed' | 'conflict'>('saved')
const mutating = ref(false)
const newCategory = ref(''), categoryDrafts = reactive<Record<number, string>>({})
const newUser = reactive({ username: '', display_name: '', password: '', roles: ['user'] as UserRole[], status: '正常' as User['status'] })
const userDrafts = reactive<Record<number, { username: string; display_name: string; roles: UserRole[]; status: User['status']; password: string }>>({})
const passwordForm = reactive({ old_password: '', new_password: '', confirm_password: '' })
const modal = ref<null | { taskId: number }>(null)
const modalFirst = ref<HTMLButtonElement | null>(null)
const reportExportOpen = ref(false), reportExporting = ref(false), reportExportError = ref('')
const reportExportStart = ref(''), reportExportEnd = ref('')
const reportExportStartInput = ref<HTMLInputElement | null>(null)
const page = computed(() => String(route.name || 'work'))
// 页内导航共用页头的折叠状态，刷新后默认展开。
const pageTopCollapsed = ref(false)
const sidebarTourAccount = computed(() =>
  ready.value && desktopSidebar.value && !user.value?.must_change_password && (page.value === 'work' || page.value === 'reports')
    ? user.value?.id : undefined,
)
function hasSeenGuide(key: string) {
  if (seenGuides.has(key)) return true
  try { return localStorage.getItem(key) === '1' } catch { return false }
}
function markGuideSeen(key: string) {
  seenGuides.add(key)
  try { localStorage.setItem(key, '1') } catch { /* 浏览器存储不可用时，仅记录当前页面的展示状态。 */ }
}
watch([sidebarTourAccount, page], async ([account, activePage], _previous, onCleanup) => {
  if (account === undefined) return
  // 使用固定的功能版本标识，后续发布新版本也不会重播这次引导。
  const key = `zhoubao.sidebar-tour.v1.4.0.${account}`
  if (hasSeenGuide(key)) return
  let cancelled = false
  let stop = () => { sidebarTourActive.value = false }
  onCleanup(() => { cancelled = true; stop() })

  // 加载侧栏引导期间先阻止任务引导，避免两个弹窗同时启动。
  sidebarTourActive.value = true
  const module = await import('./sidebarTour').catch(() => undefined)
  if (cancelled) return
  if (!module || hasSeenGuide(key)) { stop(); return }
  const wasCollapsed = sidebarCollapsed.value
  const close = (completed = false) => {
    sidebarCollapsed.value = completed ? false : wasCollapsed
    sidebarTourActive.value = false
  }
  stop = close
  sidebarCollapsed.value = false
  await nextTick()
  if (cancelled) return

  stop = module.startSidebarTour({
    menu: visibleNavItems.value.filter(item => item.name !== 'review-config' && item.name !== 'review-records' && item.name !== 'scheduled-tasks' && item.name !== 'task-board'),
    showMeetingShortcut: activePage === 'reports',
    setCollapsed: collapsed => { sidebarCollapsed.value = collapsed },
    onShown: () => markGuideSeen(key),
    onClosed: close,
  })
}, { flush: 'post' })
const title = computed(() => ({ work: '本周工作', 'task-board': '任务看板', reports: '周报汇总', categories: '任务类型', meetings: '会议记录', users: '用户管理', password: '修改密码', 'review-config': '审查配置', 'review-records': '审查记录', messages: '消息中心', 'scheduled-tasks': '定时任务' }[page.value] || '周报'))
const taskFontSizeKey = 'zhoubao.task-font-size'
function loadTaskFontSize() {
  try {
    const size = Number(localStorage.getItem(taskFontSizeKey))
    return Number.isInteger(size) && size >= 12 && size <= 24 ? size : 16
  } catch { return 16 }
}
const taskFontSize = ref(loadTaskFontSize())
function adjustTaskFontSize(delta: number) {
  taskFontSize.value = Math.min(20, Math.max(12, taskFontSize.value + delta))
  try { localStorage.setItem(taskFontSizeKey, String(taskFontSize.value)) } catch { /* 浏览器存储不可用时仍应用本次调整。 */ }
}
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

async function refreshForRelease() {
  releaseRefreshing.value = true
  try {
    if (structuralPromise) await structuralPromise
    if (hasPending()) await flushPending()
    if (reviewRecords.value && !await reviewRecords.value.flushReview()) return
    window.location.reload()
  } catch (error) { showError(error) }
  finally { releaseRefreshing.value = false }
}

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
        const response = await enqueue(() => api<WeekData>(workPath(`/tasks/${id}`, true), 'PATCH', patch))
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
    const latest = await api<WeekData>(workPath())
    for (const [id, patch] of drafts) {
      const row = (futureWork.value ? latest.plans : latest.tasks)?.find(item => item.id === id)
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
  if (workReadonly.value || workLoading.value) return
  const task = workTasks.value.find(item => item.id === id)
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
      notice.value = response.no_source ? (futureWork.value ? '没有可复制的进行中任务。' : '没有可添加的进行中任务。') : ''
    } catch (error) { showError(error) } finally { mutating.value = false }
  })()
  try { await structuralPromise } finally { structuralPromise = null }
}
function addTask() { void structural(() => api(workPath('/tasks', true), 'POST', undefined, newIdempotencyKey())) }
function setPlanCardDrag(id: number | null) {
  draggedPlanCard.value = id
  planDropActive.value = false
}
function closePlanBoard(restoreFocus = true) {
  if (!planBoardOpen.value) return
  planBoardOpen.value = false
  setPlanCardDrag(null)
  if (restoreFocus) planBoardTrigger.value?.focus()
}
function addPlanCard(id: number) {
  if (!planBoardOpen.value || !futureWork.value || !canManageOwnWork.value || mutating.value || plannedCardIds.value.has(id)) return
  void structural(() => api(workPath(`/plans/from-board/${id}`, true), 'POST', undefined, newIdempotencyKey()))
}
function allowPlanDrop(event: DragEvent) {
  if (draggedPlanCard.value === null || mutating.value || !event.dataTransfer) return
  event.preventDefault()
  event.dataTransfer.dropEffect = 'copy'
  planDropActive.value = true
}
function leavePlanDrop(event: DragEvent) {
  if (!(event.relatedTarget instanceof Node) || !(event.currentTarget as HTMLElement).contains(event.relatedTarget)) {
    planDropActive.value = false
  }
}
function dropPlanCard(event: DragEvent) {
  const id = draggedPlanCard.value
  if (id === null) return
  event.preventDefault()
  setPlanCardDrag(null)
  addPlanCard(id)
}
function duplicateTask(id: number) { void structural(() => api(`/weeks/${selectedWeek.value}/tasks/${id}/duplicate?revision=${week.value.revision}`, 'POST', undefined, newIdempotencyKey())) }
function reorderTasks(ids: number[]) { void structural(() => api(workPath('/tasks/order', true), 'PUT', { task_ids: ids })) }
function transferTask(id: number, userId: number) {
  void structural(() => api(`/weeks/${selectedWeek.value}/tasks/${id}/transfer?revision=${week.value.revision}`, 'POST', { user_id: userId }))
}
const taskGuideAccount = computed(() =>
  ready.value && page.value === 'work' && !user.value?.must_change_password &&
    canManageOwnWork.value && !futureWork.value && week.value.tasks.length && !mutating.value && !modal.value && !sidebarTourActive.value
    ? user.value?.id : undefined,
)
watch([taskGuideAccount, selectedWeek], async ([account, requestedWeek], _previous, onCleanup) => {
  if (account === undefined) return
  // 等待可高亮的任务卡片，且同一账号在当前浏览器只展示一次。
  const key = `zhoubao.task-actions-tour.${account}`
  if (hasSeenGuide(key)) return
  let cancelled = false
  let stop: (() => void) | undefined
  onCleanup(() => { cancelled = true; stop?.() })

  const module = await import('./sidebarTour').catch(() => undefined)
  if (!module || cancelled || taskGuideAccount.value !== account || selectedWeek.value !== requestedWeek || hasSeenGuide(key)) return
  stop = module.startTaskActionsTour(() => markGuideSeen(key))
}, { flush: 'post' })
function askDelete(id: number) { openModal({ taskId: id }) }
function openModal(value: NonNullable<typeof modal.value>) { modal.value = value; void nextTick(() => modalFirst.value?.focus()) }
async function confirmDelete(id: number) {
  modal.value = null
  await structural(() => api(workPath(`/tasks/${id}`, true), 'DELETE'))
}
function addInProgress() {
  const suffix = futureWork.value ? '/plans/add-in-progress' : '/add-in-progress'
  void structural(() => api(workPath(suffix, true), 'POST', undefined, newIdempotencyKey()))
}

async function loadPage() {
  if (!user.value || page.value === 'login') return
  const serial = ++loadSerial
  try {
    if (page.value === 'work') {
      workLoading.value = true
      const context = await api<{ current_week: string; members: ReportTab[] }>('/work-context')
      if (serial !== loadSerial) return
      const requestedWeek = validDay(route.query.week)
      if (requestedWeek && mondayOf(requestedWeek) === requestedWeek) selectedWeek.value = requestedWeek
      else if (!currentWorkWeek.value) selectedWeek.value = context.current_week
      currentWorkWeek.value = context.current_week
      workMembers.value = context.members
      if (!workMembers.value.some(member => member.id === workMember.value)) workMember.value = null
      const categoryPath = workMemberQuery.value ? `/categories?${workMemberQuery.value}` : '/categories'
      const [weekData, categoryData] = await Promise.all([api<WeekData>(workPath()), api<Category[]>(categoryPath)])
      if (serial !== loadSerial) return
      week.value = weekData; categories.value = categoryData
      if (targetTask.value && weekData.tasks.some(task => task.id === targetTask.value)) {
        await nextTick()
        document.getElementById(`work-task-${targetTask.value}`)?.scrollIntoView({ block: 'center' })
      }
    } else if (page.value === 'reports') {
      reportTasks.value = []
      todayWeeklyMeetingLoading.value = true
      const [newTabs, weeklyMeeting] = await Promise.all([
        api<ReportTab[]>(`/reports/${selectedWeek.value}`),
        findTodayWeeklyMeeting(),
      ])
      if (serial !== loadSerial) return
      todayWeeklyMeeting.value = weeklyMeeting
      tabs.value = restoreReportTabOrder(newTabs, storedReportTabOrder())
      if (!tabs.value.some(tab => tab.id === activeTab.value)) activeTab.value = tabs.value[0]?.id || null
      if (activeTab.value) {
        const requestedTab = activeTab.value
        const response = await api<WeekData>(`/reports/${selectedWeek.value}/users/${requestedTab}`)
        if (serial === loadSerial && activeTab.value === requestedTab) reportTasks.value = response.tasks
      }
    } else if (page.value === 'categories') {
      categories.value = await api<Category[]>('/categories')
      categories.value.forEach(item => { categoryDrafts[item.id] = item.name })
    } else if (page.value === 'users' && isAdmin.value) {
      users.value = await api<User[]>('/users')
      users.value.forEach(item => { userDrafts[item.id] = { username: item.username, display_name: item.display_name, roles: [...userRoles(item)], status: item.status, password: '' } })
    } else if (page.value === 'meetings') {
      await loadMeetings()
    }
    notice.value = ''
  } catch (error) {
    if (serial === loadSerial) {
      if (page.value === 'work') week.value = { revision: 0, tasks: [] }
      showError(error)
    }
  } finally {
    if (serial === loadSerial) {
      todayWeeklyMeetingLoading.value = false
      workLoading.value = false
    }
  }
}
async function loadMeetings() {
  const meetingId = targetMeeting.value
  if (meetingId) {
    // 按会议 ID 读取定位记录，避免当前筛选条件和分页隐藏来源会议。
    const item = await api<Meeting>(`/meetings/${meetingId}`)
    if (page.value === 'meetings' && targetMeeting.value === meetingId) {
      meetings.value = { items: [item], total: 1, page: 1, page_size: 10 }
    }
    return
  }
  const params = new URLSearchParams({ page: String(meetingPage.value), page_size: '10' })
  if (meetingFilter.date_from) params.set('date_from', meetingFilter.date_from)
  if (meetingFilter.date_to) params.set('date_to', meetingFilter.date_to)
  if (meetingFilter.content.trim()) params.set('content', meetingFilter.content.trim())
  if (meetingFilter.status) params.set('status', meetingFilter.status)
  const result = await api<MeetingPage>(`/meetings?${params}`)
  if (page.value === 'meetings' && !targetMeeting.value) meetings.value = result
}
async function findTodayWeeklyMeeting() {
  const today = todayShanghai(), pageSize = 50
  for (let page = 1; ; page++) {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize), date_from: today, date_to: today })
    const result = await api<MeetingPage>(`/meetings?${params}`)
    const meeting = result.items.find(item => item.meeting_type === '周会')
    if (meeting || page * pageSize >= result.total) return meeting || null
  }
}
async function searchMeetings() {
  meetingPage.value = 1
  try {
    if (targetMeeting.value) await router.replace({ name: 'meetings' })
    else await loadMeetings()
  } catch (error) { showError(error) }
}
async function turnMeetingPage(offset: number) { meetingPage.value += offset; try { await loadMeetings() } catch (error) { meetingPage.value -= offset; showError(error) } }
async function openMeeting(meeting: Meeting | null = null) {
  // 打开编辑器时读取最新修订号，避免列表缓存覆盖人员刚更新的进度。
  try { meetingDraft.value = meeting ? await api<Meeting>(`/meetings/${meeting.id}`) : null; meetingOpen.value = true }
  catch (error) { showError(error) }
}
async function meetingSaved() {
  if (page.value === 'meetings') { meetingPage.value = 1; try { await loadMeetings() } catch (error) { showError(error) } }
  else if (page.value === 'reports') {
    todayWeeklyMeetingLoading.value = true
    try { todayWeeklyMeeting.value = await findTodayWeeklyMeeting(); if (activeTab.value) await chooseTab(activeTab.value) } catch (error) { showError(error) }
    finally { todayWeeklyMeetingLoading.value = false }
  }
}
async function removeMeeting(meeting: Meeting) {
  if (!window.confirm(`删除 ${meeting.meeting_date} 的会议记录？对应的看板卡片和本周任务也将删除。`)) return
  try {
    await api(`/meetings/${meeting.id}`, 'DELETE')
    if (targetMeeting.value === meeting.id) await searchMeetings()
    else await loadMeetings()
  } catch (error) { showError(error) }
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
  try {
    if (structuralPromise) await structuralPromise
    await flushPending()
    if (refresh && page.value === 'work') currentWorkWeek.value = (await api<{ current_week: string }>('/work-context')).current_week
    selectedWeek.value = refresh && page.value === 'work' ? currentWorkWeek.value : value
    if (refresh) calendarKey.value++
    if (page.value === 'work' && route.query.week) await router.replace({ name: 'work' })
    else await loadPage()
  } catch (error) { showError(error) }
}

async function chooseWorkMember(id: number) {
  if (workLoading.value || modal.value || (workMember.value ?? user.value?.id) === id) return
  try {
    if (structuralPromise) await structuralPromise
    await flushPending()
    if (page.value !== 'work') return
    workMember.value = id === user.value?.id ? null : id
    notice.value = ''
    if (route.query.task) await router.replace({ name: 'work', query: { week: selectedWeek.value } })
    else await loadPage()
  } catch { notice.value = '当前修改尚未保存，请先重试。' }
}
async function navigate(name: string) {
  if (name === 'review-records') reviewToday.value = todayShanghai()
  if (page.value === name && !(name === 'meetings' && targetMeeting.value)) { mobileOpen.value = false; return }
  try { if (structuralPromise) await structuralPromise; await flushPending(); if (name === 'reports') activeTab.value = null; await router.push(`/${name}`); mobileOpen.value = false } catch { notice.value = '当前修改尚未保存，请先重试。' }
}
async function login(event: Event) {
  try {
    const form = new FormData(event.currentTarget as HTMLFormElement)
    const result = await credentialApi<{ user: User; csrf_token: string }>('/auth/login', { username: form.get('username'), password: form.get('password') })
    user.value = result.user; setCsrf(result.csrf_token); notice.value = ''
    await router.replace(result.user.must_change_password ? '/password' : '/work')
    await loadPage()
  } catch (error) { showError(error) }
}
async function logout() {
  try { if (structuralPromise) await structuralPromise; await flushPending(); if (reviewRecords.value && !await reviewRecords.value.flushReview()) return; await api('/auth/logout', 'POST'); signingOut = true; await router.replace('/login'); user.value = null; setCsrf('') } catch (error) { showError(error) } finally { signingOut = false }
}
async function showLoginAfterRevocation() {
  signingOut = true
  try { await router.replace('/login'); user.value = null; setCsrf('') } finally { signingOut = false }
}
async function changePassword() {
  if (passwordForm.new_password !== passwordForm.confirm_password) { notice.value = '两次输入的新密码不一致。'; return }
  try { await credentialApi('/auth/password', { old_password: passwordForm.old_password, new_password: passwordForm.new_password }); await showLoginAfterRevocation(); passwordForm.old_password = ''; passwordForm.new_password = ''; passwordForm.confirm_password = ''; notice.value = '密码已更新，请重新登录。' } catch (error) { showError(error) }
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
  if (!newUser.roles.length) { notice.value = '请至少选择一个角色。'; return }
  try {
    await credentialApi('/users', newUser)
    Object.assign(newUser, { username: '', display_name: '', password: '', roles: ['user'], status: '正常' })
    await loadPage()
  } catch (error) { showError(error) }
}
async function saveUser(id: number) {
  const { username, display_name, roles, status } = userDrafts[id]
  const current = users.value.find(item => item.id === id)
  if (!current) return
  if (!roles.length) { notice.value = '请至少选择一个角色。'; return }
  try {
    const updated = await api<User>(`/users/${id}`, 'PATCH', {
      username, display_name, status, ...(sameRoles(userRoles(current), roles) ? {} : { roles }),
    })
    if (user.value?.id === id) {
      if (!sameRoles(userRoles(user.value), userRoles(updated)) || updated.status === '锁定') {
        await showLoginAfterRevocation()
        return
      }
      user.value = updated
    }
    await loadPage()
  } catch (error) { showError(error) }
}
async function deleteUser(item: User) {
  if (!window.confirm(`删除 ${item.display_name}？该用户将从列表移除，历史周报会保留。`)) return
  try { await api(`/users/${item.id}`, 'DELETE'); await loadPage() } catch (error) { showError(error) }
}
async function resetPassword(id: number) {
  try { await credentialApi(`/users/${id}/password`, { password: userDrafts[id].password }); userDrafts[id].password = ''; if (user.value?.id === id) await showLoginAfterRevocation(); notice.value = '密码已重置，用户需重新登录。' } catch (error) { showError(error) }
}

const removeRouteGuard = router.beforeEach(async (to, from) => {
  if (!ready.value || !user.value || to.fullPath === from.fullPath) return
  if (to.name === 'login' && !signingOut) return user.value.must_change_password ? '/password' : '/work'
  if (user.value.must_change_password && to.name !== 'password' && !signingOut) return '/password'
  if (adminPages.includes(String(to.name)) && !isAdmin.value) return '/work'
  if (hasPending()) {
    try { if (structuralPromise) await structuralPromise; await flushPending() } catch { notice.value = '当前修改尚未保存，请先重试。'; return false }
  }
})
onMounted(async () => {
  mobileSidebarQuery.addEventListener('change', updateSidebarViewport)
  window.addEventListener('beforeunload', beforeUnload)
  document.addEventListener('invalid', localizeInvalid, true)
  document.addEventListener('input', clearValidation, true)
  document.addEventListener('change', clearValidation, true)
  try { const result = await api<{ user: User; csrf_token: string }>('/auth/me'); user.value = result.user; setCsrf(result.csrf_token) }
  catch { await router.replace('/login') }
  ready.value = true
  if (user.value?.must_change_password) await router.replace('/password')
  else if (user.value && (page.value === 'login' || (adminPages.includes(page.value) && !isAdmin.value))) await router.replace('/work')
  if (user.value) await loadPage()
})
onUnmounted(() => { mobileSidebarQuery.removeEventListener('change', updateSidebarViewport); removeRouteGuard(); window.removeEventListener('beforeunload', beforeUnload); document.removeEventListener('invalid', localizeInvalid, true); document.removeEventListener('input', clearValidation, true); document.removeEventListener('change', clearValidation, true); if (timer) clearTimeout(timer); if (maxWaitTimer) clearTimeout(maxWaitTimer) })
watch(() => [route.name, route.query.week, route.query.task, route.query.meeting], () => { if (ready.value && user.value) void loadPage() })
watch([page, selectedWeek, workMember, canManageOwnWork, futureWork, () => user.value?.id], () => closePlanBoard(false))
watch(unreadMessages, count => { if (!count) showUnreadReminder.value = false })
watch(() => user.value && !user.value.must_change_password ? user.value.id : null, (account, _, onCleanup) => {
  showUnreadReminder.value = false
  showPermissionReminder.value = false
  liveMessages.value = []
  releaseVersion.value = ''
  unreadMessages.value = 0
  void refreshUnread()
  if (!account) return
  checkNotificationPermission()
  showPermissionReminder.value = notificationPermission.value !== 'granted'
  window.addEventListener('focus', checkNotificationPermission)
  let reminderTimer: number | undefined
  let intervalMinutes = 0
  let scheduleVersion = 0
  let checking = false
  const { stop, remindUnread } = subscribeToMessages(account, (count, schedule) => {
    if (user.value?.id !== account) return
    checkNotificationPermission()
    unreadVersion++
    unreadMessages.value = count
    messagesRefresh.value++
    const nextInterval = schedule?.enabled ? schedule.interval_minutes : 0
    if (nextInterval === intervalMinutes) return
    intervalMinutes = nextInterval
    scheduleVersion++
    window.clearInterval(reminderTimer)
    if (intervalMinutes > 0) {
      reminderTimer = window.setInterval(scanUnread, intervalMinutes * 60 * 1000)
    } else {
      showUnreadReminder.value = false
    }
  }, message => {
    // 合并多个即时提醒时保留最新三条，其余可在消息中心查看。
    liveMessages.value = [...liveMessages.value.slice(-2), message]
  }, message => openLiveMessage(message), version => { releaseVersion.value = version })
  // 配置或账号变更时，丢弃旧扫描尚未返回的结果。
  async function scanUnread() {
    if (checking) return
    checking = true
    const version = ++unreadVersion
    const schedule = scheduleVersion
    try {
      const { total, items } = await api<{ total: number; items: LiveMessage[] }>('/notifications?is_read=false')
      if (schedule !== scheduleVersion || version !== unreadVersion) return
      unreadMessages.value = total
      checkNotificationPermission()
      if (notificationPermission.value === 'granted') {
        if (total > 0 && items[0]) remindUnread(items[0], total)
      } else {
        showUnreadReminder.value = total > 0
        if (total > 0) showPermissionReminder.value = true
      }
    } catch { /* 轮询失败时保留最近一次成功的未读状态。 */ }
    finally { checking = false }
  }
  onCleanup(() => {
    scheduleVersion++
    window.clearInterval(reminderTimer)
    window.removeEventListener('focus', checkNotificationPermission)
    stop()
  })
})
</script>

<template>
  <div v-if="!ready" class="loading">正在加载周报…</div>
  <main v-else-if="!user" class="login-screen"><div class="login-poster"><span class="eyebrow">每周工作 / 团队周报</span><h1>把一周<br>写成进展。</h1><p>清晰记录每一天，也看见整个团队。</p></div><form class="login-panel" @submit.prevent="login"><span class="eyebrow">01 / 用户登录</span><h2>登录周报</h2><label>用户名<input name="username" autocomplete="username" required /></label><label>密码<input name="password" type="password" autocomplete="current-password" required /></label><button class="primary-button" type="submit">进入工作台 →</button><p v-if="notice" class="message error" role="alert">{{ notice }}</p></form></main>
  <div v-else class="shell" :class="{ 'sidebar-collapsed': compactSidebar, 'sidebar-guided': sidebarTourActive }">
    <button class="mobile-toggle" type="button" :aria-expanded="mobileOpen" aria-label="打开或关闭导航" @click="mobileOpen = !mobileOpen">☰ 菜单</button>
    <aside class="sidebar" :class="{ open: mobileOpen }">
      <div class="brand">
        <img class="brand-mark" :src="brandLogo" alt="周报" />
        <div><strong v-if="!compactSidebar">周报</strong><ReleaseNotes :version="version" :compact="compactSidebar" /></div>
        <button v-if="desktopSidebar" class="icon-btn sidebar-toggle" data-sidebar-tour="toggle" type="button" aria-controls="sidebar-body" :aria-expanded="!compactSidebar" :aria-label="compactSidebar ? '展开侧栏' : '收起侧栏'" :title="compactSidebar ? '展开侧栏' : '收起侧栏'" @click="sidebarCollapsed = !sidebarCollapsed">{{ compactSidebar ? '→' : '←' }}</button>
      </div>
      <div id="sidebar-body" class="sidebar-body">
        <nav v-if="!user.must_change_password" aria-label="主导航">
          <button v-for="item in visibleNavItems" :key="item.name" :data-sidebar-tour="item.name" class="sidebar-link" type="button" :class="{ active: page === item.name }" :aria-current="page === item.name ? 'page' : undefined" :aria-label="item.label" :title="compactSidebar ? item.label : undefined" @click="navigate(item.name)">
            <svg class="sidebar-icon" viewBox="0 0 24 24" aria-hidden="true"><path :d="item.icon" /></svg>
            <span v-if="!compactSidebar">{{ item.label }}</span>
          </button>
        </nav>
      </div>
      <MonthCalendar v-if="page === 'work' || page === 'reports'" :selected="selectedWeek" :scope="page" :current-week="currentWorkWeek" :member-id="page === 'work' && delegatedWork ? workMember : null" :refresh-key="calendarKey" :compact="compactSidebar" @select="selectWeek" />
      <MonthCalendar v-else-if="page === 'review-records'" :selected="reviewDay" scope="review-records" :refresh-key="calendarKey + reviewRefresh" :compact="compactSidebar" @select="selectReviewDay" />
      <div class="sidebar-bottom">
        <div class="sidebar-user">
          <div class="identity"><strong :title="user.display_name">{{ user.display_name }}</strong><small v-if="!compactSidebar">{{ user.username }}</small></div>
          <div class="sidebar-actions">
            <button class="mini-button" data-sidebar-tour="password" type="button" aria-label="修改密码" :title="compactSidebar ? '修改密码' : undefined" @click="navigate('password')">
              <svg v-if="compactSidebar" class="sidebar-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M21 7a5 5 0 0 1-6.7 4.7L8 18H4v-4l6.3-6.3A5 5 0 1 1 21 7z M16 7h.01" /></svg>
              <span v-else>修改密码</span>
            </button>
            <button class="mini-button" data-sidebar-tour="logout" type="button" aria-label="退出登录" :title="compactSidebar ? '退出登录' : undefined" @click="logout">
              <svg v-if="compactSidebar" class="sidebar-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M11 4H4v16h7 M9 12h12 M17 8l4 4-4 4" /></svg>
              <span v-else>退出登录</span>
            </button>
          </div>
        </div>
      </div>
    </aside>
    <main class="content" :style="{ '--task-font-size': `${taskFontSize}px` }"><div class="page-top" :class="{ 'report-top': page === 'reports' || (page === 'work' && isAdmin), 'page-top-collapsed': pageTopCollapsed }">
      <div class="page-top-leading">
        <button class="icon-btn page-top-toggle" type="button" :aria-label="pageTopCollapsed ? '展开页头' : '收起页头'" :title="pageTopCollapsed ? '展开页头' : '收起页头'" :aria-expanded="!pageTopCollapsed" aria-controls="page-top-details" @click="pageTopCollapsed = !pageTopCollapsed">
          <span aria-hidden="true">{{ pageTopCollapsed ? '↓' : '↑' }}</span>
        </button>
        <div class="page-top-text">
          <span class="eyebrow">周报系统 / {{ title }}</span>
          <div v-show="!pageTopCollapsed" id="page-top-details" :class="{ 'message-heading': page === 'messages' }">
            <h1>{{ title }}</h1>
            <template v-if="page === 'messages'">
              <button v-if="notificationPermission === 'default'" class="mini-button" type="button" :disabled="requestingPermission" @click="enableNotifications">开启桌面通知</button>
              <small v-else-if="notificationPermission === 'denied'">请在浏览器站点设置中允许通知。</small>
              <small v-else-if="notificationPermission === 'granted'">已开启桌面通知</small>
              <small v-else>当前浏览器环境仅支持站内消息。</small>
            </template>
          </div>
          <p v-if="page === 'work' || page === 'reports'" class="date-range">{{ selectedWeek }} 至 {{ new Date(new Date(`${selectedWeek}T12:00:00Z`).getTime() + 6 * 86400000).toISOString().slice(0,10) }}</p>
          <p v-else-if="page === 'review-records'" class="date-range">{{ reviewDay }}</p>
        </div>
      </div>
      <div class="top-actions">
        <button v-if="pageTopCollapsed && page === 'messages' && notificationPermission === 'default'" class="mini-button" type="button" :disabled="requestingPermission" @click="enableNotifications">开启桌面通知</button>
        <template v-if="page === 'work' || page === 'reports'">
          <div class="font-size-controls" role="group" aria-label="填写和选择项字号">
            <button class="mini-button" type="button" aria-label="缩小字号" title="缩小字号" :disabled="taskFontSize <= 12" @click="adjustTaskFontSize(-1)">A−</button>
            <output aria-live="polite">{{ taskFontSize }}px</output>
            <button class="mini-button" type="button" aria-label="增大字号" title="增大字号" :disabled="taskFontSize >= 20" @click="adjustTaskFontSize(1)">A+</button>
          </div>
          <template v-if="page === 'work'">
            <button v-if="canManageOwnWork && selectedWeek === currentWorkWeek" class="secondary-button" type="button" :disabled="mutating" @click="selectWeek(addDays(currentWorkWeek, 7))">填写下周计划</button>
            <button v-if="canManageOwnWork && !workReadonly && (futureWork || selectedWeek === currentWorkWeek)" class="secondary-button" type="button" :disabled="mutating" @click="addInProgress">↖ {{ futureWork ? '复制进行中的任务' : '添加进行中的任务' }}</button>
            <button v-if="canManageOwnWork && futureWork" ref="planBoardTrigger" class="primary-button" type="button"
              :disabled="mutating && !planBoardOpen" :aria-expanded="planBoardOpen" aria-controls="plan-task-board"
              @click="planBoardOpen ? closePlanBoard() : planBoardOpen = true">＋ 新增任务计划</button>
            <button v-else-if="canManageOwnWork && selectedWeek === currentWorkWeek" class="primary-button" type="button" :disabled="mutating" @click="addTask">＋ 新增任务</button>
          </template>
          <template v-else>
            <button class="primary-button" type="button" :disabled="reportExporting" @click="openReportExport">⇩ 导出Excel</button>
            <button class="primary-button" data-sidebar-tour="meeting-shortcut" type="button" :disabled="todayWeeklyMeetingLoading" @click="openMeeting(todayWeeklyMeeting)">
              <span aria-hidden="true">{{ todayWeeklyMeeting ? '✎' : '＋' }}</span> {{ meetingActionLabel }}
            </button>
          </template>
        </template>
        <button v-if="!user.must_change_password" class="secondary-button" type="button" @click="navigate('messages')">消息中心<span v-if="unreadMessages" class="unread-count" :aria-label="`未读 ${unreadMessages} 条`">{{ unreadMessages > 99 ? '99+' : unreadMessages }}</span></button>
        <button v-if="page === 'review-records'" class="primary-button" type="button" @click="summaryRequest++">审查总结</button>
      </div>
      <div v-if="page === 'work' && isAdmin && workMembers.length" class="tabs work-member-tabs" role="tablist" aria-label="任务明细成员">
        <button v-for="member in workMembers" :key="member.id" type="button" role="tab" :disabled="workLoading" :aria-selected="(workMember ?? user.id) === member.id" :class="{ selected: (workMember ?? user.id) === member.id }" @click="chooseWorkMember(member.id)">{{ member.name }}<small v-if="member.id === user.id">（本人）</small><small v-else-if="!member.is_active">（已停用）</small></button>
      </div>
      <div v-if="page === 'reports' && tabs.length" class="tabs" role="tablist" aria-label="成员"><button v-for="tab in tabs" :key="tab.id" type="button" role="tab" draggable="true" title="拖动调整成员顺序" :aria-selected="activeTab === tab.id" :class="{ selected: activeTab === tab.id, dragging: draggedReportTabId === tab.id }" @click="chooseTab(tab.id)" @dragstart="startReportTabDrag($event, tab.id)" @dragover="allowReportTabDrop" @drop="dropReportTab($event, tab.id)" @dragend="draggedReportTabId = null">{{ tab.name }}<small v-if="tab.is_deleted">（已删除）</small><small v-else-if="!tab.is_active">（已停用）</small></button></div></div>
      <div class="work-area" :class="{ 'review-work-area': page === 'review-records', 'board-work-area': page === 'task-board', 'plan-work-area': planBoardOpen }"><p v-if="notice" class="message" :class="{ error: saveStatus === 'failed' || saveStatus === 'conflict' }" role="alert">{{ notice }}</p>
      <p v-if="messageJumpNotice" class="message error" role="alert">{{ messageJumpNotice }}</p>
      <ReviewConfig v-if="page === 'review-config' && isAdmin" :key="user.id" :account-id="user.id" />
      <ScheduledTasks v-else-if="page === 'scheduled-tasks' && isAdmin" :key="user.id" />
      <ReviewRecords v-else-if="page === 'review-records'" ref="reviewRecords" :day="reviewDay" :summary-request="summaryRequest" :refresh-key="reviewRefresh" />
      <MessageCenter v-else-if="page === 'messages'" :admin="isAdmin" :jump-to-message="jumpToMessage" :refresh-key="messagesRefresh" @change="refreshUnread" />
      <TaskBoard v-else-if="page === 'task-board'" :key="user.id" :target-task="targetTask" :target-refresh="boardTargetRefresh" />
      <div v-else-if="page === 'work'" :role="futureWork ? 'region' : undefined" :aria-label="futureWork ? '任务计划表' : undefined"
        :class="{ 'plan-list-drop-area': planBoardOpen, 'plan-list-drop-active': planDropActive }"
        @dragover="allowPlanDrop" @dragleave="leavePlanDrop" @drop="dropPlanCard">
        <div class="section-head">
          <strong>{{ futureWork ? '任务计划表' : '任务明细' }} <span v-if="!workLoading">{{ workTasks.length }}</span></strong>
          <div v-if="!workReadonly && !workLoading" class="save-indicator" role="status">{{ { saved:'✓ 已保存', saving:'… 保存中', failed:'! 保存失败', conflict:'! 内容冲突' }[mutating ? 'saving' : saveStatus] }}<button v-if="saveStatus === 'failed'" type="button" @click="flushPending">重试</button><button v-if="saveStatus === 'conflict'" type="button" @click="resolveConflict">用当前修改重试</button></div>
        </div>
        <p v-if="workLoading" role="status">正在加载{{ futureWork ? '任务计划' : '任务明细' }}…</p>
        <p v-else-if="workReadonly" class="message">{{ futureWork ? '可提前填写本人下一周的任务计划。' : '仅当前周可编辑任务明细。' }}</p>
        <p v-if="planBoardOpen" class="plan-drop-hint">将看板卡片拖到任务计划表</p>
        <TaskTable v-if="!workLoading" :key="selectedWeek + ':' + (workMember ?? user.id) + ':' + futureWork" :tasks="workTasks" :categories="categories" work-view :plan="futureWork" :readonly="workReadonly" :delegated="delegatedWork" :busy="mutating" :target-task="futureWork ? null : targetTask" :is-current-week="selectedWeek === currentWorkWeek" @edit="editTask" @duplicate="duplicateTask" @remove="askDelete" @reorder="reorderTasks" @transfer="transferTask" />
        <Teleport v-if="planBoardOpen" to="body">
          <PlanTaskBoard :planned-ids="plannedCardIds" :busy="mutating" :dragging="draggedPlanCard !== null"
            @drag="setPlanCardDrag" @add="addPlanCard" @close="closePlanBoard()" />
        </Teleport>
        <details v-if="!workLoading && !futureWork && week.plans?.length" class="work-plan-history">
          <summary>任务计划表（历史） · {{ week.plans.length }} 项</summary>
          <TaskTable :tasks="week.plans" plan readonly />
        </details>
      </div>
      <div v-else-if="page === 'reports'"><div v-if="!tabs.length" class="empty">暂无成员记录。</div><TaskTable v-if="activeTab" :tasks="reportTasks" readonly /></div>
      <section v-else-if="page === 'categories'" class="panel"><p>为自己的任务维护类型；修改或删除后，历史任务名称保持原样。系统内置类型所有人可直接选择。</p><form class="inline-form" @submit.prevent="addCategory"><label>新任务类型<input v-model="newCategory" maxlength="100" required placeholder="例如：产品开发" /></label><button class="primary-button" type="submit">新增类型</button></form><div v-for="category in categories" :key="category.id" class="list-row"><input v-model="categoryDrafts[category.id]" :aria-label="`任务类型 ${category.name}`" maxlength="100" /><button class="mini-button" type="button" @click="renameCategory(category.id)">保存名称</button><button class="mini-button danger" type="button" @click="deleteCategory(category.id)">删除</button></div><div v-if="!categories.length" class="empty">还没有个人任务类型，可在上方新增。</div></section>
      <section v-else-if="page === 'meetings'" class="meetings-page">
        <div v-if="targetMeeting" class="section-head"><button class="secondary-button" type="button" @click="searchMeetings">返回会议列表</button></div>
        <form v-else class="meeting-filters panel" @submit.prevent="searchMeetings"><label>开始日期<input v-model="meetingFilter.date_from" type="date" /></label><label>结束日期<input v-model="meetingFilter.date_to" type="date" /></label><label>会议内容<input v-model="meetingFilter.content" placeholder="模糊搜索" /></label><label>完成状态<select v-model="meetingFilter.status"><option value="">全部</option><option v-for="status in taskStatuses" :key="status" :value="status">{{ status }}</option><option value="未开始">未开始</option></select></label><button class="secondary-button" type="submit">查询</button><button class="primary-button" type="button" @click="openMeeting()">＋ 新增会议记录</button></form><div class="meeting-list"><article v-for="item in visibleMeetings" :key="item.id" class="meeting-card"><div class="meeting-card-head"><div><strong>{{ item.meeting_date }}</strong><span>{{ item.meeting_type }}</span><small class="meeting-person">创建人：{{ item.creator?.display_name || '未知' }}</small><small class="meeting-person">更新人：{{ item.updaters.map(person => person.display_name).join('、') || '暂无' }}</small></div><div class="top-actions"><button class="mini-button" type="button" @click="openMeeting(item)">编辑</button><button class="mini-button danger" type="button" @click="removeMeeting(item)">删除</button></div></div><p class="preline">{{ item.content }}</p><div v-if="item.needs_follow_up" class="meeting-tasks"><strong>跟踪任务</strong><div v-for="task in item.tasks" :key="task.id" class="meeting-task-line"><span class="preline">{{ task.position }}. {{ task.name }}</span>
            <span v-if="!task.assignments?.length" class="status-tag" :class="{ completed: task.status === '已完成', pending: !task.status }" :style="progressStyle(task.status)">{{ task.status || '未开始' }}</span>
            <span v-for="assignment in task.assignments" :key="assignment.user_id" class="meeting-person-progress"><span class="meeting-assignee-name">{{ assignment.person?.display_name }}</span><span>:</span><span class="status-tag" :class="{ completed: assignment.status === '已完成', pending: !assignment.status }" :style="progressStyle(assignment.status)">{{ assignment.status || '未开始' }}</span></span></div><p v-if="!item.tasks.length">暂无关联任务</p></div></article><div v-if="!visibleMeetings.length" class="empty">没有符合条件的会议记录。</div></div><div v-if="!targetMeeting" class="meeting-pagination"><span>共 {{ meetings.total }} 条 · 第 {{ meetings.page }} 页</span><button class="mini-button" type="button" :disabled="meetingPage <= 1" @click="turnMeetingPage(-1)">上一页</button><button class="mini-button" type="button" :disabled="meetingPage * meetings.page_size >= meetings.total" @click="turnMeetingPage(1)">下一页</button></div></section>
      <section v-else-if="page === 'users' && isAdmin" class="panel">
        <h2>新增用户</h2>
        <form class="user-create" @submit.prevent="createUser">
          <label>用户名<input v-model="newUser.username" required pattern="[A-Za-z0-9_.-]+" /></label>
          <label>显示姓名<input v-model="newUser.display_name" required /></label>
          <label>初始密码<input v-model="newUser.password" type="password" minlength="6" required /></label>
          <fieldset class="user-roles">
            <legend>角色</legend>
            <label><input v-model="newUser.roles" type="checkbox" value="user" />普通用户</label>
            <label><input v-model="newUser.roles" type="checkbox" value="admin" />管理员</label>
          </fieldset>
          <label>状态<select v-model="newUser.status"><option>正常</option><option>锁定</option></select></label>
          <button class="primary-button" type="submit">创建用户</button>
        </form>
        <h2>现有用户</h2>
        <div v-for="item in users" :key="item.id" class="user-row">
          <div class="user-header"><strong>{{ item.username }}</strong><span>{{ item.is_active ? item.status : '已停用' }}</span></div>
          <div class="user-controls">
            <label>用户名<input v-model="userDrafts[item.id].username" pattern="[A-Za-z0-9_.-]+" /></label>
            <label>姓名<input v-model="userDrafts[item.id].display_name" /></label>
            <fieldset class="user-roles">
              <legend>角色</legend>
              <label><input v-model="userDrafts[item.id].roles" type="checkbox" value="user" />普通用户</label>
              <label><input v-model="userDrafts[item.id].roles" type="checkbox" value="admin" />管理员</label>
            </fieldset>
            <label>状态<select v-model="userDrafts[item.id].status"><option>正常</option><option>锁定</option></select></label>
            <button class="mini-button" type="button" @click="saveUser(item.id)">保存资料</button>
            <button v-if="!userRoles(item).includes('admin')" class="mini-button danger" type="button" @click="deleteUser(item)">删除用户</button>
          </div>
          <form class="inline-form" @submit.prevent="resetPassword(item.id)">
            <label>重置密码<input v-model="userDrafts[item.id].password" type="password" minlength="6" required placeholder="至少 6 位" /></label>
            <button class="mini-button" type="submit">设置新密码</button>
          </form>
        </div>
      </section>
      <section v-else-if="page === 'password'" class="panel narrow"><h2>{{ user.must_change_password ? '首次登录，请修改初始密码' : '修改我的密码' }}</h2><p v-if="user.must_change_password">新密码不能与初始密码相同。修改成功后请重新登录。</p><form class="stack-form" @submit.prevent="changePassword"><label>当前密码<input v-model="passwordForm.old_password" type="password" autocomplete="current-password" required /></label><label>新密码（至少 6 位）<input v-model="passwordForm.new_password" type="password" autocomplete="new-password" minlength="6" required /></label><label>确认新密码<input v-model="passwordForm.confirm_password" type="password" autocomplete="new-password" minlength="6" required /></label><button class="primary-button" type="submit">更新密码</button></form></section>
      </div>
    </main>
    <div v-if="reportExportOpen" class="modal-scrim" @click.self="reportExportOpen = false" @keydown.esc="reportExportOpen = false"><form class="modal export-modal" role="dialog" aria-modal="true" aria-labelledby="report-export-title" @submit.prevent="exportReports"><span class="eyebrow">周报汇总</span><h2 id="report-export-title">导出 Excel</h2><p>选择起止周，每位成员将单独生成一个工作表。</p><div class="export-weeks"><label>起始周<input ref="reportExportStartInput" v-model="reportExportStart" type="week" required /></label><label>结束周<input v-model="reportExportEnd" type="week" required /></label></div><p v-if="reportExportError" class="message error" role="alert">{{ reportExportError }}</p><div class="modal-actions"><button class="secondary-button" type="button" :disabled="reportExporting" @click="reportExportOpen = false">取消</button><button class="primary-button" type="submit" :disabled="reportExporting">{{ reportExporting ? '生成中…' : '确定并导出' }}</button></div></form></div>
    <div v-if="modal" class="modal-scrim" @keydown.esc="modal = null"><div class="modal" role="dialog" aria-modal="true" :aria-label="futureWork ? '确认删除任务计划' : '确认删除任务'"><h2>删除这项{{ futureWork ? '任务计划' : '任务' }}？</h2><p>{{ futureWork ? '该计划将从任务计划表移除。' : '该任务将从本周工作明细移除。' }}</p><div class="modal-actions"><button ref="modalFirst" class="secondary-button" type="button" @click="modal = null">取消</button><button class="primary-button" type="button" @click="confirmDelete(modal.taskId)">确认删除</button></div></div></div>
    <MeetingEditor v-if="meetingOpen" :meeting="meetingDraft" @close="meetingOpen = false" @saved="meetingSaved" />
    <div class="unread-reminder-region" aria-live="polite">
      <div v-if="showPermissionReminder && notificationPermission !== 'granted'" class="notification-permission" role="group" aria-label="桌面通知权限">
        <strong>开启桌面通知</strong>
        <p v-if="notificationPermission === 'default'">授权后，未读消息将通过操作系统提醒。</p>
        <p v-else-if="notificationPermission === 'denied'">通知已被浏览器阻止。请在地址栏的站点设置中允许通知。</p>
        <p v-else>当前浏览器或访问地址无法使用桌面通知。新消息会在网页内提醒。</p>
        <div class="notification-permission-actions">
          <button v-if="notificationPermission === 'default'" class="mini-button" type="button" :disabled="requestingPermission" @click="enableNotifications">开启桌面通知</button>
          <button class="mini-button" type="button" @click="showPermissionReminder = false">稍后再说</button>
        </div>
      </div>
      <div v-for="message in liveMessages" :key="message.id" class="unread-reminder live-message-reminder">
        <button class="unread-reminder-link" type="button" @click="openLiveMessage(message)">
          <span>{{ message.kind }} · 新消息</span>
          <strong>{{ message.title || '点击查看新消息' }}</strong>
        </button>
        <button class="unread-reminder-close" type="button" aria-label="关闭新消息提醒" @click="dismissLiveMessage(message.id)">×</button>
      </div>
      <Transition name="unread-reminder">
        <div v-if="showUnreadReminder && unreadMessages > 0" class="unread-reminder">
          <button class="unread-reminder-link" type="button" @click="openUnreadReminder">
            <strong>你有 {{ unreadMessages }} 条未读消息</strong>
            <span>前往消息中心 →</span>
          </button>
          <button class="unread-reminder-close" type="button" aria-label="关闭未读消息提醒" @click="showUnreadReminder = false">×</button>
        </div>
      </Transition>
      <div v-if="releaseVersion" class="release-notice" role="group" aria-label="版本更新">
        <span class="release-notice-icon" aria-hidden="true">👂</span>
        <p class="release-notice-text">有新版 <strong>v{{ releaseVersion }}</strong> 已就绪</p>
        <div class="release-notice-actions">
          <button class="release-notice-refresh" type="button" :disabled="releaseRefreshing" @click="refreshForRelease">刷新页面</button>
          <button class="release-notice-later" type="button" @click="releaseVersion = ''">稍后</button>
        </div>
      </div>
    </div>
  </div>
</template>

