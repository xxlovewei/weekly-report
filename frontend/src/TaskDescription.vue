<script setup lang="ts">
import { nextTick, onMounted, ref, useId, watch } from 'vue'
import { DescriptionHistory } from './descriptionHistory'
import { editNumberedText, moveNumberedText, reconcileNumberedInput } from './numberedLines'
import type { NumberedEdit, TextSelection } from './numberedLines'

const props = defineProps<{ modelValue: string; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const textarea = ref<HTMLTextAreaElement | null>(null)
const text = ref(props.modelValue), error = ref('')
const id = useId()
const history = new DescriptionHistory()
let known: TextSelection = { value: props.modelValue, start: 0, end: 0 }
let pending: { before: TextSelection; inputType: string; expected?: TextSelection | null } | null = null
let composition: TextSelection | null = null
let drag: { before: TextSelection; removed: boolean; target?: number } | null = null

function read(): TextSelection {
  const el = textarea.value!
  return { value: el.value, start: el.selectionStart, end: el.selectionEnd, direction: el.selectionDirection }
}
function resize() {
  const el = textarea.value
  if (el) { el.style.height = 'auto'; el.style.height = `${el.scrollHeight + 4}px` }
}
function display(state: TextSelection, focus = false) {
  const el = textarea.value!
  const scrollLeft = el.scrollLeft
  text.value = state.value
  el.value = state.value
  if (focus) el.focus({ preventScroll: true })
  el.setSelectionRange(state.start, state.end, state.direction || 'none')
  el.scrollLeft = scrollLeft
  known = { ...state }
  resize()
  void nextTick(resize)
}
function commit(before: TextSelection, after: TextSelection, kind: string) {
  pending = null
  if (Array.from(after.value).length > 5000) {
    display(before)
    error.value = '任务描述最多 5000 个字符，本次操作未应用。'
    return
  }
  error.value = ''
  history.record(before, after, kind)
  display(after)
  if (before.value !== after.value) emit('update:modelValue', after.value)
}
function apply(operation: NumberedEdit) {
  const before = read()
  const result = editNumberedText(before.value, before.start, before.end, operation)
  if (!result) return false
  commit(before, result, 'structural')
  return true
}
function restoreHistory(redo: boolean) {
  if (props.disabled || composition) return
  const before = read(), result = redo ? history.redo() : history.undo()
  if (!result) return
  pending = null
  error.value = ''
  display(result, true)
  if (before.value !== result.value) emit('update:modelValue', result.value)
}
function keydown(event: KeyboardEvent) {
  if (props.disabled || composition || event.isComposing || event.keyCode === 229) return
  const key = event.key.toLowerCase()
  if ((event.ctrlKey || event.metaKey) && !event.altKey && (key === 'z' || key === 'y')) {
    event.preventDefault()
    restoreHistory(key === 'y' || event.shiftKey)
    return
  }
  if (event.ctrlKey || event.altKey || event.metaKey) return
  const kind = event.key === 'Enter' ? (event.shiftKey ? 'softBreak' : 'enter')
    : event.key === 'Backspace' ? 'backspace' : event.key === 'Delete' ? 'delete' : null
  if (kind && apply({ kind })) event.preventDefault()
}
function beforeinput(event: InputEvent) {
  if (props.disabled || composition || event.isComposing) return
  if (drag && event.inputType === 'insertFromDrop') {
    const position = read().start
    drag.target = drag.removed && position >= drag.before.start ? position + drag.before.end - drag.before.start : position
    return
  }
  if (event.inputType === 'historyUndo' || event.inputType === 'historyRedo') {
    if (event.cancelable) { event.preventDefault(); restoreHistory(event.inputType === 'historyRedo') }
    else pending = { before: read(), inputType: event.inputType }
    return
  }
  const before = read()
  const kind = event.inputType === 'insertLineBreak' || event.inputType === 'insertParagraph' ? 'enter'
    : event.inputType === 'deleteContentBackward' ? 'backspace' : event.inputType === 'deleteContentForward' ? 'delete' : null
  let expected: TextSelection | null | undefined
  if (kind) expected = editNumberedText(before.value, before.start, before.end, { kind })
  else if (event.inputType.startsWith('delete') && before.start !== before.end) {
    expected = editNumberedText(before.value, before.start, before.end, { kind: 'replace', text: '' })
  } else if (event.inputType === 'insertFromDrop' || event.inputType === 'insertFromPaste') {
    const data = event.dataTransfer?.getData('text/plain') ?? event.data
    if (typeof data === 'string') expected = editNumberedText(before.value, before.start, before.end, { kind: 'paste', text: data })
  } else if (typeof event.data === 'string') {
    expected = editNumberedText(before.value, before.start, before.end, { kind: 'replace', text: event.data })
  }
  if (expected && event.cancelable && kind) {
    event.preventDefault()
    commit(before, expected, 'structural')
  } else pending = { before, inputType: event.inputType, expected }
}
function input(event: Event) {
  const actual = read(), inputEvent = event as InputEvent
  text.value = actual.value
  resize()
  if (composition || inputEvent.isComposing) return
  if (drag && (inputEvent.inputType === 'deleteByDrag' || inputEvent.inputType === 'insertFromDrop')) {
    drag.removed ||= inputEvent.inputType === 'deleteByDrag'
    return
  }
  const historyType = pending?.inputType || inputEvent.inputType
  if (historyType === 'historyUndo' || historyType === 'historyRedo') {
    const redo = historyType === 'historyRedo'
    display(pending?.before || known)
    pending = null
    restoreHistory(redo)
    return
  }
  const before = pending?.before || { ...known }
  const inputType = pending?.inputType || inputEvent.inputType || ''
  // Prefix Enter is an ordinary line break; do not repair the deliberately edited prefix.
  const result = pending?.expected || (pending?.expected === null && (inputType === 'insertLineBreak' || inputType === 'insertParagraph') ? actual
    : reconcileNumberedInput(before.value, actual.value, actual.start, actual.end, inputType))
  const typing = inputType === 'insertText' && before.start === before.end && !before.value.slice(before.start, before.end).includes('\n')
  if (result.start !== result.end) result.direction = actual.direction
  commit(before, result, typing ? 'typing' : 'structural')
}
function paste(event: ClipboardEvent) {
  if (props.disabled || composition || !event.clipboardData) return
  event.preventDefault()
  apply({ kind: 'paste', text: event.clipboardData.getData('text/plain') })
}
function compositionStart() { composition = read(); pending = null }
function compositionEnd() {
  if (!composition) return
  const before = composition, actual = read()
  composition = null
  commit(before, reconcileNumberedInput(before.value, actual.value, actual.start, actual.end), 'composition')
}
function dragStart() {
  const before = read()
  if (!props.disabled && !composition && before.start !== before.end) drag = { before, removed: false }
}
function dragEnd() {
  if (!drag) return
  const { before, removed, target } = drag, actual = read()
  drag = null
  const result = target === undefined ? reconcileNumberedInput(before.value, actual.value, actual.start, actual.end, 'deleteByDrag')
    : removed ? moveNumberedText(before.value, before.start, before.end, target)
    : editNumberedText(before.value, target, target, { kind: 'paste', text: before.value.slice(before.start, before.end) })!
  commit(before, result, 'structural')
}
function rememberSelection() {
  if (!composition && textarea.value?.value === known.value) known = read()
}
watch(() => props.modelValue, value => {
  if (value === known.value) return
  history.clear()
  pending = null
  composition = null
  drag = null
  error.value = ''
  if (textarea.value) display({ value, start: Math.min(known.start, value.length), end: Math.min(known.end, value.length) })
  else { text.value = value; known = { value, start: 0, end: 0 } }
})
onMounted(resize)
</script>

<template>
  <label><span>任务描述</span><textarea ref="textarea" :disabled="disabled" rows="2" :value="text" placeholder="写下这项工作…" :aria-invalid="!!error" :aria-describedby="error ? `${id}-error` : undefined" @keydown="keydown" @beforeinput="beforeinput" @input="input" @paste="paste" @compositionstart="compositionStart" @compositionend="compositionEnd" @dragstart="dragStart" @dragend="dragEnd" @select="rememberSelection" @keyup="rememberSelection" @pointerup="rememberSelection" /></label>
  <p v-if="error" :id="`${id}-error`" class="description-error" role="alert">{{ error }}</p>
</template>
