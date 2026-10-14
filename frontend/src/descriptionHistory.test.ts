import { describe, expect, it } from 'vitest'
import { DescriptionHistory } from './descriptionHistory'

const state = (value: string, start = value.length, end = start) => ({ value, start, end })

describe('description undo history', () => {
  it('undoes a structural edit and numbering as one transaction, restoring selection', () => {
    const history = new DescriptionHistory()
    history.record(state('1. A\n2. B', 4, 4), state('1. A\n2. \n3. B', 8), 'structural', 0)
    expect(history.undo()).toEqual(state('1. A\n2. B', 4, 4))
    expect(history.redo()).toEqual(state('1. A\n2. \n3. B', 8))
  })

  it('coalesces adjacent typing for 500ms and stops at cursor changes', () => {
    const history = new DescriptionHistory()
    history.record(state(''), state('a'), 'typing', 0)
    history.record(state('a'), state('ab'), 'typing', 100)
    history.record(state('ab', 0), state('xab', 1), 'typing', 200)
    expect(history.undo()).toEqual(state('ab', 0))
    expect(history.undo()).toEqual(state(''))
  })

  it('clears redo after a new action and caps history at 100 transactions', () => {
    const history = new DescriptionHistory()
    for (let i = 0; i < 110; i++) history.record(state(String(i)), state(String(i + 1)), 'structural', i)
    for (let i = 0; i < 100; i++) expect(history.undo()).not.toBeNull()
    expect(history.undo()).toBeNull()
    expect(history.redo()).not.toBeNull()
    history.record(state('11'), state('new'), 'structural', 1000)
    expect(history.redo()).toBeNull()
    history.clear()
    expect(history.canUndo).toBe(false)
  })
})
