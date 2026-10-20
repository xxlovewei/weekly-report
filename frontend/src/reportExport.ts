import * as XLSX from 'xlsx-js-style'

export interface ReportExportSheet { name: string; rows: (string | number)[][] }

function limitSheetName(value: string, limit: number) {
  let result = ''
  for (const character of value) {
    if (result.length + character.length > limit) break
    result += character
  }
  return result
}

export function createReportWorkbook(people: ReportExportSheet[]) {
  const workbook = XLSX.utils.book_new()
  const usedNames = new Set<string>()
  const headers = ['周次', '任务类型', '任务大类', '任务描述', '完成状态', '工作日期', '备注']
  for (const person of people) {
    const base = limitSheetName(person.name.replace(/[\\/:?*\[\]]/g, ' ').replace(/^'+|'+$/g, '').trim() || '未命名', 31)
    let name = base, suffix = 2
    while (usedNames.has(name.toLowerCase())) {
      const ending = ` (${suffix++})`
      name = limitSheetName(base, 31 - ending.length) + ending
    }
    usedNames.add(name.toLowerCase())
    const sheet = XLSX.utils.aoa_to_sheet([headers, ...person.rows])
    headers.forEach((_, column) => {
      sheet[XLSX.utils.encode_cell({ r: 0, c: column })].s = {
        font: { sz: 16, bold: true },
        alignment: { horizontal: 'center', vertical: 'center' },
      }
    })
    sheet['!cols'] = [12, 16, 20, 60, 14, 18, 40].map(wch => ({ wch }))
    XLSX.utils.book_append_sheet(workbook, sheet, name)
  }
  return workbook
}

export function downloadReportWorkbook(people: ReportExportSheet[], filename: string) {
  XLSX.writeFile(createReportWorkbook(people), filename, { compression: true })
}
