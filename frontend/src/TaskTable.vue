<script setup lang="ts">
import { computed } from 'vue'
import type { Category, Task, TaskField } from './types'
const props = defineProps<{ tasks: Task[]; categories?: Category[]; readonly?: boolean; busy?: boolean }>()
const emit = defineEmits<{ edit: [id: number, patch: Partial<TaskField>]; duplicate: [id: number]; remove: [id: number] }>()
const statuses = ['已完成','90%','80%','70%','60%','50%','40%','30%','20%','10%','5%']
const sharedTypes = ['开发相关','联调联试','数据处理','运维相关','开会','其他']
const taskTypes = computed(() => [...sharedTypes, ...(props.categories || []).map(c => c.name).filter(name => !sharedTypes.includes(name))])
const days = ['一','二','三','四','五','六','日']
function toggle(task: Task, day: number) { emit('edit', task.id, { work_days: task.work_days.includes(day) ? task.work_days.filter(x => x !== day) : [...task.work_days, day].sort() }) }
function resize(el: HTMLTextAreaElement) { el.style.height = 'auto'; el.style.height = `${el.scrollHeight + 4}px` }
const vAutoHeight = { mounted: resize, updated: resize }
function changeText(event: Event, id: number, field: 'description' | 'notes') {
  const el = event.target as HTMLTextAreaElement
  resize(el)
  emit('edit', id, { [field]: el.value })
}
</script>
<template>
  <div v-if="tasks.length === 0" class="empty" role="status">本周还没有任务。</div>
  <div v-else class="task-list">
    <article v-for="task in tasks" :key="task.id" class="task-row">
      <span class="task-index">{{ String(task.position).padStart(2, '0') }}</span>
      <div class="task-fields">
        <label class="task-type"><span>任务类型</span><span v-if="readonly" class="read-value">{{ task.category_name || '—' }}</span><select v-else :disabled="busy" :value="task.category_name || ''" @change="emit('edit', task.id, { category_name: ($event.target as HTMLSelectElement).value || null })"><option value="">未选择</option><option v-if="task.category_name && !taskTypes.includes(task.category_name)" :value="task.category_name">{{ task.category_name }}（历史）</option><option v-for="name in taskTypes" :key="name" :value="name">{{ name }}</option></select></label>
        <label class="task-group"><span>任务大类</span><span v-if="readonly" class="read-value preline">{{ task.task_group || '—' }}</span><input v-else :disabled="busy" maxlength="200" :value="task.task_group" @input="emit('edit', task.id, { task_group: ($event.target as HTMLInputElement).value })" /></label>
        <label class="description"><span>任务描述</span><span v-if="readonly" class="read-value preline">{{ task.description || '—' }}</span><textarea v-else v-auto-height :disabled="busy" rows="2" :value="task.description" placeholder="写下这项工作…" @input="changeText($event, task.id, 'description')" /></label>
        <label class="task-status"><span>完成状态</span><span v-if="readonly" class="read-value">{{ task.status || '未开始' }}</span><select v-else :disabled="busy" :value="task.status || ''" @change="emit('edit', task.id, { status: ($event.target as HTMLSelectElement).value || null })"><option value="">未开始</option><option v-for="status in statuses" :key="status" :value="status">{{ status }}</option></select></label>
        <div class="work-days"><span>工作日期</span><div class="day-tags"><template v-for="(label, index) in days" :key="index"><span v-if="readonly" class="day-tag" :class="{ selected: task.work_days.includes(index + 1) }">{{ label }}</span><button v-else type="button" :disabled="busy" class="day-tag" :class="{ selected: task.work_days.includes(index + 1) }" :aria-label="`周${label}${task.work_days.includes(index+1) ? '已选中' : '未选中'}`" :aria-pressed="task.work_days.includes(index+1)" @click="toggle(task, index+1)">{{ label }}</button></template></div></div>
        <label class="notes"><span>备注</span><span v-if="readonly" class="read-value preline">{{ task.notes || '—' }}</span><textarea v-else :disabled="busy" rows="2" :value="task.notes" placeholder="补充说明…" @input="emit('edit', task.id, { notes: ($event.target as HTMLTextAreaElement).value })" /></label>
      </div>
      <div v-if="!readonly" class="task-actions"><button type="button" :disabled="busy" class="mini-button" @click="emit('duplicate', task.id)">复制一行</button><button type="button" :disabled="busy" class="mini-button danger" @click="emit('remove', task.id)">删除</button></div>
    </article>
  </div>
</template>
