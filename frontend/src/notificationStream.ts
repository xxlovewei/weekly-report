import { version } from '../package.json'
import type { LiveMessage, ScheduleSettings } from './types'

interface Snapshot {
  count: number
  messages: LiveMessage[]
  unread_reminder: ScheduleSettings
  release?: { version: string; message: string } | null
}

const titles: Record<LiveMessage['kind'], string> = {
  转交任务: '来活了📝！请及时查收📩',
  会议指派: '收到会议指派📋',
  代码审查: '来bug了⚠️！请及时查收📩',
  系统通知: '系统通知',
  发版检查: '收到发版检查任务',
}

export function desktopNotificationPermission(): NotificationPermission | 'unsupported' {
  return window.isSecureContext && typeof Notification !== 'undefined'
    ? Notification.permission : 'unsupported'
}

export function subscribeToMessages(
  account: number,
  onSnapshot: (count: number, schedule: ScheduleSettings) => void,
  onNewMessage: (message: LiveMessage) => void,
  onClick: (message: LiveMessage) => Promise<void>,
  onRelease: (version: string) => void,
) {
  const stream = new EventSource(`${import.meta.env.BASE_URL}api/notifications/stream?client_version=${version}`)
  const displayed = new Set<Notification>()
  let closed = false
  let lastMessageId = 0
  let announcedVersion: string | undefined
  const key = `zhoubao.notification.${import.meta.env.BASE_URL}.${account}`
  const releaseKey = `${key}.release`

  function showDesktop(title: string, options: NotificationOptions, open: () => void) {
    if (closed || desktopNotificationPermission() !== 'granted') return false
    try {
      const notification = new Notification(title, options)
      displayed.add(notification)
      notification.onclose = () => displayed.delete(notification)
      notification.onclick = event => {
        event.preventDefault()
        notification.close()
        if (closed) return
        window.focus()
        open()
      }
      return true
    } catch { return false }
  }

  function notifyRelease(releaseVersion: string) {
    if (announcedVersion !== releaseVersion) return
    try {
      // 每个浏览器账号只弹一次桌面提醒，各页签仍独立展示页面提示。
      if (localStorage.getItem(releaseKey) === releaseVersion) return
    } catch { /* 储存不可用时，使用浏览器的通知标签合并提醒。 */ }
    if (showDesktop('🎉 周报系统已更新', {
      body: `v${releaseVersion} 已就绪，点击返回周报系统查看更新提示。`,
      tag: releaseKey,
    }, () => onRelease(announcedVersion ?? releaseVersion))) {
      try { localStorage.setItem(releaseKey, releaseVersion) } catch { /* 页面提示依然可用。 */ }
    }
  }

  function show(message: LiveMessage, unreadCount?: number) {
    if (closed || desktopNotificationPermission() !== 'granted') return
    if (unreadCount === undefined) {
      try {
        // 同账号的多个标签页只展示一次即时通知。
        if (Number(localStorage.getItem(key)) >= message.id) return
      } catch { /* 隐私模式下仍允许展示通知。 */ }
    }
    const shown = showDesktop(unreadCount === undefined ? titles[message.kind] : `你有 ${unreadCount} 条未读消息`, {
      body: message.title || '点击可直接跳转查看',
      // 定时提醒使用固定标签，未读消息跨轮询仍可再次提醒。
      tag: unreadCount === undefined ? `${key}.${message.id}` : `${key}.unread`,
    }, () => { void onClick(message) })
    if (shown && unreadCount === undefined) {
      try { localStorage.setItem(key, String(message.id)) } catch { /* 标签页内的去重仍由事件游标处理。 */ }
    }
  }

  function stop() {
    closed = true
    stream.close()
    displayed.forEach(notification => notification.close())
    displayed.clear()
  }
  stream.onmessage = event => {
    if (closed) return
    const snapshot: Snapshot = JSON.parse(event.data)
    onSnapshot(snapshot.count, snapshot.unread_reminder)
    if (snapshot.release && snapshot.release.version !== announcedVersion) {
      // 断线重连或消息流刷新不会重新弹出已收到的同版本提醒。
      const releaseVersion = snapshot.release.version
      announcedVersion = releaseVersion
      onRelease(releaseVersion)
      const showRelease = () => notifyRelease(releaseVersion)
      if (navigator.locks) void navigator.locks.request(releaseKey, showRelease).catch(showRelease)
      else showRelease()
    }
    for (const message of snapshot.messages) {
      // SSE 按消息编号递增发送，同一标签页只展示一次。
      if (message.id <= lastMessageId) continue
      lastMessageId = message.id
      if (message.is_read) continue
      const desktopAllowed = desktopNotificationPermission() === 'granted'
      if (!desktopAllowed || message.kind === '发版检查') onNewMessage(message)
      if (!desktopAllowed) continue
      if (navigator.locks) void navigator.locks.request(key, () => show(message)).catch(() => show(message))
      else show(message)
    }
  }
  stream.addEventListener('session-ended', stop)
  return { stop, remindUnread: show }
}
