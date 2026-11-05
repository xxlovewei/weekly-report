<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import type { MeetingPerson } from './types'

defineProps<{ people: MeetingPerson[]; selected: number[]; loading?: boolean; label: string }>()
const emit = defineEmits<{ toggle: [person: MeetingPerson] }>()
const root = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const menu = ref<HTMLElement | null>(null)
const open = ref(false)
const menuStyle = ref<Record<string, string>>({})

function positionMenu() {
  if (!open.value || !trigger.value) return
  const rect = trigger.value.getBoundingClientRect()
  const below = window.innerHeight - rect.bottom - 12
  const above = rect.top - 12
  const upward = below < 160 && above > below
  menuStyle.value = {
    left: `${rect.left}px`, width: `${rect.width}px`,
    maxHeight: `${Math.max(40, Math.min(220, upward ? above : below))}px`,
    ...(upward ? { bottom: `${window.innerHeight - rect.top + 4}px` } : { top: `${rect.bottom + 4}px` }),
  }
}
function toggleMenu() {
  open.value = !open.value
  if (open.value) void nextTick(() => { positionMenu(); menu.value?.querySelector<HTMLInputElement>('input')?.focus() })
}
function closeMenu() { open.value = false }
function closeWithKeyboard() { closeMenu(); trigger.value?.focus() }
function closeOutside(event: Event) {
  const target = event.target
  if (target instanceof Node && !root.value?.contains(target) && !menu.value?.contains(target)) closeMenu()
}
onMounted(() => {
  document.addEventListener('pointerdown', closeOutside, true)
  document.addEventListener('focusin', closeOutside)
  document.addEventListener('scroll', positionMenu, true)
  window.addEventListener('resize', positionMenu)
})
onUnmounted(() => {
  document.removeEventListener('pointerdown', closeOutside, true)
  document.removeEventListener('focusin', closeOutside)
  document.removeEventListener('scroll', positionMenu, true)
  window.removeEventListener('resize', positionMenu)
})
</script>

<template>
  <div ref="root" class="assignee-select" @keydown.esc.stop.prevent="closeWithKeyboard">
    <button ref="trigger" type="button" class="assignee-trigger" :aria-label="label" aria-haspopup="dialog" :aria-expanded="open" :disabled="loading" @click="toggleMenu">
      <span>{{ selected.length ? `已选择 ${selected.length} 人` : '未选择' }}</span>
      <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="m3 4 3 4 3-4" fill="none" stroke="currentColor" stroke-width="1.5" /></svg>
    </button>
    <!-- 固定定位并挂到页面顶层，菜单不撑高任务行，也不被弹窗的滚动区域裁切。 -->
    <Teleport to="body">
      <div v-if="open" ref="menu" class="assignee-menu" role="dialog" :aria-label="label" :style="menuStyle" @keydown.esc.stop.prevent="closeWithKeyboard">
        <label v-for="person in people" :key="person.id" class="assignee-option"><input type="checkbox" :checked="selected.includes(person.id)" @change="emit('toggle', person)" /><span>{{ person.display_name }}</span></label>
        <span v-if="!people.length" class="assignee-empty">暂无普通用户</span>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.assignee-trigger{display:flex;align-items:center;justify-content:space-between;gap:8px;width:100%;min-height:38px;padding:9px 10px;border:2px solid #000;background:#fff;font-size:12px;text-align:left}
.assignee-trigger svg{flex-shrink:0}
.assignee-trigger:disabled{cursor:wait}
.assignee-menu{position:fixed;z-index:50;overflow-y:auto;border:2px solid #000;background:#fff;box-shadow:3px 3px 0 #000;padding:4px}
.assignee-option{display:flex;align-items:center;gap:7px;padding:7px 5px;cursor:pointer;font-size:12px;font-weight:700;overflow-wrap:anywhere}
.assignee-option:hover{background:#eef7ff}
.assignee-option input{width:14px;height:14px;padding:0;margin:0;flex-shrink:0}
.assignee-empty{display:block;padding:7px 5px;font-size:12px}
</style>
