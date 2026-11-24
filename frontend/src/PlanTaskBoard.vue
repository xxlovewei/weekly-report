<script setup lang="ts">
import { onMounted, ref } from 'vue'
import TaskBoard from './TaskBoard.vue'

defineProps<{ plannedIds: Set<number>; busy: boolean; dragging: boolean }>()
const emit = defineEmits<{ close: []; add: [id: number]; drag: [id: number | null] }>()
const closeButton = ref<HTMLButtonElement | null>(null)

onMounted(() => closeButton.value?.focus())
</script>

<template>
  <aside id="plan-task-board" class="plan-task-board" :class="{ 'plan-task-board-dragging': dragging }"
    aria-labelledby="plan-task-board-title" @keydown.esc.stop="emit('close')">
    <header class="plan-board-header">
      <h2 id="plan-task-board-title">任务看板</h2>
      <button ref="closeButton" type="button" class="icon-btn" aria-label="关闭任务看板" @click="emit('close')">×</button>
    </header>
    <TaskBoard :planned-ids="plannedIds" :plan-busy="busy" @add-plan="emit('add', $event)" @plan-drag="emit('drag', $event)" />
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
.plan-board-header h2 { margin: 0; }
/* 拖拽期间露出被侧栏覆盖的计划区域，让整个列表可放置。 */
.plan-task-board-dragging { opacity: .25; pointer-events: none; }
@keyframes plan-board-enter { from { transform: translateX(calc(100% + 12px)); } }
@media (prefers-reduced-motion: reduce) { .plan-task-board { animation: none; } }
</style>
