<script setup lang="ts">
import { reactive, ref, nextTick, onMounted, onUnmounted } from 'vue'
import AssigneeSelect from './AssigneeSelect.vue'
import { taskStatuses } from './taskStatuses'
import { api, ApiError } from './api'
import { todayShanghai } from './dates'
import type { Meeting, MeetingTask, MeetingPerson } from './types'
const props = defineProps<{ meeting?: Meeting | null }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const meetingId = ref(props.meeting?.id ?? null)
const people = ref<MeetingPerson[]>([])
const peopleLoading = ref(true)
const form = reactive({
  revision: props.meeting?.revision,
  meeting_date: props.meeting?.meeting_date || todayShanghai(),
  meeting_type: props.meeting?.meeting_type || '周会',
  content: props.meeting?.content || '',
  needs_follow_up: props.meeting?.needs_follow_up || false,
  tasks: (props.meeting?.tasks || []).map(t => ({ id: t.id, name: t.name, status: t.status, assignments: (t.assignments || []).map(a => ({ ...a })) })) as MeetingTask[],
})
const error = ref(''), success = ref(false), saving = ref(false), first = ref<HTMLInputElement | null>(null)
let successTimer: ReturnType<typeof setTimeout> | undefined
onMounted(async () => {
  void nextTick(() => first.value?.focus())
  try { people.value = await api<MeetingPerson[]>('/meeting-assignees') }
  catch (cause) { error.value = cause instanceof ApiError ? cause.message : '人员加载失败，请重新打开。' }
  finally { peopleLoading.value = false }
})
function togglePerson(task: MeetingTask, person: MeetingPerson) {
  const assigned = task.assignments || (task.assignments = [])
  const index = assigned.findIndex(a => a.user_id === person.id)
  if (index >= 0) assigned.splice(index, 1)
  else assigned.push({ user_id: person.id, status: task.status, person })
}
function personName(task: MeetingTask, id: number) {
  const person = people.value.find(p => p.id === id) || task.assignments?.find(a => a.user_id === id)?.person
  return person?.display_name || `用户 ${id}`
}
onUnmounted(() => clearTimeout(successTimer))
async function save() {
  saving.value = true; error.value = ''; success.value = false
  try {
    const saved = await api<Meeting>(meetingId.value ? `/meetings/${meetingId.value}` : '/meetings', meetingId.value ? 'PUT' : 'POST', { ...form, tasks: form.needs_follow_up ? form.tasks.map(t => ({ id: t.id, name: t.name, status: t.status, assignments: (t.assignments || []).map(a => ({ user_id: a.user_id, status: a.status })) })) : [] })
    meetingId.value = saved.id
    form.revision = saved.revision
    form.tasks = saved.tasks
    success.value = true
    clearTimeout(successTimer)
    successTimer = setTimeout(() => { success.value = false }, 3000)
    emit('saved')
  } catch (cause) { error.value = cause instanceof ApiError ? cause.message : '保存失败，请重试。' }
  finally { saving.value = false }
}
</script>
<template>
  <div class="modal-scrim" @keydown.esc="emit('close')">
    <div class="modal meeting-modal" role="dialog" aria-modal="true" :aria-label="meeting ? '编辑会议记录' : '新增会议记录'">
      <div class="meeting-modal-head"><div><span class="eyebrow">会议记录</span><h2>{{ meeting ? '编辑会议记录' : '新增会议记录' }}</h2></div><button class="icon-btn" type="button" aria-label="关闭" @click="emit('close')">×</button></div>
      <form class="stack-form" @submit.prevent="save">
        <div class="meeting-form-row"><label>日期<input ref="first" v-model="form.meeting_date" type="date" required /></label><label>会议类型<input v-model="form.meeting_type" maxlength="100" required /></label></div>
        <label>会议内容<textarea v-model="form.content" rows="4" maxlength="10000" required /></label>
        <label>是否需要跟踪完成情况<select v-model="form.needs_follow_up"><option :value="false">否</option><option :value="true">是</option></select></label>
        <div v-if="form.needs_follow_up" class="meeting-followups"><div class="section-head"><strong>关联任务</strong><button class="mini-button" type="button" @click="form.tasks.push({ name: '', status: null, assignments: [] })">＋ 添加任务</button></div>
          <div v-for="(task, index) in form.tasks" :key="index" class="meeting-task-edit">
            <strong>{{ index + 1 }}</strong>
            <label class="meeting-task-description"><span class="meeting-task-field-title">任务描述</span><textarea v-model="task.name" maxlength="5000" rows="3" /></label>
            <div class="meeting-task-field meeting-assignees">
              <span class="meeting-task-field-title">指派人员</span>
              <AssigneeSelect :people="people" :selected="(task.assignments || []).map(a => a.user_id)" :loading="peopleLoading" :label="`任务 ${index + 1} 指派人员`" @toggle="togglePerson(task, $event)" />
            </div>
            <div class="meeting-task-field meeting-task-completion">
              <span class="meeting-task-field-title">完成状态</span>
              <select v-if="!task.assignments?.length" v-model="task.status" class="meeting-completion-select" :aria-label="`任务 ${index + 1} 完成状态`"><option :value="null">未开始</option><option v-for="status in taskStatuses" :key="status" :value="status">{{ status }}</option></select>
              <div v-else class="assignment-statuses">
                <label v-for="assignment in task.assignments" :key="assignment.user_id" class="assignment-status">
                  <span>{{ personName(task, assignment.user_id) }}</span>
                  <select v-model="assignment.status" class="meeting-completion-select" :aria-label="`${personName(task, assignment.user_id)}的完成状态`"><option :value="null">未开始</option><option v-for="status in taskStatuses" :key="status" :value="status">{{ status }}</option></select>
                  <button v-if="!people.some(p => p.id === assignment.user_id)" type="button" class="mini-button" @click="task.assignments = task.assignments.filter(a => a.user_id !== assignment.user_id)">取消指派</button>
                </label>
              </div>
            </div>
            <button class="mini-button danger" type="button" :aria-label="`删除关联任务 ${index+1}`" @click="form.tasks.splice(index, 1)">删除</button>
          </div>
        </div>
        <p v-if="error" class="message error" role="alert">{{ error }}</p>
        <p v-if="success" class="message" role="status">会议记录已保存。</p>
        <div class="modal-actions"><button class="secondary-button" type="button" @click="emit('close')">关闭</button><button class="primary-button" type="submit" :disabled="saving || peopleLoading">{{ saving ? '保存中…' : '保存' }}</button></div>
      </form>
    </div>
  </div>
</template>
