import { driver, type DriveStep } from 'driver.js'
import 'driver.js/dist/driver.css'
import { nextTick } from 'vue'

const menuDescriptions = {
  work: '查看和填写所选周的个人工作。收起侧栏时，鼠标悬停在菜单图标上即可查看名称。',
  reports: '查看所选周的成员周报。此页还提供新增或修改当天周会记录的快捷入口。',
  categories: '查看和维护填写周报时使用的任务类型。',
  meetings: '查看、新增和编辑会议记录，并跟踪关联任务的完成情况。',
  users: '管理员可在这里管理用户账号、账号状态和密码重置。',
}

interface SidebarTourOptions {
  menu: ReadonlyArray<{ name: keyof typeof menuDescriptions; label: string }>
  showMeetingShortcut: boolean
  setCollapsed: (collapsed: boolean) => void
  onShown: () => void
  onClosed: (completed: boolean) => void
}

function step(target: string, title: string, description: string): DriveStep {
  return {
    element: `.sidebar [data-sidebar-tour="${target}"]`,
    popover: { title, description, side: 'right', align: 'start' },
  }
}

export function startSidebarTour(options: SidebarTourOptions) {
  let shown = false
  const tour = driver({
    animate: !window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    duration: 160,
    closeBtnLabel: '跳过引导',
    prevBtnText: '上一步',
    nextBtnText: '下一步',
    progressText: '{{current}} / {{total}}',
    showProgress: true,
    stagePadding: 4,
    popoverClass: 'sidebar-tour-popover',
    overlayClickBehavior: 'none',
    disableActiveInteraction: true,
    onPopoverRender: popover => {
      popover.closeButton.title = '跳过引导'
      if (shown) return
      shown = true
      options.onShown()
    },
    onDestroyStarted: (_element, _step, { reason }) => closeTour(reason === 'done'),
  })

  // 即使在步骤切换动画中跳过，也要恢复侧栏布局。
  function closeTour(completed = false) {
    tour.destroy()
    options.onClosed(completed)
  }

  // 先更新侧栏布局，再让 Driver.js 定位折叠或展开后的控件。
  async function changeLayout(collapsed: boolean, move: () => void) {
    const index = tour.getActiveIndex()
    options.setCollapsed(collapsed)
    await nextTick()
    if (tour.isActive() && tour.getActiveIndex() === index) move()
  }

  const collapse = step('toggle', '收起侧栏', '点击高亮的左箭头收起侧栏，为工作区腾出空间。')
  collapse.disableActiveInteraction = false
  collapse.advanceOn = 'click'
  collapse.popover = { ...collapse.popover, nextBtnText: '收起侧栏', onNextClick: () => changeLayout(true, tour.moveNext) }

  const releaseNotes = step('release-notes', '查看版本更新内容', '将鼠标移到高亮的版本号上，即可查看本次更新。也可以用 Tab 聚焦版本号。')
  releaseNotes.disableActiveInteraction = false
  releaseNotes.allowedElements = '.sidebar .release-notes [role="tooltip"]'
  releaseNotes.popover = { ...releaseNotes.popover, onPrevClick: () => changeLayout(false, tour.movePrevious) }

  const expand = step('toggle', '展开侧栏', '点击高亮的右箭头恢复完整菜单和月历。')
  expand.disableActiveInteraction = false
  expand.advanceOn = 'click'
  expand.popover = { ...expand.popover, doneBtnText: '展开侧栏', onDoneClick: () => changeLayout(false, () => closeTour(true)) }

  const steps = [
    collapse,
    releaseNotes,
    ...options.menu.map(item => step(item.name, item.label, menuDescriptions[item.name])),
    step('current-week', '回到本周', '返回今天所在的一周。折叠月历显示所选周的月份，底部显示它在该月是第几周。'),
    step('previous-week', '上一周', '切换到所选周的前一周，工作区会显示那一周的数据。'),
    step('next-week', '下一周', '切换到所选周的后一周，跨月时会更新月份和周数。'),
  ]
  if (options.showMeetingShortcut) steps.push(step('meeting-shortcut', '周会快捷入口', '在周报汇总中可新增当天周会记录。如果已有记录，点击即可编辑。'))
  steps.push(
    step('password', '修改密码', '打开修改密码页面。'),
    step('logout', '退出登录', '退出当前账号并返回登录页面。'),
    expand,
  )
  tour.setSteps(steps)
  tour.drive()
  return () => { if (tour.isActive()) closeTour() }
}
