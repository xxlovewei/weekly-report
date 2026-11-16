<script setup lang="ts">
import { computed, ref, useId } from 'vue'
import { api } from './api'

const props = defineProps<{ version: string; compact?: boolean }>()
const panelId = useId()
const trigger = ref<HTMLButtonElement | null>(null)
const open = ref(false), loading = ref(false), error = ref('')
interface ReleaseNote { version: string; description: string }
const history = ref<ReleaseNote[] | null>(null)
const selected = ref(props.version)
const index = computed(() => history.value?.findIndex(note => note.version === selected.value) ?? -1)
const active = computed(() => history.value?.[index.value])

function adjacentVersion(offset: number) {
  return history.value?.[index.value + offset]
}

function moveVersion(offset: number) {
  const target = adjacentVersion(offset)
  if (target) selected.value = target.version
}

async function showNotes() {
  if (!open.value) selected.value = props.version
  open.value = true
  if (history.value || loading.value) return
  loading.value = true; error.value = ''
  try {
    const records = await api<ReleaseNote[]>('/releases')
    if (!records.some(note => note.version === props.version)) {
      records.push({ version: props.version, description: '暂无本版本的更新说明。' })
    }
    // 按版本号的数字顺序排列，1.10.0 排在 1.9.0 之后。
    history.value = records.sort((a, b) => a.version.localeCompare(b.version, undefined, { numeric: true }))
  } catch { error.value = '暂时无法读取更新内容，请稍后重试。' }
  finally { loading.value = false }
}

function leaveNotes(event: MouseEvent) {
  // 鼠标移开时保留键盘正在操作的弹框。
  if (!(event.currentTarget as HTMLElement).querySelector(':focus-visible')) open.value = false
}

function blurNotes(event: FocusEvent) {
  if (!(event.currentTarget as HTMLElement).contains(event.relatedTarget as Node | null)) open.value = false
}

function dismissNotes() {
  if (open.value) trigger.value?.focus()
  open.value = false
}
</script>

<template>
  <div class="release-notes" @mouseenter="showNotes" @mouseleave="leaveNotes" @focusout="blurNotes" @keydown.esc.stop.prevent="dismissNotes">
    <small><button ref="trigger" type="button" class="release-trigger" data-sidebar-tour="release-notes" :aria-expanded="open" :aria-controls="open ? panelId : undefined" @focus="showNotes" @click="showNotes"><span v-if="!compact">当前版本：</span>v{{ version }}</button></small>
    <div v-if="open" :id="panelId" class="release-tooltip" role="region" :aria-labelledby="`${panelId}-title`">
      <div class="release-notes-header">
        <strong :id="`${panelId}-title`" aria-live="polite">v{{ selected }} 更新内容</strong>
        <button type="button" class="icon-btn" aria-label="上一个版本" title="上一个版本" :aria-disabled="!adjacentVersion(-1)" @click="moveVersion(-1)">←</button>
        <button type="button" class="icon-btn" aria-label="下一个版本" title="下一个版本" :aria-disabled="!adjacentVersion(1)" @click="moveVersion(1)">→</button>
      </div>
      <p :key="selected">{{ loading ? '正在加载更新内容…' : error || active?.description }}</p>
    </div>
  </div>
</template>

<style scoped>
.release-notes{position:relative}
.release-trigger{padding:0;border:0;background:transparent;cursor:help;letter-spacing:inherit}
.release-trigger:focus-visible{outline:2px solid #000;outline-offset:3px}
.release-tooltip{position:absolute;top:100%;left:0;z-index:60;width:min(340px,calc(100vw - 120px));padding:12px;border:2px solid #000;background:#fff;box-shadow:4px 4px 0 #000;letter-spacing:normal}
.release-notes-header{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.release-notes-header strong{font-size:13px}
.release-notes-header button{flex:none;width:26px;height:24px;padding:0}
.release-notes-header button[aria-disabled="true"]{cursor:not-allowed;opacity:.45;background:#fff;transform:none;box-shadow:2px 2px 0 #000}
.release-tooltip p{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;line-height:1.6;max-height:320px;overflow-y:auto}
/* 引导弹窗贴着版本号时，把更新说明放到弹窗下方，并保留可悬停的路径。 */
.release-notes:has(.release-trigger.driver-active-element) .release-tooltip{--release-tour-gap:180px;top:calc(100% + var(--release-tour-gap))}
.release-notes:has(.release-trigger.driver-active-element) .release-tooltip::before{content:"";position:absolute;bottom:100%;left:0;width:38px;height:calc(var(--release-tour-gap) + 4px)}
.release-notes:has(.release-trigger.driver-active-element) .release-tooltip p{max-height:clamp(48px,calc(100dvh - 340px),320px)}
</style>
