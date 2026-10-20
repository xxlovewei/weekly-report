<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { addDays, monthGrid, mondayOf, todayShanghai } from './dates'
import { api } from './api'
const props = defineProps<{ selected: string; scope: 'work' | 'reports'; refreshKey?: number }>()
const emit = defineEmits<{ select: [week: string, refresh?: boolean] }>()
const displayed = ref({ year: Number(props.selected.slice(0, 4)), month: Number(props.selected.slice(5, 7)) })
const currentWeek = ref(mondayOf(todayShanghai()))
const marked = ref<string[]>([])
let request = 0
watch(() => [displayed.value.year, displayed.value.month, props.scope, props.refreshKey], async () => {
  const latest = ++request
  try {
    const result = await api<string[]>(`/calendar/marks?year=${displayed.value.year}&month=${displayed.value.month}&scope=${props.scope}`)
    if (latest === request) marked.value = result
  } catch { if (latest === request) marked.value = [] }
}, { immediate: true })
watch(() => props.selected, value => {
  const start = displayed.value.year * 12 + displayed.value.month
  const next = Number(value.slice(0, 4)) * 12 + Number(value.slice(5, 7))
  if (Math.abs(start - next) > 1) displayed.value = { year: Number(value.slice(0, 4)), month: Number(value.slice(5, 7)) }
})
const days = computed(() => monthGrid(displayed.value.year, displayed.value.month))
function shift(offset: number) {
  const date = new Date(Date.UTC(displayed.value.year, displayed.value.month - 1 + offset, 1))
  displayed.value = { year: date.getUTCFullYear(), month: date.getUTCMonth() + 1 }
}
function goCurrent() {
  const today = todayShanghai()
  currentWeek.value = mondayOf(today)
  displayed.value = { year: Number(today.slice(0, 4)), month: Number(today.slice(5, 7)) }
  emit('select', currentWeek.value, true)
}
</script>

<template>
  <section class="calendar" aria-label="选择周">
    <div class="calendar-head"><strong>{{ displayed.year }} / {{ String(displayed.month).padStart(2, '0') }}</strong><div><button class="icon-btn" type="button" aria-label="回到本周" title="回到本周" @click="goCurrent">回</button><button class="icon-btn" type="button" aria-label="上个月" @click="shift(-1)">←</button><button class="icon-btn" type="button" aria-label="下个月" @click="shift(1)">→</button></div></div>
    <div class="calendar-grid"><span v-for="label in ['一','二','三','四','五','六','日']" :key="label" class="calendar-label">{{ label }}</span>
      <button v-for="day in days" :key="day" type="button" class="calendar-day" :class="{ chosen: mondayOf(day) === selected, current: mondayOf(day) === currentWeek, outside: Number(day.slice(5,7)) !== displayed.month }" :aria-label="`${day}，选择该周${day === addDays(mondayOf(day), 6) && marked.includes(mondayOf(day)) ? '，已有任务' : ''}`" :aria-pressed="mondayOf(day) === selected" @click="emit('select', mondayOf(day))">{{ Number(day.slice(8)) }}<span v-if="day === addDays(mondayOf(day), 6) && marked.includes(mondayOf(day))" class="week-check" aria-hidden="true">√</span></button>
    </div>
    <p class="calendar-caption">{{ selected }} — {{ addDays(selected, 6) }}</p>
  </section>
</template>
