const zone = 'Asia/Shanghai'
const dayFormat = new Intl.DateTimeFormat('en-CA', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit' })
export function todayShanghai() { return dayFormat.format(new Date()) }
export function parseDay(day: string) { return new Date(`${day}T12:00:00Z`) }
export function dayString(day: Date) { return day.toISOString().slice(0, 10) }
export function addDays(day: string, count: number) { const date = parseDay(day); date.setUTCDate(date.getUTCDate() + count); return dayString(date) }
export function mondayOf(day: string) { const weekday = parseDay(day).getUTCDay(); return addDays(day, -(weekday === 0 ? 6 : weekday - 1)) }
export function monthGrid(year: number, month: number) {
  const first = dayString(new Date(Date.UTC(year, month - 1, 1, 12)))
  const start = mondayOf(first)
  return Array.from({ length: 42 }, (_, i) => addDays(start, i))
}
