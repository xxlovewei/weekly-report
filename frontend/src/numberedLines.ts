export interface TextSelection { value: string; start: number; end: number; direction?: 'forward' | 'backward' | 'none' }
export type NumberedEdit = { kind: 'enter' | 'softBreak' | 'backspace' | 'delete' } | { kind: 'replace' | 'paste'; text: string }
interface Marker {
  start: number; end: number; body: number; digitStart: number; digitEnd: number
  indent: string; opening: string; closing: string; spacing: string; digits: string; number: number; group: number
}
interface Line { start: number; end: number; text: string; owner?: Marker; marker?: Marker }

function columns(text: string) {
  let width = 0
  for (const character of text) width += character === '\t' ? 4 - width % 4 : 1
  return width
}
function sameFormat(a: Marker, b: Marker) { return a.indent === b.indent && a.opening === b.opening && a.closing === b.closing }
function parse(value: string) {
  const lines: Line[] = [], markers: Marker[] = []
  let offset = 0, previous: Marker | undefined, group = 0
  for (const text of value.split('\n')) {
    const line: Line = { start: offset, end: offset + text.length, text }
    const match = /^([ \t]*)([(（]?)(\d+)([.．、)）])([ \t]*)/.exec(text)
    if (match) {
      const [, indent, opening, digits, closing, spacing] = match
      const valid = !(opening === '(' && closing !== ')') && !(opening === '（' && closing !== '）')
        && !(/[.．]/.test(closing) && !spacing && /^\d/.test(text.slice(match[0].length)))
        && Number.isSafeInteger(Number(digits))
      if (valid) {
        const marker: Marker = { start: offset, end: line.end, body: offset + match[0].length,
          digitStart: offset + indent.length + opening.length, digitEnd: offset + indent.length + opening.length + digits.length,
          indent, opening, closing, spacing, digits, number: Number(digits), group }
        if (previous && sameFormat(previous, marker) && previous.number + 1 === marker.number) marker.group = previous.group
        else marker.group = group++
        line.marker = line.owner = marker
        markers.push(marker)
        previous = marker
      }
    }
    if (!line.marker) {
      const indentation = /^[ \t]*/.exec(text)![0]
      const bodyColumn = previous ? columns(value.slice(previous.start, previous.body)) : 0
      if (previous && columns(indentation) >= bodyColumn && indentation.length > 0) line.owner = previous
      else previous = undefined
    }
    lines.push(line)
    offset = line.end + 1
  }
  return { lines, markers }
}
function numberText(marker: Marker, number: number) {
  return marker.digits.startsWith('0') ? String(number).padStart(marker.digits.length, '0') : String(number)
}
function prefix(marker: Marker, number = marker.number) {
  return `${marker.indent}${marker.opening}${numberText(marker, number)}${marker.closing}${marker.spacing}`
}

// Surviving markers keep their pre-edit group, even when insertion temporarily duplicates a number.
function replace(value: string, start: number, end: number, text: string, inserted: { offset: number; group: number }[] = [], force = false, selection?: { start: number; end: number }): TextSelection {
  const before = parse(value)
  let result = value.slice(0, start) + text + value.slice(end)
  let selectionStart = selection?.start ?? start + text.length, selectionEnd = selection?.end ?? selectionStart
  if (!force && !value.slice(start, end).includes('\n')) return { value: result, start: selectionStart, end: selectionEnd }
  const after = parse(result)
  const provenance = new Map<number, number>()
  for (const marker of before.markers) {
    if (start < marker.body && end > marker.start) continue
    const position = marker.digitStart >= end ? marker.digitStart + text.length - (end - start) : marker.digitStart
    provenance.set(position, marker.group)
  }
  for (const marker of inserted) provenance.set(start + marker.offset, marker.group)
  const numbers = new Map<number, number>()
  for (const marker of before.markers) if (!numbers.has(marker.group)) numbers.set(marker.group, marker.number)
  const changes: { start: number; end: number; text: string }[] = []
  const widths = new Map<number, number>()
  for (const marker of after.markers) {
    const group = provenance.get(marker.digitStart)
    if (group === undefined) continue
    const number = numbers.get(group)!
    if (!Number.isSafeInteger(number)) return { value, start, end }
    const digits = numberText(marker, number)
    changes.push({ start: marker.digitStart, end: marker.digitEnd, text: digits })
    widths.set(marker.digitStart, digits.length - marker.digits.length)
    numbers.set(group, number + 1)
  }
  for (const line of after.lines) {
    const delta = line.owner && widths.get(line.owner.digitStart)
    if (!line.marker && delta && line.owner) {
      const indentation = /^[ \t]*/.exec(line.text)![0]
      const width = columns(indentation) + delta - columns(line.owner.indent)
      changes.push({ start: line.start, end: line.start + indentation.length, text: line.owner.indent + ' '.repeat(Math.max(0, width)) })
    }
  }
  for (const change of changes.sort((a, b) => b.start - a.start)) {
    result = result.slice(0, change.start) + change.text + result.slice(change.end)
    const map = (position: number) => position >= change.end ? position + change.text.length - (change.end - change.start)
      : position > change.start ? change.start + Math.min(position - change.start, change.text.length) : position
    selectionStart = map(selectionStart)
    selectionEnd = map(selectionEnd)
  }
  return { value: result, start: selectionStart, end: selectionEnd }
}

export function editNumberedText(value: string, start: number, end: number, operation: NumberedEdit): TextSelection | null {
  const { lines, markers } = parse(value)
  const index = lines.findIndex(line => start >= line.start && start <= line.end)
  const line = lines[index], owner = line?.owner
  if (operation.kind === 'replace') return replace(value, start, end, operation.text)
  if (operation.kind === 'paste') {
    let text = operation.text.replace(/\r\n?/g, '\n')
    const pasted = parse(text.replace(/\n$/, ''))
    const matching = owner && pasted.markers.length > 0 && pasted.lines.every(item => item.owner)
      && pasted.markers.every(item => item.group === 0 && sameFormat(owner, item))
    const atStart = line?.marker && start === line.start
    const atEnd = owner && start === line.end && lines[index + 1]?.owner !== owner
    const selectionBoundary = end === start || end === value.length || lines.some(item => item.start === end)
    if (matching && (atStart || atEnd) && selectionBoundary) {
      text = text.replace(/\n$/, '')
      if (atEnd) text = '\n' + text
      if (atStart && end < value.length) text += '\n'
      const inserted = parse(text).markers.map(item => ({ offset: item.digitStart, group: owner.group }))
      return replace(value, start, end, text, inserted, true)
    }
    return replace(value, start, end, text)
  }
  if (operation.kind === 'enter' || operation.kind === 'softBreak') {
    if (!owner || (line.marker && start < owner.body)) return null
    if (operation.kind === 'softBreak') return replace(value, start, end, '\n' + ' '.repeat(columns(prefix(owner))))
    if (!Number.isSafeInteger(owner.number + 1)) return null
    const text = '\n' + prefix(owner, owner.number + 1)
    return replace(value, start, end, text, [{ offset: 1 + owner.indent.length + owner.opening.length, group: owner.group }], true)
  }
  if (start !== end) return replace(value, start, end, '')
  if (operation.kind === 'backspace' && line?.marker && (start === line.start || start === line.marker.body)) {
    const previous = markers[markers.indexOf(line.marker) - 1]
    if (previous?.group === line.marker.group) return replace(value, line.start - 1, line.marker.body, '', [], true)
    return replace(value, line.start, line.marker.body, '', [], true)
  }
  if (operation.kind === 'backspace' && owner && !line.marker) {
    const body = line.start + /^[ \t]*/.exec(line.text)![0].length
    if (start === line.start || start === body) return replace(value, line.start - 1, body, '')
  }
  if (operation.kind === 'delete' && start === line?.end) {
    const following = lines[index + 1], next = following?.marker
    if (owner && next && owner.group === next.group) return replace(value, start, next.body, '', [], true)
    if (owner && following?.owner === owner) return replace(value, start, following.start + /^[ \t]*/.exec(following.text)![0].length, '')
  }
  return null
}

export function reconcileNumberedInput(before: string, after: string, start: number, end: number, inputType = ''): TextSelection {
  if ((inputType === 'insertLineBreak' || inputType === 'insertParagraph') && start === end && after[start - 1] === '\n') {
    const position = start - 1, replacedEnd = position + before.length - after.length + 1
    return editNumberedText(before, position, replacedEnd, { kind: 'enter' }) || { value: after, start, end }
  }
  if (before.length - after.length === 1 && start === end) {
    const position = inputType === 'deleteContentBackward' ? start + 1 : start
    if (inputType === 'deleteContentBackward' || inputType === 'deleteContentForward') {
      const merged = editNumberedText(before, position, position, { kind: inputType === 'deleteContentBackward' ? 'backspace' : 'delete' })
      if (merged) return merged
    }
  }
  let from = 0, oldEnd = before.length, newEnd = after.length
  while (from < oldEnd && from < newEnd && before[from] === after[from]) from++
  while (oldEnd > from && newEnd > from && before[oldEnd - 1] === after[newEnd - 1]) { oldEnd--; newEnd-- }
  const text = after.slice(from, newEnd)
  if (inputType !== 'insertFromPaste' && inputType !== 'insertFromDrop') return replace(before, from, oldEnd, text, [], false, { start, end })
  const result = editNumberedText(before, from, oldEnd, { kind: 'paste', text })!
  const map = (position: number) => {
    if (result.value === after) return position
    if (position === newEnd) return result.start
    return position < from ? position : Math.max(from, position + result.value.length - after.length)
  }
  return { value: result.value, start: map(start), end: map(end) }
}

export function moveNumberedText(value: string, start: number, end: number, target: number): TextSelection {
  if (target >= start && target <= end) return { value, start, end }
  const text = value.slice(start, end)
  const from = end === value.length && start > 0 && value[start - 1] === '\n' ? start - 1 : start
  const position = target > end ? target - (end - from) : target
  const removed = replace(value, from, end, '', [], true, { start: position, end: position })
  return editNumberedText(removed.value, removed.start, removed.end, { kind: 'paste', text })!
}

export function numberedLineBreak(value: string, start: number, end: number): { value: string; caret: number } | null {
  const result = editNumberedText(value, start, end, { kind: 'enter' })
  return result ? { value: result.value, caret: result.start } : null
}
