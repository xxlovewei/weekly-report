<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, ApiError } from './api'
import type { TaskPriority } from './types'

interface Card {
  id: number
  name: string
  category_name: string
  priority: TaskPriority
  state: 'inbox' | 'in_progress' | 'done'
  status: string | null
}

const props = defineProps<{ plannedIds: Set<number>; busy: boolean }>()
const emit = defineEmits<{ close: []; add: [id: number]; drag: [id: number | null] }>()
const cards = ref<Card[]>([])
const loading = ref(true), error = ref('')
const closeButton = ref<HTMLButtonElement | null>(null)
const columns = computed(() => [
  { state: 'inbox', label: '任务箱', cards: cards.value.filter(card => card.state === 'inbox') },
  { state: 'in_progress', label: '进行中', cards: cards.value.filter(card => card.state === 'in_progress') },
])

async function load() {
  loading.value = true
  error.value = ''
  try {
    cards.value = (await api<{ tasks: Card[] }>('/board-tasks')).tasks
  } catch (cause) {
    error.value = cause instanceof ApiError ? cause.message : '任务看板加载失败，请重试。'
  } finally {
    loading.value = false
  }
}

function startDrag(event: DragEvent, id: number) {
  if (props.busy || props.plannedIds.has(id) || !event.dataTransfer) {
    event.preventDefault()
    return
  }
  // 计划引用原任务，使用独立的拖拽类型，与表内排序区分。
  event.dataTransfer.effectAllowed = 'copy'
  event.dataTransfer.setData('application/x-zhoubao-board-plan', String(id))
  const card = (event.currentTarget as HTMLElement).closest('.plan-board-card')
  if (card) event.dataTransfer.setDragImage(card, 12, 12)
  emit('drag', id)
}

onMounted(() => {
  closeButton.value?.focus()
  void load()
})
</script>

<template>
  <aside id="plan-task-board" class="plan-task-board" aria-labelledby="plan-task-board-title" @keydown.esc.stop="emit('close')">
    <header class="plan-board-header">
      <h2 id="plan-task-board-title">任务看板</h2>
      <button ref="closeButton" type="button" class="icon-btn" aria-label="关闭任务看板" @click="emit('close')">×</button>
    </header>
    <p v-if="loading" role="status">正在加载任务…</p>
    <div v-else-if="error" role="alert">
      <p>{{ error }}</p>
      <button type="button" class="mini-button" @click="load">重试</button>
    </div>
    <div v-else class="plan-board-columns">
      <section v-for="column in columns" :key="column.state" class="plan-board-column" :aria-labelledby="`plan-board-${column.state}`">
        <h3 :id="`plan-board-${column.state}`">{{ column.label }}</h3>
        <div class="plan-board-cards">
          <p v-if="!column.cards.length" class="plan-board-empty">暂无任务</p>
          <article v-for="card in column.cards" :key="card.id" class="plan-board-card priority-edge"
            :data-priority="card.priority" :aria-label="card.name || '未命名任务'">
            <span v-if="!plannedIds.has(card.id)" class="plan-board-grip" title="拖到任务计划表" aria-hidden="true"
              :draggable="!busy" @dragstart="startDrag($event, card.id)" @dragend="emit('drag', null)">⠿</span>
            <div class="plan-board-card-content">
              <strong class="preline">{{ card.name || '未命名任务' }}</strong>
              <small v-if="card.category_name || card.status">{{ [card.category_name, card.status].filter(Boolean).join(' · ') }}</small>
            </div>
            <button type="button" class="mini-button plan-board-card-action" :aria-disabled="busy || plannedIds.has(card.id)"
              :aria-label="`${plannedIds.has(card.id) ? '已加入计划' : '加入计划'}：${card.name || '未命名任务'}`"
              @click="emit('add', card.id)">{{ plannedIds.has(card.id) ? '已加入' : '加入计划' }}</button>
          </article>
        </div>
      </section>
    </div>
  </aside>
</template>

<style scoped>
.plan-task-board {
  position: fixed; z-index: 17; inset: 12px 12px 12px auto;
  width: min(360px, calc(100vw - 112px));
  display: flex; flex-direction: column; gap: 14px; padding: 14px;
  background: #fff; border: 2px solid #000; box-shadow: 5px 5px 0 #000;
  animation: plan-board-enter 150ms ease-out;
}
.plan-board-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.plan-board-header h2, .plan-board-column h3, .plan-board-empty { margin: 0; }
.plan-board-columns { flex: 1; min-height: 0; display: grid; grid-template-rows: repeat(2, minmax(0, 1fr)); gap: 12px; }
.plan-board-column { min-height: 0; display: flex; flex-direction: column; border: 1px solid #000; }
.plan-board-column h3 { padding: 8px; border-bottom: 1px solid #000; background: #ccff00; font-size: 15px; }
.plan-board-cards { flex: 1; min-height: 0; overflow: auto; display: grid; align-content: start; gap: 8px; padding: 8px; }
.plan-board-card {
  display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 5px; padding: 8px; border: 1px solid #222;
  border-inline-start: 4px solid var(--priority-glow); box-shadow: var(--priority-edge-shadow);
}
.plan-board-grip { padding: 2px 4px; font-size: 18px; -webkit-user-select: none; user-select: none; }
.plan-board-grip[draggable="true"] { cursor: grab; }
.plan-board-card-content { grid-column: 2; display: grid; gap: 5px; }
.plan-board-card small, .plan-board-empty { font-size: 12px; color: #555; }
.plan-board-card-action { grid-column: 2; justify-self: end; font-size: 11px; }
.plan-board-card-action[aria-disabled="true"] { cursor: default; color: #555; background: #f4f4f4; box-shadow: none; transform: none; }
@keyframes plan-board-enter { from { transform: translateX(calc(100% + 12px)); } }
@media (prefers-reduced-motion: reduce) { .plan-task-board { animation: none; } }
</style>
