import { describe, expect, it } from 'vitest'
import { moveReportTab, restoreReportTabOrder } from './reportTabOrder'

const tabs = [{ id: 1 }, { id: 2 }, { id: 3 }]

describe('report tab order', () => {
  it('moves a dragged member before or after the drop target', () => {
    expect(moveReportTab(tabs, 3, 1, false).map(tab => tab.id)).toEqual([3, 1, 2])
    expect(moveReportTab(tabs, 1, 3, true).map(tab => tab.id)).toEqual([2, 3, 1])
  })

  it('restores saved members first and appends newly available members', () => {
    expect(restoreReportTabOrder(tabs, [3, 1]).map(tab => tab.id)).toEqual([3, 1, 2])
  })
})
