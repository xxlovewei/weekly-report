import { describe, expect, it } from 'vitest'
import { editNumberedText, moveNumberedText, reconcileNumberedInput } from './numberedLines'

describe('numbered text editing', () => {
  it.each([
    ['1. A\n2. B\n3. C', '1. AB\n2. C'],
    ['1、A\n2、B\n3、C', '1、AB\n2、C'],
    ['（1）A\n（2）B\n（3）C', '（1）AB\n（2）C'],
    ['09. A\n10. B\n11. C', '09. AB\n10. C'],
  ])('Backspace at the body start joins items and decrements the suffix: %s', (value, expected) => {
    const position = value.indexOf('B')
    expect(editNumberedText(value, position, position, { kind: 'backspace' })?.value).toBe(expected)
  })

  it('joins an empty item before Backspace can erase its marker', () => {
    expect(editNumberedText('1. A\n2. \n3. C', 8, 8, { kind: 'backspace' })).toEqual({ value: '1. A\n2. C', start: 4, end: 4 })
    expect(reconcileNumberedInput('1. A\n2. \n3. C', '1. A\n2.\n3. C', 7, 7, 'deleteContentBackward').value).toBe('1. A\n2. C')
  })

  it('Backspace at continuation body start removes only its formatting and line break', () => {
    expect(editNumberedText('1. A\n   B\n2. C', 8, 8, { kind: 'backspace' })?.value).toBe('1. AB\n2. C')
  })

  it('does not merge a restarted group into the previous group', () => {
    expect(editNumberedText('1. A\n7. B\n8. C', 8, 8, { kind: 'backspace' })?.value).toBe('1. A\nB\n7. C')
    expect(editNumberedText('1. A\n12. B\n13. C', 6, 6, { kind: 'backspace' })).toBeNull()
  })

  it.each([
    ['1. A\n2. B\n3. C', 4, 'enter', '1. A\n2. \n3. B\n4. C'],
    ['1. AB\n2. C', 4, 'enter', '1. A\n2. B\n3. C'],
    ['1. A\n2. B', 3, 'enter', '1. \n2. A\n3. B'],
    ['1. \n2. B', 3, 'enter', '1. \n2. \n3. B'],
    ['1. A\n7. B\n8. C', 4, 'enter', '1. A\n2. \n7. B\n8. C'],
    ['1. A\n2、B', 4, 'enter', '1. A\n2. \n2、B'],
    ['9. A\n10. B', 4, 'enter', '9. A\n10. \n11. B'],
    ['099. A\n100. B', 6, 'enter', '099. A\n100. \n101. B'],
    ['1. A\n2. B', 4, 'softBreak', '1. A\n   \n2. B'],
    ['1. A\n   BC\n2. D', 9, 'enter', '1. A\n   B\n2. C\n3. D'],
    ['1. A\n2. B\n3. C', 5, 'backspace', '1. AB\n2. C'],
    ['1. A\n2. B\n3. C', 4, 'delete', '1. AB\n2. C'],
    ['5. A\n6. B', 0, 'backspace', 'A\n5. B'],
  ] as const)('%s at %i: %s', (value, position, kind, expected) => {
    expect(editNumberedText(value, position, position, { kind })?.value).toBe(expected)
  })

  it.each([
    [0, 5, '1. B\n2. C'],
    [5, 10, '1. A\n2. C'],
    [4, 9, '1. A\n2. C'],
    [4, 13, '1. AC'],
    [0, 14, ''],
  ])('deletes selected items %i..%i', (start, end, expected) => {
    expect(editNumberedText('1. A\n2. B\n3. C', start, end, { kind: 'replace', text: '' })?.value).toBe(expected)
  })

  it('cuts an item including its continuation', () => {
    const value = '5. A\n   details\n6. B\n7. C'
    expect(editNumberedText(value, 0, value.indexOf('6.'), { kind: 'replace', text: '' })?.value).toBe('5. B\n6. C')
  })

  it('renumbers independently across an ordinary paragraph', () => {
    const value = '1. A\n2. B\n说明\n5. C\n6. D'
    expect(editNumberedText(value, 5, value.indexOf('6.'), { kind: 'replace', text: '' })?.value).toBe('1. A\n5. D')
  })

  it('inserts a matching pasted list at an item boundary', () => {
    expect(editNumberedText('5. A\n6. B', 5, 5, { kind: 'paste', text: '1. X\n2. Y' })?.value).toBe('5. A\n6. X\n7. Y\n8. B')
    expect(editNumberedText('5. A\n6. B', 4, 4, { kind: 'paste', text: '1. X\n2. Y\n' })?.value).toBe('5. A\n6. X\n7. Y\n8. B')
  })

  it('preserves nonmatching pasted text and manual number edits', () => {
    expect(editNumberedText('1. A\n2. B', 5, 5, { kind: 'paste', text: '7、X\n' })?.value).toBe('1. A\n7、X\n2. B')
    expect(editNumberedText('1. A\n2. B\n3. C', 5, 6, { kind: 'replace', text: '7' })?.value).toBe('1. A\n7. B\n3. C')
  })

  it('preserves caret when numbers gain digits before it', () => {
    const value = '9. A\n10. B\n11. C'
    const result = editNumberedText(value, 5, 11, { kind: 'replace', text: '' })!
    expect(result.value).toBe('9. A\n10. C')
    expect(result.start).toBe(5)
  })

  it('reconciles native selection deletion without beforeinput', () => {
    expect(reconcileNumberedInput('1. A\n2. B\n3. C', '1. A\n3. C', 5, 5, 'deleteByCut').value).toBe('1. A\n2. C')
  })

  it('reconciles native Enter and merging without beforeinput', () => {
    expect(reconcileNumberedInput('1. A\n2. B', '1. A\n\n2. B', 5, 5, 'insertLineBreak').value).toBe('1. A\n2. \n3. B')
    expect(reconcileNumberedInput('1. A\n2. B', '1. A2. B', 4, 4, 'deleteContentBackward').value).toBe('1. AB')
  })

  it('does not interpret decimals, ordinary text or prefix edits as numbered Enter', () => {
    expect(editNumberedText('1.5版本', 5, 5, { kind: 'enter' })).toBeNull()
    expect(editNumberedText('12. A', 1, 1, { kind: 'enter' })).toBeNull()
    expect(editNumberedText('普通文字', 4, 4, { kind: 'enter' })).toBeNull()
  })

  it('keeps continuations aligned when the number gains or loses a digit', () => {
    expect(editNumberedText('8. A\n9. B\n   details\n10. C', 4, 4, { kind: 'enter' })?.value).toBe('8. A\n9. \n10. B\n    details\n11. C')
    expect(editNumberedText('9. A\n10. B\n    details\n11. C', 0, 5, { kind: 'replace', text: '' })?.value).toBe('9. B\n   details\n10. C')
  })

  it('merges a continuation without keeping its formatting indentation', () => {
    expect(editNumberedText('1. A\n   B\n2. C', 4, 4, { kind: 'delete' })?.value).toBe('1. AB\n2. C')
    expect(editNumberedText('1. A\n   B\n2. C', 5, 5, { kind: 'backspace' })?.value).toBe('1. AB\n2. C')
  })

  it('moves an entire item up or down as one edit', () => {
    expect(moveNumberedText('1. A\n2. B\n3. C', 5, 10, 14).value).toBe('1. A\n2. C\n3. B')
    expect(moveNumberedText('1. A\n2. B\n3. C', 10, 14, 0).value).toBe('1. C\n2. A\n3. B')
  })
})
