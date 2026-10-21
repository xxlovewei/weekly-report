import { describe, expect, it } from 'vitest'
import * as XLSX from 'xlsx-js-style'
import { mondayToWeekInput, weekInputToMonday, weeksInRange } from './dates'
import { createReportWorkbook } from './reportExport'

describe('report export', () => {
  it('converts ISO week inputs and includes both ends of the selected range', () => {
    expect(weekInputToMonday('2026-W43')).toBe('2026-10-19')
    expect(mondayToWeekInput('2027-01-04')).toBe('2027-W01')
    expect(weekInputToMonday('2021-W53')).toBeNull()
    expect(weeksInRange('2026-12-28', '2027-01-11')).toEqual(['2026-12-28', '2027-01-04', '2027-01-11'])
  })

  it('creates one valid sheet per person and keeps task text as text', () => {
    const workbook = createReportWorkbook([
      { name: '张三/开发', rows: [['2026-10-19', '开发', '客户端', '=1+1\nline two', '未开始', '周一', '']] },
      { name: '张三/开发', rows: [] },
    ])
    expect(workbook.SheetNames).toEqual(['张三 开发', '张三 开发 (2)'])
    const cell = workbook.Sheets['张三 开发']['D2']
    expect(cell.t).toBe('s')
    expect(cell.f).toBeUndefined()
    expect(cell.v).toBe('=1+1\nline two')
    expect(workbook.Sheets['张三 开发']['A1'].v).toBe('周次')
    expect(workbook.Sheets['张三 开发']['A1'].s).toMatchObject({
      font: { sz: 16, bold: true },
      alignment: { horizontal: 'center', vertical: 'center' },
    })
    expect(workbook.Sheets['张三 开发']['F1'].v).toBe('工作日期')
    expect(workbook.Sheets['张三 开发']['!cols']).toHaveLength(7)
    const parsed = XLSX.read(XLSX.write(workbook, { type: 'array', bookType: 'xlsx' }), { type: 'array', cellStyles: true })
    expect(parsed.SheetNames).toHaveLength(2)
    expect(parsed.Sheets['张三 开发']['D2'].v).toBe('=1+1\nline two')
  })
})
