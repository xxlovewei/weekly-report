// 会议任务与本周工作共用完成状态，避免选项不一致。
export const taskStatuses = ['已完成', '90%', '80%', '70%', '60%', '50%', '40%', '30%', '20%', '10%', '5%']

// 周报汇总与会议跟踪任务共用百分比填充及颜色规则。
export function progressStyle(status: string | null) {
  if (!status || !/^\d+%$/.test(status)) return
  const progress = Math.min(100, Number.parseInt(status))
  // 进度决定填充宽度，填充色随完成度加深，并保持黑字清晰可读。
  return { background: `linear-gradient(to right, hsl(210 85% ${90 - progress * 0.4}%) ${progress}%, #eef7ff ${progress}%)` }
}
