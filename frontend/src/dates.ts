const zone = 'Asia/Shanghai'
const dayFormat = new Intl.DateTimeFormat('en-CA', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit' })
export function todayShanghai() { return dayFormat.format(new Date()) }
export function parseDay(day: string) { return new Date(`${day}T12:00:00Z`) }
export function dayString(day: Date) { return day.toISOString().slice(0, 10) }
export function addDays(day: string, count: number) { const date = parseDay(day); date.setUTCDate(date.getUTCDate() + count); return dayString(date) }
export function mondayOf(day: string) { const weekday = parseDay(day).getUTCDay(); return addDays(day, -(weekday === 0 ? 6 : weekday - 1)) }
export function weekInputToMonday(value: string) {
  const match = /^(\d{4})-W(\d{2})$/.exec(value)
  if (!match) return null
  const year = Number(match[1]), week = Number(match[2])
  if (week < 1 || week > 53) return null
  const monday = addDays(mondayOf(`${year}-01-04`), (week - 1) * 7)
  return addDays(monday, 3).slice(0, 4) === String(year) ? monday : null
}
export function mondayToWeekInput(monday: string) {
  const year = addDays(monday, 3).slice(0, 4)
  const firstMonday = mondayOf(`${year}-01-04`)
  const week = Math.floor((Date.parse(`${monday}T12:00:00Z`) - Date.parse(`${firstMonday}T12:00:00Z`)) / 604800000) + 1
  return `${year}-W${String(week).padStart(2, '0')}`
}
export function weeksInRange(start: string, end: string) {
  if (start > end || mondayOf(start) !== start || mondayOf(end) !== end) return []
  const weeks: string[] = []
  for (let week = start; week <= end; week = addDays(week, 7)) weeks.push(week)
  return weeks
}
export function monthGrid(year: number, month: number) {
  const first = dayString(new Date(Date.UTC(year, month - 1, 1, 12)))
  const start = mondayOf(first)
  return Array.from({ length: 42 }, (_, i) => addDays(start, i))
}
