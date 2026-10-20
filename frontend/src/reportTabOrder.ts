export function restoreReportTabOrder<T extends { id: number }>(tabs: T[], savedIds: number[]) {
  const positions = new Map(savedIds.map((id, index) => [id, index]))
  return [...tabs].sort((a, b) => (positions.get(a.id) ?? Infinity) - (positions.get(b.id) ?? Infinity))
}

export function moveReportTab<T extends { id: number }>(tabs: T[], draggedId: number, targetId: number, after: boolean) {
  const from = tabs.findIndex(tab => tab.id === draggedId), target = tabs.findIndex(tab => tab.id === targetId)
  if (from < 0 || target < 0 || from === target) return tabs
  const next = [...tabs]
  const [moved] = next.splice(from, 1)
  const destination = next.findIndex(tab => tab.id === targetId)
  next.splice(destination + Number(after), 0, moved)
  return next
}
