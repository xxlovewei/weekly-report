<script setup lang="ts">
import { reactive, ref, nextTick, onMounted } from 'vue'
import { api, ApiError } from './api'
import { todayShanghai } from './dates'
import type { Meeting, MeetingTask } from './types'
const props = defineProps<{ meeting?: Meeting | null }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const form = reactive({
  meeting_date: props.meeting?.meeting_date || todayShanghai(),
  meeting_type: props.meeting?.meeting_type || '',
  content: props.meeting?.content || '',
  needs_follow_up: props.meeting?.needs_follow_up || false,
  tasks: (props.meeting?.tasks || []).map(t => ({ name: t.name, status: t.status })) as MeetingTask[],
})
const error = ref(''), saving = ref(false), first = ref<HTMLInputElement | null>(null)
onMounted(() => { void nextTick(() => first.value?.focus()) })
async function save() {
  saving.value = true; error.value = ''
  try {
    await api(props.meeting ? `/meetings/${props.meeting.id}` : '/meetings', props.meeting ? 'PUT' : 'POST', { ...form, tasks: form.needs_follow_up ? form.tasks : [] })
    emit('saved')
  } catch (cause) { error.value = cause instanceof ApiError ? cause.message : '保存失败，请重试。' }
  finally { saving.value = false }
}
</script>
<template>
  <div class="modal-scrim" @keydown.esc="emit('close')">
    <div class="modal meeting-modal" role="dialog" aria-modal="true" :aria-label="meeting ? '编辑会议记录' : '新增会议记录'">
      <span class="eyebrow">会议记录</span><h2>{{ meeting ? '编辑会议记录' : '新增会议记录' }}</h2>
      <form class="stack-form" @submit.prevent="save">
        <div class="meeting-form-row"><label>日期<input ref="first" v-model="form.meeting_date" type="date" required /></label><label>会议类型<input v-model="form.meeting_type" maxlength="100" required /></label></div>
        <label>会议内容<textarea v-model="form.content" rows="4" maxlength="10000" required /></label>
        <label>是否需要跟踪完成情况<select v-model="form.needs_follow_up"><option :value="false">否</option><option :value="true">是</option></select></label>
        <div v-if="form.needs_follow_up" class="meeting-followups"><div class="section-head"><strong>关联任务</strong><button class="mini-button" type="button" @click="form.tasks.push({ name: '', status: null })">＋ 添加任务</button></div>
          <div v-for="(task, index) in form.tasks" :key="index" class="meeting-task-edit"><strong>{{ index + 1 }}</strong><label>任务名称<input v-model="task.name" maxlength="500" required /></label><label>任务状态<select v-model="task.status"><option :value="null">未选择</option><option value="未完成">未完成</option><option value="已完成">已完成</option></select></label><button class="mini-button danger" type="button" :aria-label="`删除关联任务 ${index+1}`" @click="form.tasks.splice(index, 1)">删除</button></div>
        </div>
        <p v-if="error" class="message error" role="alert">{{ error }}</p>
        <div class="modal-actions"><button class="secondary-button" type="button" @click="emit('close')">取消</button><button class="primary-button" type="submit" :disabled="saving">{{ saving ? '保存中…' : '保存会议记录' }}</button></div>
      </form>
    </div>
  </div>
</template>
