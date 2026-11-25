<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { taskStatuses as statuses, progressStyle } from './taskStatuses'
import TaskDescription from './TaskDescription.vue'
import TaskActions from './TaskActions.vue'
import ReviewIssueDialog from './ReviewIssueDialog.vue'
import { sharedTaskTypes } from './taskTypes'
import type { Category, Task, TaskField } from './types'
const props = defineProps<{ tasks: Task[]; categories?: Category[]; readonly?: boolean; delegated?: boolean; workView?: boolean; busy?: boolean; targetTask?: number | null; plan?: boolean; allowBoardTransfer?: boolean }>()
const emit = defineEmits<{ edit: [id: number, patch: Partial<TaskField>]; duplicate: [id: number]; remove: [id: number]; reorder: [ids: number[]]; transfer: [id: number, userId: number] }>()
const actions = ref<InstanceType<typeof TaskActions> | null>(null)
const draggedId = ref<number | null>(null)
const dropTarget = ref<{ id: number; after: boolean } | null>(null)
const selectedId = ref<number | null>(null)
const openedIssue = ref<number | null>(null)
let keyboardHandle: HTMLButtonElement | null = null
watch(() => props.busy, busy => {
  if (!busy && keyboardHandle) { keyboardHandle.focus(); keyboardHandle = null }
}, { flush: 'post' })

const taskTypes = computed(() => [...sharedTaskTypes, ...(props.categories || []).map(c => c.name).filter(name => !sharedTaskTypes.includes(name))])
const days = ['一','二','三','四','五','六','日']
function toggle(task: Task, day: number) { emit('edit', task.id, { work_days: task.work_days.includes(day) ? task.work_days.filter(x => x !== day) : [...task.work_days, day].sort() }) }
function toggleSelection(id: number) { selectedId.value = selectedId.value === id ? null : id }
// 捕获阶段清除手柄外的选中状态；点击另一个手柄后仍可正常选中它。
function clearSelectionOnPageClick(event: MouseEvent) {
  if (!(event.target instanceof Element) || !event.target.closest('.task-drag-handle')) selectedId.value = null
}
onMounted(() => document.addEventListener('click', clearSelectionOnPageClick, true))
onUnmounted(() => document.removeEventListener('click', clearSelectionOnPageClick, true))
function resetDrag() { draggedId.value = null; dropTarget.value = null }
function reorder(id: number, targetId: number, after: boolean) {
  if (props.readonly || props.delegated || props.busy || id === targetId || !props.tasks.some(task => task.id === id)) return
  const ids = props.tasks.map(task => task.id).filter(taskId => taskId !== id)
  const index = ids.indexOf(targetId)
  if (index < 0) return
  ids.splice(index + Number(after), 0, id)
  if (ids.some((taskId, index) => taskId !== props.tasks[index].id)) emit('reorder', ids)
}
function startDrag(event: DragEvent, task: Task) {
  if (props.readonly || props.delegated || props.busy || !event.dataTransfer) { event.preventDefault(); return }
  // 拖动其他任务时，清除此前保留的键盘排序选中状态。
  if (selectedId.value !== null && selectedId.value !== task.id) selectedId.value = null
  draggedId.value = task.id
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('application/x-zhoubao-task', String(task.id))
  event.dataTransfer.setDragImage((event.currentTarget as HTMLElement).closest('.task-row')!, 20, 20)
}
function dragOver(event: DragEvent, task: Task) {
  if (draggedId.value === null || props.readonly || props.delegated || props.busy) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  dropTarget.value = { id: task.id, after: event.clientY > rect.top + rect.height / 2 }
}
function drop(event: DragEvent, task: Task) {
  if (draggedId.value === null) return
  dragOver(event, task)
  if (dropTarget.value) reorder(draggedId.value, task.id, dropTarget.value.after)
  resetDrag()
}
function moveWithKeyboard(event: KeyboardEvent, id: number) {
  if (selectedId.value !== id || (event.key !== 'ArrowUp' && event.key !== 'ArrowDown')) return
  event.preventDefault()
  const offset = event.key === 'ArrowUp' ? -1 : 1
  const target = props.tasks[props.tasks.findIndex(task => task.id === id) + offset]
  if (target && !props.busy && !props.readonly) {
    keyboardHandle = event.currentTarget as HTMLButtonElement
    reorder(id, target.id, offset > 0)
  }
}
function openActions(event: MouseEvent | KeyboardEvent, id: number) {
  if (props.readonly) return
  event.preventDefault()
  if (!props.busy) actions.value?.open(event, id)
}
</script>
<template>
  <div v-if="tasks.length === 0" class="empty" role="status">{{ plan ? '这周还没有任务计划。' : '本周还没有任务。' }}</div>
  <div v-else class="task-list">
    <article v-for="task in tasks" :key="task.id" :id="readonly && !workView ? undefined : `work-task-${task.id}`" class="task-row priority-edge" :data-priority="task.priority" :class="{ 'task-target': targetTask === task.id, selected: selectedId === task.id, dragging: draggedId === task.id, 'drop-before': dropTarget?.id === task.id && !dropTarget.after && draggedId !== task.id, 'drop-after': dropTarget?.id === task.id && dropTarget.after && draggedId !== task.id }" @dragover="dragOver($event, task)" @drop="drop($event, task)" @contextmenu="openActions($event, task.id)" @keydown.shift.f10="openActions($event, task.id)" @keydown.context-menu="openActions($event, task.id)">
      <div class="task-leading">
        <button v-if="!readonly && !delegated" type="button" class="task-drag-handle" :disabled="busy" :draggable="!busy" :aria-pressed="selectedId === task.id" :aria-label="`${selectedId === task.id ? '取消选中' : '选中'}任务 ${task.position}，使用上下方向键调整顺序`" title="点击选中或取消选中；选中后按上下方向键调整顺序，也可拖动" @click="toggleSelection(task.id)" @dragstart="startDrag($event, task)" @dragend="resetDrag" @keydown="moveWithKeyboard($event, task.id)"><svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 2v14M2 9h14M6 5l3-3 3 3M6 13l3 3 3-3M5 6 2 9l3 3M13 6l3 3-3 3" /></svg></button>
        <span class="task-index" :aria-label="task.priority ? `任务 ${task.position}，优先级${task.priority}` : undefined">{{ String(task.position).padStart(2, '0') }}</span>
        <button v-if="!readonly && task.review_issue_id" class="task-review-info" type="button" aria-haspopup="dialog"
          title="点击可查看审查记录的内容" aria-label="点击可查看审查记录的内容" @click="openedIssue = task.review_issue_id">
          <span aria-hidden="true">i</span>
        </button>
        <RouterLink v-if="(!readonly || workView) && task.meeting_id && task.meeting_date" class="task-transfer-mark task-meeting-link"
          :to="{ name: 'meetings', query: { meeting: task.meeting_id } }"
          :title="`${task.meeting_date}会议指派，点击可跳转会议记录`"
          :aria-label="`${task.meeting_date}会议指派，点击可跳转会议记录`"><span aria-hidden="true">💡</span></RouterLink>
        <span v-if="task.transferred_by" class="task-transfer-mark" role="img" :aria-label="`由${task.transferred_by}转交的任务`" :title="`由${task.transferred_by}转交的任务`">💡</span>
      </div>
      <div class="task-fields">
        <label class="task-type"><span>任务类型</span><span v-if="readonly" class="read-value">{{ task.category_name || '—' }}</span><select v-else :disabled="busy" :value="task.category_name || ''" @change="emit('edit', task.id, { category_name: ($event.target as HTMLSelectElement).value || null })"><option value="">未选择</option><option v-if="task.category_name && !taskTypes.includes(task.category_name)" :value="task.category_name">{{ task.category_name }}（历史）</option><option v-for="name in taskTypes" :key="name" :value="name">{{ name }}</option></select></label>
        <label v-if="readonly" class="task-group"><span>任务名称</span><span class="read-value preline">{{ task.task_group || '—' }}</span></label>
        <TaskDescription v-else class="task-group" plain label="任务名称" placeholder="" :rows="1" :max-length="Math.max(200, task.task_group.length)" :model-value="task.task_group" :disabled="busy || task.name_locked" :title="task.name_locked ? '多人会议任务的名称请在会议记录中修改' : undefined" @update:model-value="emit('edit', task.id, { task_group: $event })" />
        <div class="description"><label v-if="readonly"><span>本周任务进展</span><span class="read-value preline">{{ task.description || '—' }}</span></label><TaskDescription v-else :model-value="task.description" :disabled="busy" @update:model-value="emit('edit', task.id, { description: $event })" /></div>
        <label class="task-status"><span>完成状态</span><span v-if="readonly" class="read-value"><span class="status-tag" :class="{ completed: task.status === '已完成', pending: !task.status }" :style="progressStyle(task.status)">{{ task.status || '未开始' }}</span></span><select v-else :disabled="busy" :value="task.status || ''" @change="emit('edit', task.id, { status: ($event.target as HTMLSelectElement).value || null })"><option value="">未开始</option><option v-if="task.status === '忽略'" value="忽略" disabled>忽略</option><option v-for="status in statuses" :key="status" :value="status">{{ status }}</option></select></label>
        <div class="work-days"><span>工作日期</span><div class="day-tags" :class="{ readonly }"><template v-for="(label, index) in days" :key="index"><span v-if="readonly" class="day-tag" :class="{ selected: task.work_days.includes(index + 1) }">{{ label }}</span><button v-else type="button" :disabled="busy" class="day-tag" :class="{ selected: task.work_days.includes(index + 1) }" :aria-label="`周${label}${task.work_days.includes(index+1) ? '已选中' : '未选中'}`" :aria-pressed="task.work_days.includes(index+1)" @click="toggle(task, index+1)">{{ label }}</button></template></div></div>
        <label v-if="readonly" class="notes"><span>备注</span><span class="read-value preline">{{ task.notes || '—' }}</span></label><TaskDescription v-else class="notes" label="备注" placeholder="补充说明…" :disabled="busy" :model-value="task.notes" @update:model-value="emit('edit', task.id, { notes: $event })" />
      </div>
      <div v-if="!readonly" class="task-actions"><button v-if="!delegated && !plan" type="button" :disabled="busy" class="mini-button" @click="emit('duplicate', task.id)">复制一行</button><button type="button" :disabled="busy || !!task.meeting_task_id" :title="task.meeting_task_id ? '会议指派任务，请在会议记录中取消指派' : undefined" class="mini-button danger" @click="emit('remove', task.id)">删除</button></div>
    </article>
  </div>
  <TaskActions v-if="!readonly" ref="actions" :tasks="tasks" :busy="busy" :delegated="delegated" :plan="plan" :allow-board-transfer="allowBoardTransfer" @move="reorder" @priority="(id, priority) => emit('edit', id, { priority })" @transfer="(id, userId) => emit('transfer', id, userId)" />
  <ReviewIssueDialog v-if="openedIssue !== null" :issue-id="openedIssue" @close="openedIssue = null" />
</template>
