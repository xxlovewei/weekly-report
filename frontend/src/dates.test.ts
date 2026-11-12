import { describe, expect, it } from 'vitest'
import { addDays, mondayOf, monthGrid, weekOfMonth } from './dates'

describe('Monday-based calendar', () => {
  it('handles Sunday, month and year boundaries', () => {
    expect(mondayOf('2027-01-03')).toBe('2026-12-28')
    expect(addDays('2026-12-28', 7)).toBe('2027-01-04')
    expect(monthGrid(2027, 1)[0]).toBe('2026-12-28')
  })

  it('counts the partial first row when a month starts on a Sunday', () => {
    expect(weekOfMonth('2026-11-02')).toBe(2)
    expect(weekOfMonth('2026-11-30')).toBe(6)
    expect(weekOfMonth('2026-12-07')).toBe(2)
    expect(weekOfMonth('2027-02-01')).toBe(1)
  })
})

