import { describe, expect, it } from 'vitest'
import { addDays, mondayOf, monthGrid } from './dates'

describe('Monday-based calendar', () => {
  it('handles Sunday, month and year boundaries', () => {
    expect(mondayOf('2027-01-03')).toBe('2026-12-28')
    expect(addDays('2026-12-28', 7)).toBe('2027-01-04')
    expect(monthGrid(2027, 1)[0]).toBe('2026-12-28')
  })
})

