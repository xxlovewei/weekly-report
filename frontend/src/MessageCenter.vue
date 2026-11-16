<script setup lang="ts">
import { ref, watch } from 'vue'
import { api } from './api'
import type { LiveMessage } from './types'

const props = defineProps<{
  admin: boolean; jumpToMessage: (item: LiveMessage) => Promise<void>; refreshKey: number
}>()
const emit = defineEmits<{ change: [] }>()
interface Message extends LiveMessage {
  title: string; created_at: string; recipient?: string
}
const items = ref<Message[]>([]), total = ref(0), page = ref(1)
// 进入消息中心时优先显示待处理的未读消息。
const allUsers = ref(false), day = ref(''), status = ref('false'), kind = ref('')
const loading = ref(false), busy = ref<number | null>(null), error = ref('')
const timestamp = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', dateStyle: 'medium', timeStyle: 'short' })
let serial = 0
async function load(background = false) {
  const current = ++serial
  const query = new URLSearchParams({ all_users: String(allUsers.value), page: String(page.value) })
  if (day.value) query.set('day', day.value)
  if (status.value) query.set('is_read', status.value)
  if (kind.value) query.set('kind', kind.value)
  if (!background) loading.value = true
  error.value = ''
  try {
    const result = await api<{ items: Message[]; total: number }>(`/notifications?${query}`)
    if (current !== serial) return
    if (!result.items.length && page.value > 1) { page.value--; return }
    items.value = result.items; total.value = result.total
  } catch (cause) { if (current === serial) error.value = (cause as Error).message }
  finally { if (current === serial) loading.value = false }
}
watch([allUsers, day, status, kind], () => { if (page.value === 1) void load(); else page.value = 1 })
watch(page, () => void load(), { immediate: true })
watch(() => props.refreshKey, () => void load(true))
async function mark(item: Message) {
  busy.value = item.id; error.value = ''
  try {
    await api(`/notifications/${item.id}`, 'PATCH', { is_read: !item.is_read })
    emit('change')
    await load()
  } catch (cause) { error.value = (cause as Error).message }
  finally { busy.value = null }
}
async function jump(item: Message) {
  busy.value = item.id; error.value = ''
  try { await props.jumpToMessage(item) }
  catch (cause) { error.value = (cause as Error).message }
  finally { busy.value = null }
}
</script>

<template>
  <section class="panel review-panel review-form" aria-label="消息筛选">
    <label v-if="admin">查看范围<select v-model="allUsers"><option :value="false">我的消息</option><option :value="true">所有人员</option></select></label>
    <label>日期<input v-model="day" type="date" /></label>
    <label>状态<select v-model="status"><option value="">全部</option><option value="false">未读</option><option value="true">已读</option></select></label>
    <label>类型<select v-model="kind"><option value="">全部</option><option>转交任务</option><option>代码审查</option></select></label>
  </section>
  <p v-if="error" class="review-error" role="alert">{{ error }}</p>
  <p v-if="loading" class="empty" role="status">正在加载消息…</p>
  <p v-else-if="!items.length" class="empty">没有符合条件的消息</p>
  <template v-else>
    <article v-for="item in items" :key="item.id" class="panel review-panel message-row">
      <div>
        <div class="review-tags">
          <time :datetime="item.created_at">{{ timestamp.format(new Date(item.created_at)) }}</time>
          <span class="status-tag message-tag message-kind">{{ item.kind }}</span>
          <span class="status-tag message-tag" :class="{ 'message-unread': !item.is_read }">{{ item.is_read ? '已读' : '未读' }}</span>
          <span v-if="allUsers">接收人 {{ item.recipient }}</span>
        </div>
        <strong>{{ item.title }}</strong>
      </div>
      <div v-if="!allUsers" class="top-actions"><button v-if="item.target" class="mini-button" :disabled="busy !== null" @click="jump(item)">跳转</button><button class="mini-button" :disabled="busy !== null" @click="mark(item)">{{ item.is_read ? '标为未读' : '标为已读' }}</button></div>
    </article>
    <div class="meeting-pagination"><span>共 {{ total }} 条 · 第 {{ page }} 页</span><button class="mini-button" :disabled="page === 1" @click="page--">上一页</button><button class="mini-button" :disabled="page * 20 >= total" @click="page++">下一页</button></div>
  </template>
</template>
