<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import TaskDescription from './TaskDescription.vue'
import type { Category, Task, TaskField } from './types'
const props = defineProps<{ tasks: Task[]; categories?: Category[]; readonly?: boolean; busy?: boolean }>()
const emit = defineEmits<{ edit: [id: number, patch: Partial<TaskField>]; duplicate: [id: number]; remove: [id: number]; reorder: [ids: number[]] }>()
const draggedId = ref<number | null>(null)
const dropTarget = ref<{ id: number; after: boolean } | null>(null)
const selectedId = ref<number | null>(null)
let keyboardHandle: HTMLButtonElement | null = null
watch(() => props.busy, busy => {
  if (!busy && keyboardHandle) { keyboardHandle.focus(); keyboardHandle = null }
}, { flush: 'post' })
const statuses = ['已完成','90%','80%','70%','60%','50%','40%','30%','20%','10%','5%']
function progressStyle(status: string | null) {
  if (!status || !/^\d+%$/.test(status)) return
  const progress = Math.min(100, Number.parseInt(status))
  // 进度越高蓝色越深；深色背景使用白字，确保状态仍易读。
  return { backgroundColor: `hsl(210 85% ${90 - progress * 0.55}%)`, color: progress >= 80 ? '#fff' : '#000' }
}
const sharedTypes = ['开发相关','联调联试','数据处理','运维相关','开会','其他']
const taskTypes = computed(() => [...sharedTypes, ...(props.categories || []).map(c => c.name).filter(name => !sharedTypes.includes(name))])
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
  if (props.readonly || props.busy || id === targetId || !props.tasks.some(task => task.id === id)) return
  const ids = props.tasks.map(task => task.id).filter(taskId => taskId !== id)
  const index = ids.indexOf(targetId)
  if (index < 0) return
  ids.splice(index + Number(after), 0, id)
  if (ids.some((taskId, index) => taskId !== props.tasks[index].id)) emit('reorder', ids)
}
function startDrag(event: DragEvent, task: Task) {
  if (props.readonly || props.busy || !event.dataTransfer) { event.preventDefault(); return }
  // 拖动其他任务时，清除此前保留的键盘排序选中状态。
  if (selectedId.value !== null && selectedId.value !== task.id) selectedId.value = null
  draggedId.value = task.id
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('application/x-zhoubao-task', String(task.id))
  event.dataTransfer.setDragImage((event.currentTarget as HTMLElement).closest('.task-row')!, 20, 20)
}
function dragOver(event: DragEvent, task: Task) {
  if (draggedId.value === null || props.readonly || props.busy) return
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
</script>
<template>
  <div v-if="tasks.length === 0" class="empty" role="status">本周还没有任务。</div>
  <div v-else class="task-list">
    <article v-for="task in tasks" :key="task.id" class="task-row" :class="{ selected: selectedId === task.id, dragging: draggedId === task.id, 'drop-before': dropTarget?.id === task.id && !dropTarget.after && draggedId !== task.id, 'drop-after': dropTarget?.id === task.id && dropTarget.after && draggedId !== task.id }" @dragover="dragOver($event, task)" @drop="drop($event, task)">
      <div class="task-leading"><button v-if="!readonly" type="button" class="task-drag-handle" :disabled="busy" :draggable="!busy" :aria-pressed="selectedId === task.id" :aria-label="`${selectedId === task.id ? '取消选中' : '选中'}任务 ${task.position}，使用上下方向键调整顺序`" title="点击选中或取消选中；选中后按上下方向键调整顺序，也可拖动" @click="toggleSelection(task.id)" @dragstart="startDrag($event, task)" @dragend="resetDrag" @keydown="moveWithKeyboard($event, task.id)"><svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 2v14M2 9h14M6 5l3-3 3 3M6 13l3 3 3-3M5 6 2 9l3 3M13 6l3 3-3 3" /></svg></button><span class="task-index">{{ String(task.position).padStart(2, '0') }}</span></div>
      <div class="task-fields">
        <label class="task-type"><span>任务类型</span><span v-if="readonly" class="read-value">{{ task.category_name || '—' }}</span><select v-else :disabled="busy" :value="task.category_name || ''" @change="emit('edit', task.id, { category_name: ($event.target as HTMLSelectElement).value || null })"><option value="">未选择</option><option v-if="task.category_name && !taskTypes.includes(task.category_name)" :value="task.category_name">{{ task.category_name }}（历史）</option><option v-for="name in taskTypes" :key="name" :value="name">{{ name }}</option></select></label>
        <label class="task-group"><span>任务大类</span><span v-if="readonly" class="read-value preline">{{ task.task_group || '—' }}</span><input v-else :disabled="busy" maxlength="200" :value="task.task_group" @input="emit('edit', task.id, { task_group: ($event.target as HTMLInputElement).value })" /></label>
        <div class="description"><label v-if="readonly"><span>任务描述</span><span class="read-value preline">{{ task.description || '—' }}</span></label><TaskDescription v-else :model-value="task.description" :disabled="busy" @update:model-value="emit('edit', task.id, { description: $event })" /></div>
        <label class="task-status"><span>完成状态</span><span v-if="readonly" class="read-value"><span class="status-tag" :class="{ completed: task.status === '已完成', pending: !task.status }" :style="progressStyle(task.status)">{{ task.status || '未开始' }}</span></span><select v-else :disabled="busy" :value="task.status || ''" @change="emit('edit', task.id, { status: ($event.target as HTMLSelectElement).value || null })"><option value="">未开始</option><option v-for="status in statuses" :key="status" :value="status">{{ status }}</option></select></label>
        <div class="work-days"><span>工作日期</span><div class="day-tags"><template v-for="(label, index) in days" :key="index"><span v-if="readonly" class="day-tag" :class="{ selected: task.work_days.includes(index + 1) }">{{ label }}</span><button v-else type="button" :disabled="busy" class="day-tag" :class="{ selected: task.work_days.includes(index + 1) }" :aria-label="`周${label}${task.work_days.includes(index+1) ? '已选中' : '未选中'}`" :aria-pressed="task.work_days.includes(index+1)" @click="toggle(task, index+1)">{{ label }}</button></template></div></div>
        <label class="notes"><span>备注</span><span v-if="readonly" class="read-value preline">{{ task.notes || '—' }}</span><textarea v-else :disabled="busy" rows="2" :value="task.notes" placeholder="补充说明…" @input="emit('edit', task.id, { notes: ($event.target as HTMLTextAreaElement).value })" /></label>
      </div>
      <div v-if="!readonly" class="task-actions"><button type="button" :disabled="busy" class="mini-button" @click="emit('duplicate', task.id)">复制一行</button><button type="button" :disabled="busy" class="mini-button danger" @click="emit('remove', task.id)">删除</button></div>
    </article>
  </div>
</template>
