<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from './api'
import type { ScheduleSettings } from './types'

interface ScheduledTask extends ScheduleSettings {
  key: string
  name: string
}

const tasks = ref<ScheduledTask[]>([])
const loading = ref(true)
const saving = ref<string | null>(null)
const error = ref('')
const notice = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    tasks.value = await api<ScheduledTask[]>('/scheduled-tasks')
  } catch (cause) {
    error.value = (cause as Error).message
  } finally {
    loading.value = false
  }
}

async function save(task: ScheduledTask) {
  saving.value = task.key
  error.value = ''
  notice.value = ''
  try {
    const { enabled, interval_minutes } = task
    const saved = await api<ScheduledTask>(`/scheduled-tasks/${task.key}`, 'PUT', { enabled, interval_minutes })
    Object.assign(task, saved)
    notice.value = `${saved.name}已保存`
  } catch (cause) {
    error.value = (cause as Error).message
  } finally {
    saving.value = null
  }
}

onMounted(load)
</script>

<template>
  <p v-if="loading" class="empty" role="status">正在加载定时任务…</p>
  <p v-if="error" class="review-error" role="alert">{{ error }}</p>
  <button v-if="error && !tasks.length && !loading" class="secondary-button" type="button" @click="load">重试</button>
  <section v-for="task in tasks" :key="task.key" class="panel review-panel" :aria-label="task.name">
    <h2>{{ task.name }}</h2>
    <p v-if="task.key === 'unread-message-reminder'">用户登录并打开系统期间，定时检查消息中心的未读消息并发送提醒。</p>
    <form class="review-form" @submit.prevent="save(task)">
      <label>任务状态
        <select v-model="task.enabled" :disabled="saving !== null">
          <option :value="true">开启</option>
          <option :value="false">关闭</option>
        </select>
      </label>
      <label>执行间隔（分钟）
        <input v-model.number="task.interval_minutes" :disabled="saving !== null" type="number" min="1" max="1440" step="1" required />
      </label>
      <button class="primary-button" type="submit" :disabled="saving !== null">
        {{ saving === task.key ? '正在保存…' : '保存设置' }}
      </button>
    </form>
  </section>
  <p v-if="notice" class="message" role="status">{{ notice }}</p>
</template>
