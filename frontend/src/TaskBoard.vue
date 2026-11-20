<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { api, ApiError, newIdempotencyKey } from './api'
import ReviewIssueDialog from './ReviewIssueDialog.vue'
import { sharedTaskTypes } from './taskTypes'
import type { Category, TaskPriority, WeekData } from './types'

const columns = [
  { state: 'inbox', name: '任务箱' },
  { state: 'in_progress', name: '进行中' },
  { state: 'done', name: '已完成' },
] as const
type State = typeof columns[number]['state']
interface CardFields { name: string; category_name: string; priority: TaskPriority }
interface Card extends CardFields {
  id: number
  state: State
  status: string | null
  revision: number
  position: number
  has_current_detail: boolean
  has_other_details: boolean
  meeting_id?: number | null
  review_issue_id?: number | null
  transferred_by?: string | null
  name_locked?: boolean
}
type Dialog = { kind: 'edit'; card?: Card } | { kind: 'remove' | 'return'; card: Card }
const props = defineProps<{ targetTask?: number | null; targetRefresh?: number }>()

const cards = ref<Card[]>([])
const categories = ref<Category[]>([])
const weekStart = ref('')
const loading = ref(true), busy = ref(false), error = ref('')
const continuationNotice = ref('')
const dragged = ref<number | null>(null), hovered = ref<State | null>(null)
const dropBefore = ref<number | null>(null)
const dialog = ref<HTMLDialogElement | null>(null), action = ref<Dialog | null>(null)
const form = reactive<CardFields>({ name: '', category_name: '', priority: '低' })
const formError = ref('')
const openedIssue = ref<number | null>(null)
let createRequest: { body: string; key: string } | null = null
let copyRequest: { cardId: number; key: string } | null = null
const options = computed(() => [...new Set([...sharedTaskTypes, ...categories.value.map(category => category.name)])])
const grouped = computed(() => columns.map(column => ({
  ...column, cards: cards.value.filter(card => card.state === column.state)
    .sort((left, right) => left.position - right.position || left.id - right.id),
})))
const canContinue = computed(() => cards.value.some(card => card.state === 'in_progress' && !card.has_current_detail))

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
  const board = await api<{ current_week: string; tasks: Card[] }>('/board-tasks')
  cards.value = board.tasks
  weekStart.value = board.current_week
}
onMounted(load)
watch(() => [loading.value, props.targetTask, props.targetRefresh], () => {
  if (loading.value || !props.targetTask) return
  const card = document.getElementById(`board-task-${props.targetTask}`)
  if (!card) return
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  card.focus({ preventScroll: true })
  card.scrollIntoView({ block: 'center', behavior: reducedMotion ? 'instant' : 'smooth' })
  if (!reducedMotion) card.animate([
    { backgroundColor: '#fff' }, { backgroundColor: '#f2ffac' }, { backgroundColor: '#fff' },
  ], { duration: 800, iterations: 3 })
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
  busy.value = true
  error.value = ''
  formError.value = ''
  continuationNotice.value = ''
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
    continuationNotice.value = result.no_source ? '进行中的任务均已加入本周工作。' : '已将进行中的任务加入本周工作。'
    await refreshBoard()
  })
}
function open(nextAction: Dialog) {
  action.value = nextAction
  formError.value = ''
  if (nextAction.kind === 'edit') {
    const card = nextAction.card
    Object.assign(form, { name: card?.name ?? '', category_name: card?.category_name ?? '', priority: card?.priority ?? '低' })
    createRequest = null
  }
  void nextTick(() => dialog.value?.showModal())
}
async function submit() {
  const pending = action.value
  if (!pending) return
  await perform(async () => {
    if (pending.kind === 'edit') {
      const fields = { ...form, name: form.name.trim() }
      if (!fields.name && !pending.card?.name_locked) { throw new ApiError(422, '请输入任务名称。') }
      if (pending.card) {
        saveCard(await api<Card>(path(pending.card), 'PATCH', fields))
      } else {
        const body = JSON.stringify(fields)
        if (createRequest?.body !== body) createRequest = { body, key: newIdempotencyKey() }
        saveCard(await api<Card>('/board-tasks', 'POST', fields, createRequest.key))
      }
    } else if (pending.kind === 'remove') {
      await api(path(pending.card), 'DELETE')
      cards.value = cards.value.filter(card => card.id !== pending.card.id)
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
  if (busy.value || state === card.state) return
  if (state === 'inbox' && card.has_current_detail) open({ kind: 'return', card })
  else void perform(() => move(card, state))
}
function startDrag(event: DragEvent, card: Card) {
  if (busy.value || !event.dataTransfer) { event.preventDefault(); return }
  dragged.value = card.id
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('application/x-zhoubao-board-card', String(card.id))
}
function resetDrag() { dragged.value = null; hovered.value = null; dropBefore.value = null }
function beforeCardAtPointer(event: DragEvent, cardId: number) {
  const column = event.currentTarget as HTMLElement
  // 用卡片中线区分插入该卡片之前或之后，拖动中的卡片不参与比较。
  for (const element of Array.from(column.querySelectorAll<HTMLElement>('[data-card-id]'))) {
    const id = Number(element.dataset.cardId)
    if (id === cardId) continue
    const rect = element.getBoundingClientRect()
    if (event.clientY < rect.top + rect.height / 2) return id
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
  dropBefore.value = card?.state === state ? beforeCardAtPointer(event, card.id) : null
}
function drop(event: DragEvent, state: State) {
  event.preventDefault()
  const card = cards.value.find(item => item.id === dragged.value)
  const beforeId = card?.state === state ? beforeCardAtPointer(event, card.id) : null
  resetDrag()
  if (!card) return
  if (card.state === state) void perform(() => reorder(card, beforeId))
  else requestMove(card, state)
}
</script>

<template>
  <p v-if="loading" role="status">正在加载任务看板…</p>
  <div v-if="error" class="message error board-error" role="alert">
    {{ error }} <button type="button" class="mini-button" @click="load">重新载入</button>
  </div>
  <p v-if="continuationNotice" class="message board-notice" role="status">{{ continuationNotice }}</p>
  <div v-if="!loading && weekStart" class="board">
    <section v-for="column in grouped" :key="column.state" class="board-column panel"
      :class="{ 'board-drop-target': hovered === column.state }" :aria-label="column.name"
      @dragover="dragOver($event, column.state)" @drop="drop($event, column.state)">
      <header class="board-heading">
        <h2>{{ column.name }}</h2>
        <button v-if="column.state === 'inbox'" type="button" class="primary-button"
          :disabled="busy" @click="open({ kind: 'edit' })">＋ 添加任务</button>
        <button v-else-if="column.state === 'in_progress'" type="button" class="secondary-button"
          :disabled="busy || !canContinue" @click="continueThisWeek">继续本周工作</button>
      </header>
      <div class="board-card-list">
        <p v-if="!column.cards.length" class="board-empty">暂无任务</p>
        <article v-for="card in column.cards" :key="card.id" :id="`board-task-${card.id}`" class="board-card priority-edge" :data-priority="card.priority"
          tabindex="-1" :data-card-id="card.id" :class="{ 'board-drop-before': dropBefore === card.id, 'board-target': targetTask === card.id, 'board-card-charging': card.state === 'in_progress' }"
          :aria-label="`${card.name || '未命名任务'}，优先级${card.priority}`" :draggable="!busy"
          @dragstart="startDrag($event, card)" @dragend="resetDrag">
          <div v-if="card.state === 'in_progress'" class="board-charge-fill" aria-hidden="true" :style="{ '--charge': card.status || '5%' }" />
          <div class="board-card-content">
            <div class="board-card-title">
              <RouterLink v-if="card.meeting_id" class="task-transfer-mark task-meeting-link"
                :to="{ name: 'meetings', query: { meeting: card.meeting_id } }" title="会议指派，点击可跳转会议记录" aria-label="查看指派会议">💡</RouterLink>
              <span v-if="card.transferred_by" class="task-transfer-mark" role="img"
                :aria-label="`由${card.transferred_by}转交的任务`" :title="`由${card.transferred_by}转交的任务`">💡</span>
              <button v-if="card.review_issue_id" class="task-review-info" type="button" aria-haspopup="dialog"
                title="点击可查看审查记录的内容" aria-label="点击可查看审查记录的内容" @click="openedIssue = card.review_issue_id">
                <span aria-hidden="true">i</span>
              </button>
              <strong>{{ card.name || '未命名任务' }}</strong>
            </div>
          </div>
          <div class="board-card-actions">
            <button type="button" class="icon-btn" aria-label="复制任务" :disabled="busy || card.has_other_details"
              :title="card.has_other_details ? '已关联其他周的任务明细' : '复制任务'" @click="duplicate(card)">
              <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="1"/><path d="M16 8V4H4v12h4"/></svg>
            </button>
            <button type="button" class="icon-btn" aria-label="修改任务" :disabled="busy || card.has_other_details"
              :title="card.has_other_details ? '已关联其他周的任务明细' : '修改任务'" @click="open({ kind: 'edit', card })">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m4 20 4-1 12-12-3-3L5 16zM14 7l3 3"/></svg>
            </button>
            <button type="button" class="icon-btn danger" aria-label="删除任务" :disabled="busy || card.has_other_details || !!card.meeting_id"
              :title="card.meeting_id ? '会议指派任务，请在会议记录中取消指派' : card.has_other_details ? '已关联其他周的任务明细' : '删除任务'" @click="open({ kind: 'remove', card })">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M9 6V3h6v3M6 6l1 14h10l1-14M10 10v6m4-6v6"/></svg>
            </button>
          </div>
          <span v-if="card.state === 'in_progress'" class="board-charge-value" role="meter" aria-label="完成状态"
            aria-valuemin="0" aria-valuemax="100" :aria-valuenow="Number.parseInt(card.status || '5%', 10)">{{ card.status || '5%' }}</span>
        </article>
      </div>
    </section>
  </div>
  <ReviewIssueDialog v-if="openedIssue !== null" :issue-id="openedIssue" @close="openedIssue = null" />

  <dialog ref="dialog" class="modal board-dialog" aria-labelledby="board-dialog-title" @close="action = null" @cancel="busy && $event.preventDefault()">
    <form v-if="action" class="stack-form" @submit.prevent="submit">
      <h2 id="board-dialog-title">{{ action.kind === 'edit' ? (action.card ? '修改任务' : '添加任务') : action.kind === 'remove' ? '删除任务' : '移回任务箱' }}</h2>
      <template v-if="action.kind === 'edit'">
        <label>任务类型<select v-model="form.category_name" :required="!!form.category_name || action.card?.category_name !== ''" :disabled="busy">
          <option value="" disabled>{{ action.card?.category_name === '' ? '未选择' : '请选择任务类型' }}</option>
          <option v-if="form.category_name && !options.includes(form.category_name)" :value="form.category_name">{{ form.category_name }}（历史）</option>
          <option v-for="name in options" :key="name" :value="name">{{ name }}</option>
        </select></label>
        <label>任务名称<input v-model="form.name" maxlength="200" required :disabled="busy || action.card?.name_locked" /></label>
        <label>优先级<select v-model="form.priority" :disabled="busy">
          <option value="高">高</option><option value="中">中</option><option value="低">低</option>
        </select></label>
      </template>
      <p v-else-if="action.kind === 'return'">移回「{{ action.card.name }}」将删除它关联的本周任务明细。确认移回？</p>
      <p v-else>确认删除「{{ action.card.name }}」？<template v-if="action.card.has_current_detail"> 此操作也会删除它关联的本周任务明细。</template></p>
      <p v-if="formError" class="message error" role="alert">{{ formError }}</p>
      <div class="modal-actions">
        <button type="button" class="secondary-button" :disabled="busy" @click="dialog?.close()">取消</button>
        <button type="submit" class="primary-button" :class="{ 'board-destructive': action.kind !== 'edit' }" :disabled="busy">
          {{ action.kind === 'edit' ? '保存' : action.kind === 'return' ? '确认移回' : '确认删除' }}
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
.board-card-list {
  display: grid; align-content: start; gap: 12px; min-height: 0; overflow-y: auto;
  margin: -4px; padding: 4px;
}
.board-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-height: 44px; flex-wrap: wrap; }
.board-heading h2, .board-empty { margin: 0; }
.board-empty { padding: 14px 0; color: #555; }
.board-drop-target { outline: 3px solid #75a60a; outline-offset: -5px; }
.board-card.board-drop-before { outline: 2px solid #75a60a; outline-offset: 2px; }
.board-card.board-target { outline: 2px solid #2781b8; outline-offset: 2px; }
.board-card { background: #fff; border: 1px solid #222; border-left: 4px solid var(--priority-glow); box-shadow: var(--priority-edge-shadow); padding: 10px 8px 10px 12px; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; cursor: grab; }
.board-card-content { display: grid; gap: 6px; justify-items: start; min-width: 0; overflow-wrap: anywhere; }
.board-card-title { display: flex; align-items: center; gap: 4px; min-width: 0; }
.board-card-title > :not(strong) { flex: none; }
.board-card-title .task-review-info { width: 18px; height: 18px; }
.board-card-content strong { white-space: pre-wrap; }
.board-card-actions { display: flex; margin-left: auto; align-items: center; gap: 4px; flex-wrap: wrap; }
.board-card-actions svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 1.7; }
.board-notice { margin: 0 0 8px; }
.board-card-charging {
  position: relative;
  isolation: isolate;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: start;
  margin-inline-end: 5px;
  padding-block-end: 20px;
  border-radius: 8px;
  color: #112d3e;
  background: #eaf1f6;
}
.board-card-charging::after {
  content: '';
  position: absolute;
  inset-inline-end: -6px;
  inset-block-start: 50%;
  translate: 0 -50%;
  inline-size: 5px;
  block-size: 23px;
  border-radius: 0 3px 3px 0;
  background: #426675;
  pointer-events: none;
}
.board-card-charging .icon-btn { padding-inline: 5px; }
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
  animation: board-charge-in 650ms cubic-bezier(.2,.7,.25,1);
  transition: inline-size 430ms cubic-bezier(.2,.7,.25,1);
}
@keyframes board-charge-in { from { inline-size: 0; } }
.board-charge-value {
  grid-column: 1 / -1;
  justify-self: center;
  translate: 0 -6px;
  color: #174c5e;
  font: 800 clamp(30px, 4vw, 42px)/1 'Cascadia Mono', 'Consolas', ui-monospace, monospace;
  font-variant-numeric: tabular-nums;
  letter-spacing: -.075em;
  text-shadow: 0 1px #ffffffa8;
}
@media (prefers-reduced-motion: reduce) {
  .board-charge-fill::before { animation: none; transition: none; }
}
.board-dialog { margin: auto; }
.board-dialog::backdrop { background: #0009; }
.board-destructive { background: #ff8585; }
@media (max-width: 800px) { .board { grid-template-columns: 1fr; } }
</style>
