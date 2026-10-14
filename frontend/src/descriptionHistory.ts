import type { TextSelection } from './numberedLines'

type Transaction = { before: TextSelection; after: TextSelection; kind: string; time: number }

export class DescriptionHistory {
  private past: Transaction[] = []
  private future: Transaction[] = []
  get canUndo() { return this.past.length > 0 }
  get canRedo() { return this.future.length > 0 }
  clear() { this.past = []; this.future = [] }
  record(before: TextSelection, after: TextSelection, kind: string, time = Date.now()) {
    if (before.value === after.value) return
    const last = this.past.at(-1)
    if (kind === 'typing' && last?.kind === kind && !this.future.length && time - last.time < 500
      && last.after.value === before.value && last.after.start === before.start && last.after.end === before.end) {
      last.after = { ...after }; last.time = time
    } else {
      this.past.push({ before: { ...before }, after: { ...after }, kind, time })
      if (this.past.length > 100) this.past.shift()
    }
    this.future = []
  }
  undo(): TextSelection | null {
    const transaction = this.past.pop()
    if (!transaction) return null
    this.future.push(transaction)
    return { ...transaction.before }
  }
  redo(): TextSelection | null {
    const transaction = this.future.pop()
    if (!transaction) return null
    this.past.push(transaction)
    return { ...transaction.after }
  }
}
