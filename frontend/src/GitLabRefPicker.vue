<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { api } from './api'

type GitLabRef = { name: string; sha: string }
const props = defineProps<{ projectId: number; kind: 'branches' | 'tags'; disabled?: boolean }>()
const selected = defineModel<GitLabRef | null>({ required: true })
const label = computed(() => props.kind === 'branches' ? 'GitLab 分支' : 'GitLab 标签')
const input = ref<HTMLInputElement | null>(null)
const root = ref<HTMLElement | null>(null)
const menu = ref<HTMLElement | null>(null)
const inputId = useId()
const listId = `${inputId}-options`
const open = ref(false), loading = ref(false), error = ref('')
const text = ref(selected.value?.name ?? '')
const options = ref<GitLabRef[]>([]), active = ref(-1)
const currentPage = ref(0), hasMore = ref(false)
let query = '', requestId = 0
let debounce: ReturnType<typeof setTimeout> | undefined

function hasUnselectedText() {
  return !selected.value && Boolean(text.value.trim())
}
defineExpose({ hasUnselectedText })

async function fetchOptions(page: number) {
  const request = ++requestId
  const params = new URLSearchParams({ page: String(page), search: query })
  loading.value = true
  error.value = ''
  try {
    const result = await api<{ items: GitLabRef[]; has_more: boolean }>(
      `/deployments/projects/${props.projectId}/${props.kind}?${params}`,
    )
    // 连续筛选或关闭弹窗后，忽略较早请求的结果。
    if (request !== requestId) return
    const seen = new Set(page > 1 ? options.value.map(option => option.name) : [])
    const added = result.items.filter(option => !seen.has(option.name))
    options.value = page > 1 ? [...options.value, ...added] : added
    hasMore.value = result.has_more && added.length > 0
    currentPage.value = page
  } catch (cause) {
    if (request === requestId) error.value = (cause as Error).message
  } finally {
    if (request === requestId) loading.value = false
  }
}

function search(value: string, delay = false) {
  clearTimeout(debounce)
  requestId++
  query = value
  options.value = []
  currentPage.value = 0
  hasMore.value = false
  active.value = -1
  error.value = ''
  loading.value = true
  if (delay) debounce = setTimeout(() => { void fetchOptions(1) }, 200)
  else void fetchOptions(1)
}

function positionMenu() {
  if (!open.value || !input.value || !menu.value) return
  const rect = input.value.getBoundingClientRect()
  const dialog = root.value?.closest('dialog')?.getBoundingClientRect()
  if (dialog && (rect.bottom <= dialog.top || rect.top >= dialog.bottom)) { closeList(); return }
  const below = window.innerHeight - rect.bottom - 8
  const above = rect.top - 8
  const opensAbove = below < 200 && above > below
  Object.assign(menu.value.style, {
    left: `${rect.left}px`, width: `${rect.width}px`, maxHeight: `${Math.max(0, opensAbove ? above : below)}px`,
    top: opensAbove ? 'auto' : `${rect.bottom + 4}px`,
    bottom: opensAbove ? `${window.innerHeight - rect.top + 4}px` : 'auto',
  })
}

function showMenu() {
  open.value = true
  positionMenu()
  // 使用顶层弹层，滚动对话框也不会裁剪下拉选项。
  if (open.value && !menu.value?.matches(':popover-open')) menu.value?.showPopover()
}

function openList() {
  if (open.value || props.disabled) return
  showMenu()
  search(selected.value ? '' : text.value.trim())
}

function closeList() {
  clearTimeout(debounce)
  requestId++
  open.value = false
  if (menu.value?.matches(':popover-open')) menu.value.hidePopover()
  active.value = -1
}

function onInput(event: Event) {
  text.value = (event.target as HTMLInputElement).value
  selected.value = null
  showMenu()
  search(text.value.trim(), true)
}

function selectOption(option: GitLabRef) {
  selected.value = option
  text.value = option.name
  // 选中选项不会触发原生 input 事件，主动清除上次提交留下的校验文案。
  input.value?.setCustomValidity('')
  closeList()
}

function clear() {
  selected.value = null
  text.value = ''
  input.value?.setCustomValidity('')
  if (input.value !== document.activeElement) input.value?.focus()
  if (open.value && query) search('')
  else openList()
}

function onFocusOut(event: FocusEvent) {
  if (!root.value?.contains(event.relatedTarget as Node | null)) closeList()
}

function onOutsidePointer(event: PointerEvent) {
  if (open.value && !root.value?.contains(event.target as Node)) closeList()
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && open.value) {
    event.preventDefault()
    event.stopPropagation()
    closeList()
  } else if (event.key === 'Enter' && open.value) {
    event.preventDefault()
    const option = options.value[active.value]
    if (option) selectOption(option)
  } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    openList()
    if (!options.value.length) return
    if (event.key === 'ArrowDown' && active.value === options.value.length - 1 && hasMore.value && !loading.value) {
      void fetchOptions(currentPage.value + 1)
      return
    }
    active.value = event.key === 'ArrowDown' ? Math.min(active.value + 1, options.value.length - 1)
      : active.value <= 0 ? options.value.length - 1 : active.value - 1
    void nextTick(() => document.getElementById(`${listId}-${active.value}`)?.scrollIntoView({ block: 'nearest' }))
  }
}

watch(() => props.disabled, disabled => { if (disabled) closeList() })
onMounted(() => {
  document.addEventListener('pointerdown', onOutsidePointer)
  window.addEventListener('scroll', positionMenu, true)
  window.addEventListener('resize', positionMenu)
})
onBeforeUnmount(() => {
  closeList()
  document.removeEventListener('pointerdown', onOutsidePointer)
  window.removeEventListener('scroll', positionMenu, true)
  window.removeEventListener('resize', positionMenu)
})
</script>

<template>
  <div ref="root" class="gitlab-ref-picker" @focusout="onFocusOut">
    <label :for="inputId">{{ label }}（选填）</label>
    <div class="gitlab-ref-input">
      <input :id="inputId" ref="input" :value="text" :disabled="disabled"
        role="combobox" type="text" maxlength="1000" autocomplete="off" :aria-expanded="open" aria-autocomplete="list"
        :aria-controls="listId" :aria-activedescendant="open && active >= 0 ? `${listId}-${active}` : undefined"
        :placeholder="`选择或搜索${label}`"
        @focus="openList" @click="openList" @input="onInput" @keydown="onKeydown" />
      <button v-if="text" type="button" class="gitlab-ref-clear" :disabled="disabled"
        :aria-label="`清空${label}`" @pointerdown.prevent @click="clear">×</button>
    </div>
    <div ref="menu" popover="manual" class="gitlab-ref-menu">
      <ul :id="listId" role="listbox" :aria-label="label" :aria-busy="loading">
        <li v-for="(option, index) in options" :id="`${listId}-${index}`" :key="option.name"
          role="option" :aria-selected="selected?.name === option.name" :class="{ highlighted: active === index }"
          @pointerdown.prevent @click="selectOption(option)">
          <span>{{ option.name }}</span><small>{{ option.sha.slice(0, 8) }}</small>
        </li>
      </ul>
      <p v-if="error" class="review-error" role="alert">{{ error }}</p>
      <p v-else-if="loading" role="status">正在查询…</p>
      <p v-else-if="!options.length" role="status">没有匹配的{{ kind === 'branches' ? '分支' : '标签' }}</p>
      <button v-if="error || hasMore" type="button" :disabled="loading" class="gitlab-ref-more"
        @pointerdown.prevent @click="fetchOptions(currentPage + 1)">{{ error ? '重试' : '加载更多' }}</button>
    </div>
  </div>
</template>

<style scoped>
.gitlab-ref-picker { min-width: 0; display: grid; gap: .35rem; }
.gitlab-ref-picker label { display: block; }
.gitlab-ref-input { position: relative; }
.gitlab-ref-input input { padding-right: 2.5rem; }
.gitlab-ref-clear { position: absolute; right: .25rem; top: 50%; transform: translateY(-50%); border: 0; background: none; width: 2rem; height: 2rem; font-size: 1.25rem; }
.gitlab-ref-menu { position: fixed; inset: auto; margin: 0; padding: 0; overflow: auto; border: 2px solid currentColor; background: Canvas; box-shadow: 0 .4rem 1rem #17213130; }
.gitlab-ref-menu ul { list-style: none; margin: 0; padding: 0; max-height: 12rem; overflow-y: auto; }
.gitlab-ref-menu li { display: flex; justify-content: space-between; gap: .65rem; padding: .45rem .6rem; cursor: pointer; overflow-wrap: anywhere; }
.gitlab-ref-menu li:is(:hover, .highlighted, [aria-selected="true"]) { background: #ccff00; }
.gitlab-ref-menu small { flex-shrink: 0; }
.gitlab-ref-menu p { margin: 0; padding: .45rem .6rem; }
.gitlab-ref-more { padding: .4rem .6rem; border: 0; border-top: 1px solid currentColor; background: Canvas; width: 100%; }
.gitlab-ref-more:hover { background: #ffff00; }
</style>
