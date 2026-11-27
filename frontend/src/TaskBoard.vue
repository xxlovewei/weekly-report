<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { api, ApiError, newIdempotencyKey } from './api'
import stopwatch from './assets/task-stopwatch.png'
import { addDays } from './dates'
import ReviewIssueDialog from './ReviewIssueDialog.vue'
import DeploymentTaskIcon from './DeploymentTaskIcon.vue'
import { deploymentLocation } from './deploymentRoutes'
import { taskStatuses } from './taskStatuses'
import { sharedTaskTypes } from './taskTypes'
import type { Category, MeetingPerson, TaskPriority, WeekData } from './types'

const columns = [
  { state: 'inbox', name: '任务箱' },
  { state: 'in_progress', name: '进行中' },
  { state: 'done', name: '已完成' },
] as const
const progressSteps = taskStatuses.filter(status => status.endsWith('%')).map(status => Number.parseInt(status)).reverse()
type State = typeof columns[number]['state']
interface CardFields { name: string; category_name: string; priority: TaskPriority; notes: string }
interface Card extends CardFields {
  id: number
  estimated_days?: string | null
  state: State
  status: string | null
  completed_week: string | null
  revision: number
  position: number
  has_current_detail: boolean
  has_other_details: boolean
  meeting_id?: number | null
  review_issue_id?: number | null
  deployment_plan_id?: number | null
  deployment_archived?: boolean
  transferred_by?: string | null
  name_locked?: boolean
}
type Dialog = { kind: 'edit'; card?: Card } | { kind: 'remove' | 'return' | 'transfer'; card: Card }
interface Reminder { id: number; card_id: number; kind: '转交任务' | '会议指派' }
const dialogLabels = { edit: '保存', remove: '确认删除', return: '确认移回', transfer: '确认转交' }
const props = defineProps<{ targetTask?: number | null; targetRefresh?: number; plannedIds?: Set<number>; planBusy?: boolean }>()
const emit = defineEmits<{ 'add-plan': [id: number]; 'plan-drag': [id: number | null] }>()
const planMode = computed(() => props.plannedIds !== undefined)

const cards = ref<Card[]>([])
const categories = ref<Category[]>([])
const weekStart = ref('')
const showHistory = ref(false)
const loading = ref(true), busy = ref(false), error = ref('')
const notice = ref('')
const dragged = ref<number | null>(null), hovered = ref<State | null>(null)
const dropBefore = ref<number | null>(null)
const progressDraft = ref<{ cardId: number; percent: number } | null>(null)
let progressPointer: { id: number; startX: number; width: number; percent: number } | null = null
const previewId = ref<number | null>(null)
const previewPanel = ref<HTMLElement | null>(null)
const previewStyle = ref<Record<string, string>>({})
const previewCard = computed(() => cards.value.find(card => card.id === previewId.value))
let previewTimer: number | undefined
let previewAnchor: HTMLElement | null = null
const dialog = ref<HTMLDialogElement | null>(null), action = ref<Dialog | null>(null)
const form = reactive<CardFields>({ name: '', category_name: '', priority: '低', notes: '' })
const estimatedDays = ref('')
const estimatedDayParts = computed(() => {
  const match = /^(\d*)(\.\d+)?$/.exec(estimatedDays.value)
  return match ? { whole: BigInt(match[1] || '0'), fraction: match[2] || '' } : null
})
const canDecreaseEstimate = computed(() => {
  const days = estimatedDayParts.value
  return days !== null && (days.whole > 1n || (days.whole === 1n && /[1-9]/.test(days.fraction)))
})
const formError = ref('')
const openedIssue = ref<number | null>(null)
const people = ref<MeetingPerson[]>([]), peopleLoading = ref(false), recipientId = ref<number | null>(null)
const reminders = ref<Reminder[]>([]), targetMissing = ref(false)
const shownReminders = new Set<number>()
let createRequest: { body: string; key: string } | null = null
let copyRequest: { cardId: number; key: string } | null = null
let transferRequest: { recipient: number; key: string } | null = null
const options = computed(() => [...new Set([...sharedTaskTypes, ...categories.value.map(category => category.name)])])
const grouped = computed(() => columns.map(column => ({
  ...column, cards: cards.value.filter(card => card.state === column.state)
    .sort((left, right) => left.position - right.position || left.id - right.id),
})))
const visibleColumns = computed(() => planMode.value ? grouped.value.filter(column => column.state !== 'done') : grouped.value)
const completedCards = computed(() => grouped.value.find(column => column.state === 'done')!.cards)
const lastWeek = computed(() => weekStart.value ? addDays(weekStart.value, -7) : '')
function completionGroup(card: Card) {
  if (card.completed_week === weekStart.value) return '本周'
  if (card.completed_week === lastWeek.value) return '上周'
  return '更早'
}
const completedGroups = computed(() => ['本周', '上周', '更早'].map(label => ({
  label, cards: completedCards.value.filter(card => completionGroup(card) === label),
})))
const historyCards = computed(() => completedGroups.value[2].cards)
const canContinue = computed(() => cards.value.some(card => card.state === 'in_progress' && !card.has_current_detail))

function chargeValue(card: Card) {
  if (progressDraft.value?.cardId === card.id) return `${progressDraft.value.percent}%`
  return card.state === 'done' ? '100%' : card.status || '5%'
}

function startProgressDrag(event: PointerEvent, card: Card) {
  if (event.button !== 0 || busy.value || progressDraft.value) return
  const handle = event.currentTarget as HTMLElement
  const track = handle.parentElement?.querySelector('.board-charge-fill')
  if (!track) return
  event.preventDefault()
  closePreview()
  handle.focus({ preventScroll: true })
  handle.setPointerCapture(event.pointerId)
  const percent = Number.parseInt(chargeValue(card))
  progressPointer = { id: event.pointerId, startX: event.clientX, width: track.getBoundingClientRect().width, percent }
  progressDraft.value = { cardId: card.id, percent }
}

function updateProgressDrag(event: PointerEvent) {
  if (progressPointer?.id !== event.pointerId || !progressDraft.value) return
  const { startX, width, percent } = progressPointer
  // 按指针移动距离换算进度，让鼠标抓住竖线后不会跳到其他档位。
  const position = percent + (event.clientX - startX) / width * 100
  progressDraft.value.percent = progressSteps.reduce((closest, step) =>
    Math.abs(step - position) < Math.abs(closest - position) ? step : closest)
}

function endProgressDrag(event: PointerEvent, card: Card) {
  if (progressPointer?.id !== event.pointerId || !progressDraft.value) return
  updateProgressDrag(event)
  progressPointer = null
  void saveProgress(card, progressDraft.value.percent)
}

function cancelProgressDrag(event: PointerEvent) {
  if (progressPointer?.id === event.pointerId) {
    progressPointer = null
    progressDraft.value = null
  }
}

function progressKey(event: KeyboardEvent, card: Card) {
  if (event.key === 'Escape' && progressPointer) {
    const handle = event.currentTarget as HTMLElement
    handle.releasePointerCapture(progressPointer.id)
    progressPointer = null
    progressDraft.value = null
    return
  }
  if (busy.value || progressDraft.value) return
  let index = progressSteps.indexOf(Number.parseInt(chargeValue(card)))
  switch (event.key) {
    case 'ArrowRight': case 'ArrowUp': index++; break
    case 'ArrowLeft': case 'ArrowDown': index--; break
    case 'Home': index = 0; break
    case 'End': index = progressSteps.length - 1; break
    default: return
  }
  event.preventDefault()
  void saveProgress(card, progressSteps[Math.max(0, Math.min(index, progressSteps.length - 1))])
}

async function saveProgress(card: Card, percent: number) {
  const status = `${percent}%`
  if (status !== (card.status || '5%')) {
    progressDraft.value = { cardId: card.id, percent }
    await perform(async () => {
      saveCard(await api<Card>(`/board-tasks/${card.id}/progress`, 'PATCH', {
        status, revision: card.revision, week_start: weekStart.value,
      }))
    })
  }
  progressDraft.value = null
}

function cancelPreviewTimer() { window.clearTimeout(previewTimer) }

function closePreview() {
  cancelPreviewTimer()
  previewId.value = null
  previewAnchor = null
}

function schedulePreview(event: PointerEvent | FocusEvent, card: Card) {
  const anchor = event.currentTarget as HTMLElement
  if (busy.value || dragged.value !== null || progressDraft.value || action.value || openedIssue.value !== null) return
  if ('pointerType' in event ? event.pointerType === 'touch' : !anchor.matches(':focus-visible')) return
  if (previewId.value === card.id) { cancelPreviewTimer(); return }
  closePreview()
  previewAnchor = anchor
  previewTimer = window.setTimeout(() => {
    if (!anchor.isConnected) { closePreview(); return }
    // 固定定位避开看板列的滚动裁切，底部空间不足时在卡片上方展开。
    const rect = anchor.getBoundingClientRect()
    const { clientWidth, clientHeight } = document.documentElement
    const width = Math.min(340, clientWidth - 16)
    const below = clientHeight - rect.bottom - 8
    const above = rect.top - 8
    const upward = below < Math.min(260, above)
    previewStyle.value = {
      width: `${width}px`, left: `${Math.max(8, Math.min(rect.left, clientWidth - width - 8))}px`,
      maxHeight: `${upward ? above : below}px`,
      ...(upward ? { bottom: `${clientHeight - rect.top}px` } : { top: `${rect.bottom}px` }),
    }
    previewId.value = card.id
  }, 1000)
}

function leavePreview(event: PointerEvent | FocusEvent) {
  if (event.currentTarget !== previewAnchor && event.currentTarget !== previewPanel.value) return
  if ('pointerType' in event && previewAnchor?.matches(':focus-visible')) return
  if (event.relatedTarget instanceof Node &&
    (previewPanel.value?.contains(event.relatedTarget) || previewAnchor?.contains(event.relatedTarget))) return
  if (previewId.value === null) closePreview()
  else {
    cancelPreviewTimer()
    previewTimer = window.setTimeout(closePreview, 120)
  }
}

function dismissPreviewOutside(event: Event) {
  if (!(event.target instanceof Node) || !previewPanel.value?.contains(event.target)) closePreview()
}

function escapePreview(event: KeyboardEvent) {
  if (event.key === 'Escape') closePreview()
}

function stepEstimate(direction: 1 | -1) {
  const days = estimatedDayParts.value
  if (!days || (direction < 0 && !canDecreaseEstimate.value)) return
  // 步进只改变整数部分，保留用户输入的小数精度。
  estimatedDays.value = `${days.whole + BigInt(direction)}${days.fraction}`
}

function message(cause: unknown) {
  return cause instanceof ApiError ? cause.message : '操作失败，请重试。'
}
async function load() {
  loading.value = true
  error.value = ''
  try {
    const [types] = await Promise.all([api<Category[]>('/categories'), refreshBoard()])
    categories.value = types
  } catch (cause) {
    error.value = message(cause)
  } finally { loading.value = false }
}
async function refreshBoard() {
  const board = await api<{ current_week: string; tasks: Card[]; reminders?: Reminder[] }>('/board-tasks')
  cards.value = board.tasks
  weekStart.value = board.current_week
  reminders.value = board.reminders ?? []
}
onMounted(() => {
  document.addEventListener('keydown', escapePreview)
  document.addEventListener('scroll', dismissPreviewOutside, true)
  document.addEventListener('pointerdown', dismissPreviewOutside, true)
  window.addEventListener('resize', closePreview)
  void load()
})
onUnmounted(() => {
  document.removeEventListener('keydown', escapePreview)
  document.removeEventListener('scroll', dismissPreviewOutside, true)
  document.removeEventListener('pointerdown', dismissPreviewOutside, true)
  window.removeEventListener('resize', closePreview)
  closePreview()
})
watch([loading, () => props.targetTask, () => props.targetRefresh], async ([, target], [wasLoading], onCleanup) => {
  let active = true
  let stop: (() => void) | undefined
  onCleanup(() => { active = false; stop?.() })
  targetMissing.value = false
  if (planMode.value || loading.value || !weekStart.value) return
  // 在已打开的看板上点击通知，重新读取卡片与尚未展示的引导。
  if (!wasLoading && target) {
    try { await refreshBoard() }
    catch (cause) { if (active) error.value = message(cause); return }
    await nextTick()
  }
  if (!active) return
  if (target) {
    if (!showHistory.value && historyCards.value.some(card => card.id === target)) {
      showHistory.value = true
      await nextTick()
      if (!active) return
    }
    const element = document.getElementById(`board-task-${target}`)
    targetMissing.value = !element
    element?.focus({ preventScroll: true })
    element?.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' })
  }
  const pending = [...reminders.value].sort((a, b) => Number(b.card_id === target) - Number(a.card_id === target))
  const steps = pending.flatMap(reminder => {
    const card = cards.value.find(item => item.id === reminder.card_id)
    const element = document.getElementById(`board-task-${reminder.card_id}`)
    if (!card || !element || shownReminders.has(reminder.id)) return []
    const name = card.name || '未命名任务'
    const transferred = reminder.kind === '转交任务'
    const sender = card.transferred_by || '同事'
    return [{
      element,
      title: transferred ? '收到转交任务' : '收到会议指派',
      description: transferred ? `${sender}转交给你「${name}」。` : `会议指派给你「${name}」。`,
      onShown: () => {
        if (shownReminders.has(reminder.id)) return
        shownReminders.add(reminder.id)
        void api(`/board-tasks/reminders/${reminder.id}`, 'PATCH').catch(() => {
          // 记录失败时保留服务端的待提醒状态，下次进入仍可查看。
        })
      },
    }]
  })
  if (!steps.length) return
  const module = await import('./sidebarTour').catch(() => undefined)
  if (active && module) stop = module.startBoardTaskTour(steps)
}, { flush: 'post' })

function saveCard(card: Card) {
  const index = cards.value.findIndex(item => item.id === card.id)
  if (index >= 0) cards.value[index] = card
  else cards.value.push(card)
}
function path(card: Card, suffix = '') {
  return `/board-tasks/${card.id}${suffix}?revision=${card.revision}&week_start=${weekStart.value}`
}
async function perform(job: () => Promise<void>, inDialog = false) {
  if (busy.value || loading.value) return
  closePreview()
  busy.value = true
  error.value = ''
  formError.value = ''
  notice.value = ''
  try {
    await job()
    if (inDialog) dialog.value?.close()
  } catch (cause) {
    if (inDialog) formError.value = message(cause)
    else error.value = message(cause)
  } finally { busy.value = false }
}
function continueThisWeek() {
  void perform(async () => {
    const weekPath = `/weeks/${weekStart.value}`
    const week = await api<WeekData>(weekPath)
    // 与本周工作共用批量续做接口，由服务端按卡片与周明细的关联去重。
    const result = await api<WeekData>(`${weekPath}/add-in-progress?revision=${week.revision}`, 'POST', undefined, newIdempotencyKey())
    notice.value = result.no_source ? '进行中的任务均已加入本周工作。' : '已将进行中的任务加入本周工作。'
    await refreshBoard()
  })
}
function open(nextAction: Dialog) {
  if (busy.value || props.planBusy) return
  closePreview()
  action.value = nextAction
  formError.value = ''
  if (nextAction.kind === 'edit') {
    const card = nextAction.card
    Object.assign(form, { name: card?.name ?? '', category_name: card?.category_name ?? '其他', priority: card?.priority ?? '低', notes: card?.notes ?? '' })
    estimatedDays.value = card?.estimated_days ?? ''
    createRequest = null
  }
  if (nextAction.kind === 'transfer') {
    people.value = []
    recipientId.value = null
    transferRequest = null
    void loadRecipients()
  }
  void nextTick(() => dialog.value?.showModal())
}
function editInboxCard(event: MouseEvent | KeyboardEvent, card: Card) {
  if (card.state !== 'inbox' || (event.target instanceof Element && event.target.closest('button, a'))) return
  open({ kind: 'edit', card })
}
async function loadRecipients() {
  const pending = action.value
  peopleLoading.value = true
  formError.value = ''
  try {
    const result = await api<MeetingPerson[]>('/task-transfer-recipients')
    if (action.value === pending) people.value = result
  } catch (cause) {
    if (action.value === pending) formError.value = message(cause)
  } finally {
    if (action.value === pending) peopleLoading.value = false
  }
}
function removeCard(id: number) {
  cards.value = cards.value.filter(card => card.id !== id)
}
async function submit() {
  const pending = action.value
  if (!pending) return
  await perform(async () => {
    if (pending.kind === 'edit') {
      const fields = { ...form, name: form.name.trim() }
      if (!fields.name && !pending.card?.name_locked && !pending.card?.has_other_details) { throw new ApiError(422, '请输入任务名称。') }
      const estimate = estimatedDays.value
      // 保留小数原文，提交前校验格式和正值，避免浮点转换丢失精度。
      if (estimate && (!estimatedDayParts.value || !/[1-9]/.test(estimate))) {
        throw new ApiError(422, '预估工时须为大于 0 的整数或小数。')
      }
      const data = { ...fields, estimated_days: estimate || null }
      if (pending.card) {
        const patch = pending.card.has_other_details ? { notes: fields.notes } : data
        saveCard(await api<Card>(path(pending.card), 'PATCH', patch))
      } else {
        const body = JSON.stringify(data)
        if (createRequest?.body !== body) createRequest = { body, key: newIdempotencyKey() }
        const card = await api<Card>('/board-tasks', 'POST', data, createRequest.key)
        saveCard(card)
        await nextTick()
        document.getElementById(`board-task-${card.id}`)?.closest('.board-card-list')?.scrollTo({ top: 0 })
      }
    } else if (pending.kind === 'remove') {
      await api(path(pending.card), 'DELETE')
      removeCard(pending.card.id)
    } else if (pending.kind === 'transfer') {
      const person = people.value.find(item => item.id === recipientId.value)
      if (!person) return
      if (transferRequest?.recipient !== person.id) transferRequest = { recipient: person.id, key: newIdempotencyKey() }
      await api(path(pending.card, '/transfer'), 'POST', { user_id: person.id }, transferRequest.key)
      removeCard(pending.card.id)
      notice.value = `已将「${pending.card.name || '未命名任务'}」送到 ${person.display_name} 的任务箱。`
    } else {
      await move(pending.card, 'inbox')
    }
  }, true)
}
function duplicate(card: Card) {
  void perform(async () => {
    if (copyRequest?.cardId !== card.id) copyRequest = { cardId: card.id, key: newIdempotencyKey() }
    saveCard(await api<Card>(path(card, '/duplicate'), 'POST', undefined, copyRequest.key))
    copyRequest = null
  })
}
async function move(card: Card, state: State) {
  saveCard(await api<Card>(`/board-tasks/${card.id}/status`, 'PATCH', {
    state, revision: card.revision, week_start: weekStart.value,
  }))
}
function requestMove(card: Card, state: State) {
  if (busy.value || state === card.state || card.deployment_archived) return
  if (state === 'inbox' && card.has_current_detail) open({ kind: 'return', card })
  else void perform(() => move(card, state))
}
function canDrag(card: Card) {
  return !busy.value && !card.deployment_archived && !props.planBusy && !props.plannedIds?.has(card.id)
}
function startDrag(event: DragEvent, card: Card) {
  if (!canDrag(card) || progressDraft.value || !event.dataTransfer) { event.preventDefault(); return }
  closePreview()
  if (planMode.value) {
    // 引用原任务生成计划，和看板内部的移列、排序使用不同的拖拽类型。
    event.dataTransfer.effectAllowed = 'copy'
    event.dataTransfer.setData('application/x-zhoubao-board-plan', String(card.id))
    emit('plan-drag', card.id)
    return
  }
  dragged.value = card.id
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('application/x-zhoubao-board-card', String(card.id))
}
function resetDrag() {
  if (planMode.value) emit('plan-drag', null)
  dragged.value = null
  hovered.value = null
  dropBefore.value = null
}
function beforeCardAtPointer(event: DragEvent, card: Card) {
  const column = event.currentTarget as HTMLElement
  const group = card.state === 'done' ? (event.target as Element).closest<HTMLElement>('[data-completion-group]') : column
  if (!group || (card.state === 'done' && group.dataset.completionGroup !== completionGroup(card))) return undefined
  // 用卡片中线区分插入该卡片之前或之后，拖动中的卡片不参与比较。
  let lastPeerId: number | null = null
  for (const element of Array.from(group.querySelectorAll<HTMLElement>('[data-card-id]'))) {
    const id = Number(element.dataset.cardId)
    if (id === card.id) continue
    const rect = element.getBoundingClientRect()
    if (event.clientY < rect.top + rect.height / 2) return id
    lastPeerId = id
  }
  if (card.state === 'done') {
    if (lastPeerId === null) return undefined
    // 组尾插入最后一个同组卡片之后，保留其他周卡片的相对顺序。
    const peers = completedCards.value.filter(item => item.id !== card.id)
    return peers[peers.findIndex(item => item.id === lastPeerId) + 1]?.id ?? null
  }
  return null
}
async function reorder(card: Card, beforeId: number | null) {
  const positions = await api<Pick<Card, 'id' | 'position' | 'revision'>[]>(`/board-tasks/${card.id}/position`, 'PATCH', {
    before_id: beforeId, revision: card.revision, week_start: weekStart.value,
  })
  const byId = new Map(positions.map(item => [item.id, item]))
  for (const item of cards.value) {
    const update = byId.get(item.id)
    if (update) item.position = update.position
    if (item.id === card.id && update) item.revision = update.revision
  }
}
function dragOver(event: DragEvent, state: State) {
  if (busy.value || dragged.value === null) return
  event.preventDefault()
  hovered.value = state
  const card = cards.value.find(item => item.id === dragged.value)
  const beforeId = card?.state === state ? beforeCardAtPointer(event, card) : null
  const target = cards.value.find(item => item.id === beforeId)
  dropBefore.value = card?.state === 'done' && target && completionGroup(target) !== completionGroup(card)
    ? null : beforeId ?? null
}
function drop(event: DragEvent, state: State) {
  if (planMode.value) return
  event.preventDefault()
  const card = cards.value.find(item => item.id === dragged.value)
  const beforeId = card?.state === state ? beforeCardAtPointer(event, card) : null
  resetDrag()
  if (!card) return
  if (card.state === state && beforeId !== undefined) void perform(() => reorder(card, beforeId))
  else requestMove(card, state)
}
</script>

<template>
  <p v-if="loading" role="status">正在加载任务看板…</p>
  <div v-if="error" class="message error board-error" role="alert">
    {{ error }} <button type="button" class="mini-button" @click="load">重新载入</button>
  </div>
  <p v-if="notice" class="message board-notice" role="status">{{ notice }}</p>
  <p v-if="targetMissing" class="message board-notice" role="status">这条消息对应的任务已离开你的看板。</p>
  <div v-if="!loading && weekStart" class="board" :class="{ 'board-plan': planMode }">
    <section v-for="column in visibleColumns" :key="column.state" class="board-column panel"
      :class="{ 'board-drop-target': hovered === column.state }" :aria-label="column.name"
      @dragover="dragOver($event, column.state)" @drop="drop($event, column.state)">
      <header class="board-heading">
        <h2>{{ column.name }}</h2>
        <button v-if="planMode && column.state === 'inbox'" type="button" class="icon-btn" aria-label="添加任务" aria-haspopup="dialog"
          :disabled="busy || planBusy" @click="open({ kind: 'edit' })">＋</button>
        <button v-else-if="column.state === 'inbox'" type="button" class="primary-button"
          :disabled="busy" @click="open({ kind: 'edit' })">＋ 添加任务</button>
        <button v-else-if="!planMode && column.state === 'in_progress'" type="button" class="secondary-button"
          :disabled="busy || !canContinue" @click="continueThisWeek">添加到本周工作</button>
      </header>
      <div class="board-card-list">
        <template v-for="group in column.state === 'done' ? completedGroups : [{ label: '', cards: column.cards }]" :key="group.label">
          <button v-if="group.label === '更早' && historyCards.length" type="button" class="mini-button board-history-toggle"
            :aria-expanded="showHistory" @click="showHistory = !showHistory">
            {{ showHistory ? '收起更早任务' : `展开更多（${historyCards.length}）` }}
          </button>
          <section v-if="group.label !== '更早' || (showHistory && historyCards.length)" class="board-card-group"
            :aria-label="group.label || undefined" :data-completion-group="group.label || undefined">
            <h3 v-if="group.label" class="board-week-heading">{{ group.label }}</h3>
            <p v-if="!group.cards.length" class="board-empty">暂无任务</p>
            <article v-for="card in group.cards" :key="card.id" :id="`board-task-${card.id}`" class="board-card priority-edge" :data-priority="card.priority"
              tabindex="0" :data-card-id="card.id" :class="{ 'board-drop-before': dropBefore === card.id, 'board-target': targetTask === card.id, 'board-card-charging': card.state !== 'inbox' }"
              :aria-label="`${card.name || '未命名任务'}，优先级${card.priority}`" :draggable="canDrag(card)"
              :aria-keyshortcuts="planMode && card.state === 'inbox' ? 'Enter' : undefined"
              :aria-describedby="previewId === card.id ? 'board-task-preview' : undefined"
              @pointerenter="schedulePreview($event, card)" @pointerleave="leavePreview"
              @focus="schedulePreview($event, card)" @focusout="leavePreview"
              @dblclick="editInboxCard($event, card)"
              @keydown.enter.self="planMode && editInboxCard($event, card)"
              @dragstart="startDrag($event, card)" @dragend="resetDrag">
              <div v-if="card.state !== 'inbox'" class="board-charge-fill" aria-hidden="true"
                :class="{ 'board-charge-adjusting': progressDraft?.cardId === card.id }" :style="{ '--charge': chargeValue(card) }" />
              <div class="board-card-content">
                <div class="board-card-title">
                  <RouterLink v-if="card.meeting_id" class="task-transfer-mark task-meeting-link" :draggable="planMode ? false : undefined"
                    :to="{ name: 'meetings', query: { meeting: card.meeting_id } }" title="会议指派，点击可跳转会议记录" aria-label="查看指派会议">💡</RouterLink>
                  <span v-if="card.transferred_by" class="task-transfer-mark" role="img"
                    :aria-label="`由${card.transferred_by}转交的任务`" :title="`由${card.transferred_by}转交的任务`">💡</span>
                  <button v-if="card.review_issue_id" class="task-review-info" type="button" aria-haspopup="dialog"
                    title="点击可查看审查记录的内容" aria-label="点击可查看审查记录的内容" @click="openedIssue = card.review_issue_id">
                    <span aria-hidden="true">i</span>
                  </button>
                  <RouterLink v-if="card.deployment_plan_id" class="task-transfer-mark task-meeting-link" :draggable="false"
                    :to="deploymentLocation('plans', { plan: card.deployment_plan_id })" title="查看机房发版计划" aria-label="查看机房发版计划"><DeploymentTaskIcon /></RouterLink>
                  <span v-if="card.estimated_days" class="board-card-estimate" role="img"
                    :aria-label="`预估 ${card.estimated_days} 人天`" :style="{ '--estimate-length': card.estimated_days.length }">
                    <img :src="stopwatch" alt="" draggable="false" />
                    <span aria-hidden="true" :class="{ 'board-estimate-compact': card.estimated_days.length > 3 }">{{ card.estimated_days }}</span>
                  </span>
                  <strong>{{ card.name || '未命名任务' }}</strong>
                </div>
              </div>
              <div v-if="planMode" class="board-card-actions">
                <button type="button" class="mini-button board-plan-add" :aria-disabled="!canDrag(card)"
                  :aria-label="`${plannedIds?.has(card.id) ? '已加入计划' : '加入计划'}：${card.name || '未命名任务'}`"
                  @click="canDrag(card) && emit('add-plan', card.id)">{{ plannedIds?.has(card.id) ? '已加入' : '加入计划' }}</button>
              </div>
              <div v-else-if="card.state !== 'done' && !card.deployment_plan_id" class="board-card-actions">
                <button type="button" class="icon-btn" aria-label="转交任务" aria-haspopup="dialog"
                  :disabled="busy || card.has_other_details" :title="card.has_other_details ? '已有历史周明细，无法转交' : '转交任务'"
                  @click="open({ kind: 'transfer', card })">
                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 5h18l-7 15-3-7-8-3zM11 13l10-8" stroke-linecap="round" stroke-linejoin="round"/></svg>
                </button>
                <button v-if="card.state === 'inbox'" type="button" class="icon-btn" aria-label="复制任务" :disabled="busy || card.has_other_details"
                  :title="card.has_other_details ? '已关联其他周的任务明细' : '复制任务'" @click="duplicate(card)">
                  <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="1"/><path d="M16 8V4H4v12h4"/></svg>
                </button>
                <button v-if="card.state === 'inbox'" type="button" class="icon-btn" aria-label="修改任务" :disabled="busy"
                  :title="card.has_other_details ? '修改备注' : '修改任务'" @click="open({ kind: 'edit', card })">
                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m4 20 4-1 12-12-3-3L5 16zM14 7l3 3"/></svg>
                </button>
                <button v-if="card.state === 'inbox'" type="button" class="icon-btn danger" aria-label="删除任务" :disabled="busy || card.has_other_details || !!card.meeting_id"
                  :title="card.meeting_id ? '会议指派任务，请在会议记录中取消指派' : card.has_other_details ? '已关联其他周的任务明细' : '删除任务'" @click="open({ kind: 'remove', card })">
                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M9 6V3h6v3M6 6l1 14h10l1-14M10 10v6m4-6v6"/></svg>
                </button>
              </div>
              <span v-if="card.state === 'done' || (planMode && card.state === 'in_progress')" class="board-charge-value" role="meter" aria-label="完成状态"
                aria-valuemin="0" aria-valuemax="100" :aria-valuenow="Number.parseInt(chargeValue(card))">{{ chargeValue(card) }}</span>
              <template v-else-if="card.state === 'in_progress'">
                <span class="board-charge-value" aria-hidden="true">{{ chargeValue(card) }}</span>
                <span class="board-charge-handle" role="slider" aria-label="完成状态" tabindex="0"
                  :aria-valuemin="progressSteps[0]" :aria-valuemax="progressSteps[progressSteps.length - 1]"
                  :aria-valuenow="Number.parseInt(chargeValue(card))" :aria-valuetext="chargeValue(card)"
                  :aria-disabled="busy || undefined" :style="{ '--charge': chargeValue(card) }"
                  :class="{ 'board-charge-adjusting': progressDraft?.cardId === card.id }"
                  @pointerdown="startProgressDrag($event, card)" @pointermove="updateProgressDrag"
                  @pointerup="endProgressDrag($event, card)" @pointercancel="cancelProgressDrag"
                  @lostpointercapture="cancelProgressDrag" @dragstart.prevent.stop @keydown="progressKey($event, card)" />
              </template>
            </article>
          </section>
        </template>
      </div>
    </section>
  </div>
  <Teleport to="body">
    <div v-if="previewCard" id="board-task-preview" ref="previewPanel" class="board-task-preview" role="tooltip"
      :style="previewStyle" @pointerenter="cancelPreviewTimer" @pointerleave="leavePreview">
      <strong class="preline">{{ previewCard.name || '未命名任务' }}</strong>
      <dl>
        <dt>任务类型</dt><dd>{{ previewCard.category_name || '未选择' }}</dd>
        <dt>优先级</dt><dd>{{ previewCard.priority }}</dd>
        <dt>状态</dt><dd>{{ previewCard.state === 'inbox' ? '未开始' : previewCard.state === 'done' ? '已完成' : `进行中 · ${chargeValue(previewCard)}` }}</dd>
        <template v-if="previewCard.completed_week"><dt>完成周</dt><dd>{{ previewCard.completed_week }}</dd></template>
        <template v-if="previewCard.estimated_days"><dt>预估工时</dt><dd>{{ previewCard.estimated_days }} 人天</dd></template>
        <template v-if="previewCard.transferred_by"><dt>转交人</dt><dd>{{ previewCard.transferred_by }}</dd></template>
        <dt>备注</dt><dd class="preline">{{ previewCard.notes || '无' }}</dd>
      </dl>
    </div>
  </Teleport>
  <ReviewIssueDialog v-if="openedIssue !== null" :issue-id="openedIssue" @close="openedIssue = null" />

  <!-- 原生弹窗统一处理 Esc，保存过程中保留弹窗以便显示请求结果。 -->
  <dialog ref="dialog" class="modal board-dialog" aria-labelledby="board-dialog-title" @close="action = null"
    @cancel="busy && $event.preventDefault()" @keydown.esc.stop>
    <form v-if="action" class="stack-form" @submit.prevent="submit">
      <h2 id="board-dialog-title">{{ action.kind === 'edit' ? (action.card ? '修改任务' : '添加任务') : action.kind === 'remove' ? '删除任务' : action.kind === 'transfer' ? '转交任务' : '移回任务箱' }}</h2>
      <template v-if="action.kind === 'edit'">
        <label>任务类型<select v-model="form.category_name" :required="!!form.category_name || action.card?.category_name !== ''" :disabled="busy || action.card?.has_other_details">
          <option value="" disabled>{{ action.card?.category_name === '' ? '未选择' : '请选择任务类型' }}</option>
          <option v-if="form.category_name && !options.includes(form.category_name)" :value="form.category_name">{{ form.category_name }}（历史）</option>
          <option v-for="name in options" :key="name" :value="name">{{ name }}</option>
        </select></label>
        <label>任务名称
          <textarea v-model="form.name" placeholder="用尽量简短的一句话描述任务，一个任务工时尽量在5天以内，具体工作内容可写在备注中。"
            rows="3" maxlength="200" required :disabled="busy || action.card?.name_locked || action.card?.has_other_details" />
        </label>
        <div class="board-estimate-row">
          <div class="board-estimate-field">
            <label for="board-estimated-days">预估工时（人天）</label>
            <div class="board-estimate-input">
              <input id="board-estimated-days" v-model.trim="estimatedDays" type="text" inputmode="decimal" :disabled="busy || action.card?.has_other_details" />
              <div class="board-estimate-steppers">
                <button type="button" aria-label="增加 1 人天" :disabled="busy || action.card?.has_other_details || !estimatedDayParts" @click="stepEstimate(1)">▲</button>
                <button type="button" aria-label="减少 1 人天" :disabled="busy || action.card?.has_other_details || !canDecreaseEstimate" @click="stepEstimate(-1)">▼</button>
              </div>
            </div>
          </div>
          <label>优先级<select v-model="form.priority" :disabled="busy || action.card?.has_other_details">
            <option value="高">高</option><option value="中">中</option><option value="低">低</option>
          </select></label>
        </div>
        <label>备注<textarea v-model="form.notes" rows="3" maxlength="5000" :disabled="busy" /></label>
      </template>
      <template v-else-if="action.kind === 'transfer'">
        <p>将「{{ action.card.name || '未命名任务' }}」送到接收人的任务箱。</p>
        <p v-if="peopleLoading" role="status">正在加载接收人…</p>
        <button v-else-if="!people.length && formError" type="button" class="secondary-button" @click="loadRecipients">重新加载接收人</button>
        <p v-else-if="!people.length" role="status">暂无可转交的普通用户。</p>
        <label v-else>接收人<select v-model="recipientId" :disabled="busy" required>
          <option :value="null" disabled>请选择接收人</option>
          <option v-for="person in people" :key="person.id" :value="person.id">{{ person.display_name }}（{{ person.username }}）</option>
        </select></label>
      </template>
      <p v-else-if="action.kind === 'return'">移回「{{ action.card.name }}」将删除它关联的本周任务明细。确认移回？</p>
      <p v-else>确认删除「{{ action.card.name }}」？<template v-if="action.card.has_current_detail"> 此操作也会删除它关联的本周任务明细。</template></p>
      <p v-if="formError" class="message error" role="alert">{{ formError }}</p>
      <div class="modal-actions">
        <button type="button" class="secondary-button" :disabled="busy" @click="dialog?.close()">取消</button>
        <button type="submit" class="primary-button" :class="{ 'board-destructive': action.kind === 'remove' || action.kind === 'return' }"
          :disabled="busy || (action.kind === 'transfer' && recipientId === null)">
          {{ dialogLabels[action.kind] }}
        </button>
      </div>
    </form>
  </dialog>
</template>

<style scoped>
.board {
  flex: 1; min-height: 0; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
  align-content: start; align-items: start; gap: 16px;
  /* 栏目高度取页头下方的可用空间，随窗口和页头尺寸变化。 */
  container-type: size;
}
.board-column {
  display: grid; grid-template-rows: auto minmax(0, 1fr); gap: 12px;
  min-width: 0; min-height: 180px; min-height: min(180px, 100cqh);
  max-height: 100dvh; max-height: 100cqh; padding: 14px;
}
.board-plan {
  grid-template-columns: minmax(0, 1fr); grid-template-rows: repeat(2, minmax(0, 1fr));
  align-items: stretch; gap: 12px;
}
.board-plan .board-column {
  min-height: 0; max-height: none; padding: 0; gap: 0;
  border: 1px solid #000; box-shadow: none;
}
.board-plan .board-heading {
  min-height: 36px; padding: 4px 8px; flex-wrap: nowrap;
  border-bottom: 1px solid #000; background: #ccff00;
}
.board-plan .board-heading h2 { font-size: 15px; }
.board-plan .board-heading .icon-btn { padding: 1px 6px; }
.board-plan .board-card-list { margin: 0; padding: 8px; }
.board-plan .board-card-group { gap: 8px; }
.board-plan .board-empty { padding: 0; }
.board-plan .board-card {
  display: grid; grid-template-columns: minmax(0, 1fr) auto; block-size: 60px; padding-block: 4px;
}
/* 40px 宽的秒表符合原比例，能放进卡片的 50px 内容高度。 */
.board-plan .board-card-estimate { max-inline-size: 40px; }
.board-plan .board-card-content { justify-items: stretch; }
.board-plan .board-card-title strong { min-inline-size: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.board-plan .board-card[draggable="false"] { cursor: default; }
.board-plan-add[aria-disabled="true"] { cursor: default; color: #555; background: #f4f4f4; box-shadow: none; transform: none; }
.board-card-list {
  display: grid; align-content: start; gap: 12px; min-height: 0; overflow-y: auto;
  margin: -4px; padding: 4px;
}
.board-card-group { display: grid; gap: 12px; min-width: 0; }
.board-week-heading { margin: 0; padding: 0 0 6px; border-bottom: 1px solid #d9e2e8; color: #334b5a; font-size: .875rem; }
.board-week-heading + .board-empty { padding: 0 0 4px; font-size: .875rem; }
.board-history-toggle { justify-self: start; }
.board-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-height: 44px; flex-wrap: wrap; }
.board-heading h2, .board-empty { margin: 0; }
.board-empty { padding: 14px 0; color: #555; }
.board-dialog textarea { width: 100%; overflow-wrap: anywhere; resize: vertical; }
.board-dialog textarea::placeholder { color: #656b73; }
.board-dialog textarea:focus::placeholder { color: transparent; }
.board-estimate-row { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; align-items: start; }
.board-estimate-field { display: grid; gap: 7px; }
.board-estimate-input { position: relative; }
.board-estimate-input input, .board-estimate-row select { height: 38px; }
.board-estimate-input input { padding-inline-end: 42px; }
.board-estimate-steppers { position: absolute; inset-block: 2px; inset-inline-end: 2px; display: grid; grid-template-rows: repeat(2, 1fr); }
.board-estimate-steppers button { width: 32px; padding: 0; border: 0; border-inline-start: 1px solid #222; background: #fff; font-size: 10px; }
.board-estimate-steppers button + button { border-block-start: 1px solid #222; }
.board-estimate-steppers button:not(:disabled):hover { background: #ffff00; }
.board-estimate-steppers button:focus-visible { outline-offset: -3px; }
.board-drop-target { outline: 3px solid #75a60a; outline-offset: -5px; }
.board-card.board-drop-before { outline: 2px solid #75a60a; outline-offset: 2px; }
.board-card.board-target { outline: 2px solid #13766a; outline-offset: 2px; }
.board-card { background: #fff; border: 1px solid #222; border-left: 4px solid var(--priority-glow); box-shadow: var(--priority-edge-shadow); padding: 10px 8px 10px 12px; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; cursor: grab; }
.board-card-content { display: grid; gap: 6px; justify-items: start; min-width: 0; overflow-wrap: anywhere; }
.board-card-title { display: flex; align-items: center; gap: 4px; min-width: 0; }
.board-card-title > :not(strong) { flex: none; }
.board-card-title .task-review-info { width: 18px; height: 18px; }
.board-card-content strong { white-space: pre-wrap; }
.board-card-estimate { position: relative; width: clamp(30px, calc(var(--estimate-length) * 6px), 54px); aspect-ratio: 116 / 144; }
.board-card-estimate img { display: block; width: 100%; }
/* 表盘圆心在素材高度的 60%，上部按钮不参与文字居中。 */
.board-card-estimate > span {
  position: absolute; inset: 60% auto auto 50%; translate: -50% -50%; max-width: 76%;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #111; font: 700 11px/1 Arial, sans-serif;
}
.board-card-estimate > .board-estimate-compact { font-size: 8px; }
.board-task-preview {
  position: fixed; z-index: 19; overflow: auto; overscroll-behavior: contain;
  padding: 12px; border: 2px solid #222; box-shadow: 4px 4px 0 #000; background: #fff;
  color: #222; overflow-wrap: anywhere;
}
.board-task-preview dl { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 6px 12px; margin: 8px 0 0; font-size: .85rem; }
.board-task-preview dt { font-weight: 700; }
.board-task-preview dd { margin: 0; }
.board-card-actions { display: flex; margin-left: auto; align-items: center; gap: 4px; flex-wrap: wrap; }
.board-card-actions svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 1.7; }
.board-notice { margin: 0 0 8px; }
.board-card-charging {
  position: relative;
  isolation: isolate;
  border-radius: 8px;
  color: #112d3e;
  background: #eaf1f6;
}
.board-card-charging::after {
  content: '';
  position: absolute;
  inset-inline-end: -5px;
  inset-block-start: 50%;
  translate: 0 -50%;
  inline-size: 4px;
  block-size: 23px;
  border-radius: 0 3px 3px 0;
  background: #426675;
  pointer-events: none;
}
.board-card-charging .board-card-title strong { text-shadow: 0 0 3px #edf8f8, 0 0 5px #edf8f8; }
/* 电量层独立于任务文字和操作区，拥有柔和的刻度与充电边缘。 */
.board-charge-fill {
  position: absolute;
  z-index: -1;
  inset: 0;
  overflow: hidden;
  border-radius: inherit;
  pointer-events: none;
  background: repeating-linear-gradient(90deg, transparent 0 23px, #244e6312 23px 24px);
}
.board-charge-fill::before {
  content: '';
  display: block;
  box-sizing: border-box;
  block-size: 100%;
  inline-size: var(--charge);
  border-inline-end: 2px solid #2a9e8a;
  background: repeating-linear-gradient(90deg, transparent 0 23px, #207a7624 23px 24px), linear-gradient(110deg, #9ddfea, #92edcb);
  box-shadow: 4px 0 12px #39bca052;
  animation: board-charge-in 650ms var(--charge-easing);
  transition: inline-size 430ms var(--charge-easing);
}
@keyframes board-charge-in { from { inline-size: 0; } }
.board-card-charging { --charge-easing: cubic-bezier(.2,.7,.25,1); }
/* 命中区域随填充边缘一起移动，卡片的按钮和整卡拖动仍可使用。 */
.board-charge-handle {
  position: absolute; z-index: 1; inset-block: 0; inset-inline-start: var(--charge); inline-size: 14px;
  translate: -50%; cursor: ew-resize; touch-action: none; -webkit-user-select: none; user-select: none;
  animation: board-charge-handle-in 650ms var(--charge-easing);
  transition: inset-inline-start 430ms var(--charge-easing);
}
.board-charge-handle:focus-visible { outline: 2px solid #123f50; outline-offset: -2px; }
.board-card-charging :is(.board-card-actions, .task-meeting-link, .task-review-info) { position: relative; z-index: 2; }
@keyframes board-charge-handle-in { from { inset-inline-start: 0; } }
.board-charge-fill.board-charge-adjusting::before, .board-charge-handle.board-charge-adjusting { transition: none; }
/* 百分比和填充层共用卡片背景，卡片高度由任务内容决定。 */
.board-charge-value {
  position: absolute;
  z-index: -1;
  inset: 0;
  display: grid;
  place-items: center;
  pointer-events: none;
  color: #174c5e94;
  font: 800 clamp(30px, 4vw, 38px)/1 'Cascadia Mono', 'Consolas', ui-monospace, monospace;
  font-variant-numeric: tabular-nums;
  letter-spacing: -.075em;
  text-shadow: 0 1px #ffffffa8;
}
@media (prefers-reduced-motion: reduce) {
  .board-charge-fill::before, .board-charge-handle { animation: none; transition: none; }
}
.board-dialog { margin: auto; }
.board-dialog::backdrop { background: #0009; }
.board-destructive { background: #ff8585; }
@media (max-width: 800px) { .board { grid-template-columns: 1fr; } }
</style>
