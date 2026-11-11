<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { api, ApiError } from './api'
import type { MeetingPerson, Task, TaskPriority } from './types'

const props = defineProps<{ tasks: Task[]; busy?: boolean }>()
const emit = defineEmits<{
  move: [id: number, targetId: number, after: boolean]
  priority: [id: number, priority: TaskPriority | null]
  transfer: [id: number, userId: number]
}>()

const menu = ref<HTMLElement | null>(null)
const action = ref<{ id: number; x: number; y: number } | null>(null)
const choosingPriority = ref(false)
const index = computed(() => props.tasks.findIndex(task => task.id === action.value?.id))
const priorities = ['高', '中', '低', null] as const
let previousFocus: HTMLElement | null = null

async function placeMenu() {
  await nextTick()
  if (!menu.value || !action.value) return
  // 菜单贴近点击位置，同时保证靠近窗口边缘时仍能看到完整选项。
  const { offsetWidth, offsetHeight } = menu.value
  menu.value.style.left = `${Math.max(8, Math.min(action.value.x, window.innerWidth - offsetWidth - 8))}px`
  menu.value.style.top = `${Math.max(8, Math.min(action.value.y, window.innerHeight - offsetHeight - 8))}px`
  menu.value.querySelector<HTMLElement>('button:not(:disabled)')?.focus({ preventScroll: true })
}
function open(event: MouseEvent | KeyboardEvent, id: number) {
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  if (!action.value) previousFocus = document.activeElement as HTMLElement | null
  choosingPriority.value = false
  action.value = {
    id,
    x: event instanceof MouseEvent ? event.clientX : rect.left + 12,
    y: event instanceof MouseEvent ? event.clientY : rect.top + 12,
  }
  void placeMenu()
}
defineExpose({ open })

function close(restoreFocus = false) {
  if (!action.value) return
  action.value = null
  if (restoreFocus) previousFocus?.focus({ preventScroll: true })
}
function dismissOutside(event: Event) {
  if (event.target instanceof Node && menu.value?.contains(event.target)) return
  close()
}
function dismiss() { close() }
onMounted(() => {
  document.addEventListener('pointerdown', dismissOutside, true)
  window.addEventListener('wheel', dismissOutside, true)
  window.addEventListener('resize', dismiss)
})
onUnmounted(() => {
  document.removeEventListener('pointerdown', dismissOutside, true)
  window.removeEventListener('wheel', dismissOutside, true)
  window.removeEventListener('resize', dismiss)
})
watch(() => props.busy, busy => { if (busy) close() })
watch(index, value => { if (value < 0) close() })

function move(targetIndex: number) {
  const task = props.tasks[index.value], target = props.tasks[targetIndex]
  const after = targetIndex > index.value
  close(true)
  if (task && target) emit('move', task.id, target.id, after)
}
function showPriorities() {
  choosingPriority.value = true
  void placeMenu()
}
function setPriority(priority: TaskPriority | null) {
  const task = props.tasks[index.value]
  close(true)
  if (task && (task.priority ?? null) !== priority) emit('priority', task.id, priority)
}

const dialog = ref<HTMLDialogElement | null>(null)
const transferId = ref<number | null>(null)
const recipientId = ref<number | null>(null)
const recipients = ref<MeetingPerson[]>([])
const loading = ref(false), error = ref('')
let request = 0
async function startTransfer() {
  if (!action.value) return
  transferId.value = action.value.id
  recipientId.value = null
  recipients.value = []
  error.value = ''
  loading.value = true
  close()
  dialog.value?.showModal()
  const serial = ++request
  try {
    const people = await api<MeetingPerson[]>('/task-transfer-recipients')
    if (serial === request) recipients.value = people
  } catch (failure) {
    if (serial === request) error.value = failure instanceof ApiError ? failure.message : '加载接收人失败，请重试。'
  } finally {
    if (serial === request) loading.value = false
  }
}
function transferClosed() {
  request++
  transferId.value = null
  previousFocus?.focus({ preventScroll: true })
}
function confirmTransfer() {
  if (transferId.value === null || recipientId.value === null || props.busy) return
  emit('transfer', transferId.value, recipientId.value)
  dialog.value?.close()
}
</script>

<template>
  <Teleport to="body">
    <div v-if="action && index >= 0" ref="menu" class="task-context-menu" role="group" :aria-label="choosingPriority ? '设置优先级' : '任务操作'" @keydown.esc.stop.prevent="close(true)">
      <template v-if="choosingPriority">
        <button v-for="priority in priorities" :key="priority || 'none'" type="button"
          :aria-pressed="(tasks[index]?.priority ?? null) === priority" @click="setPriority(priority)">{{ priority || '无优先级' }}</button>
      </template>
      <template v-else>
        <button type="button" :disabled="index === 0" @click="move(0)">置顶</button>
        <button type="button" :disabled="index === 0" @click="move(index - 1)">上移一行</button>
        <button type="button" :disabled="index === tasks.length - 1" @click="move(index + 1)">下移一行</button>
        <button type="button" :disabled="index === tasks.length - 1" @click="move(tasks.length - 1)">置底</button>
        <button type="button" @click="showPriorities">设置优先级 <span aria-hidden="true">›</span></button>
        <button type="button" aria-haspopup="dialog" @click="startTransfer">转交任务</button>
      </template>
    </div>
    <dialog ref="dialog" class="modal task-transfer-dialog" aria-labelledby="task-transfer-title" @close="transferClosed">
      <form @submit.prevent="confirmTransfer">
        <h2 id="task-transfer-title">转交任务</h2>
        <p v-if="loading" role="status">正在加载接收人…</p>
        <p v-else-if="error" role="alert">{{ error }}</p>
        <p v-else-if="!recipients.length" role="status">暂无可转交的普通用户。</p>
        <label v-else>接收人
          <select v-model="recipientId" required>
            <option :value="null" disabled>请选择接收人</option>
            <option v-for="person in recipients" :key="person.id" :value="person.id">{{ person.display_name }}（{{ person.username }}）</option>
          </select>
        </label>
        <div class="modal-actions">
          <button class="secondary-button" type="button" autofocus @click="dialog?.close()">取消</button>
          <button class="primary-button" type="submit" :disabled="recipientId === null || busy">确认转交</button>
        </div>
      </form>
    </dialog>
  </Teleport>
</template>
