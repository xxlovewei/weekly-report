import type { LiveMessage } from './types'

interface Snapshot {
  count: number
  messages: LiveMessage[]
}

const titles: Record<LiveMessage['kind'], string> = {
  转交任务: '来活了📝！请及时查收📩',
  代码审查: '来bug了⚠️！请及时查收📩',
}

export function desktopNotificationPermission(): NotificationPermission | 'unsupported' {
  return window.isSecureContext && typeof Notification !== 'undefined'
    ? Notification.permission : 'unsupported'
}

export function subscribeToMessages(
  account: number,
  onSnapshot: (count: number) => void,
  onNewMessage: (message: LiveMessage) => void,
  onClick: (message: LiveMessage) => Promise<void>,
) {
  const stream = new EventSource(`${import.meta.env.BASE_URL}api/notifications/stream`)
  const displayed = new Set<Notification>()
  let closed = false
  let lastMessageId = 0
  const key = `zhoubao.notification.${import.meta.env.BASE_URL}.${account}`

  function show(message: LiveMessage, unreadCount?: number) {
    if (closed || desktopNotificationPermission() !== 'granted') return
    if (unreadCount === undefined) {
      try {
        // 同账号的多个标签页只展示一次即时通知。
        if (Number(localStorage.getItem(key)) >= message.id) return
      } catch { /* 隐私模式下仍允许展示通知。 */ }
    }
    try {
      const notification = new Notification(unreadCount === undefined ? titles[message.kind] : `你有 ${unreadCount} 条未读消息`, {
        body: message.title || '点击可直接跳转查看',
        // 定时提醒使用固定标签，未读消息跨轮询仍可再次提醒。
        tag: unreadCount === undefined ? `${key}.${message.id}` : `${key}.unread`,
      })
      displayed.add(notification)
      notification.onclose = () => displayed.delete(notification)
      notification.onclick = event => {
        event.preventDefault()
        notification.close()
        window.focus()
        if (!closed) void onClick(message)
      }
      if (unreadCount === undefined) {
        try { localStorage.setItem(key, String(message.id)) } catch { /* 标签页内的去重仍由事件游标处理。 */ }
      }
    } catch { /* 系统通知失败时继续接收消息流。 */ }
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
    onSnapshot(snapshot.count)
    for (const message of snapshot.messages) {
      // SSE 按消息编号递增发送，同一标签页只展示一次。
      if (message.id <= lastMessageId) continue
      lastMessageId = message.id
      if (message.is_read) continue
      if (desktopNotificationPermission() !== 'granted') {
        onNewMessage(message)
        continue
      }
      if (navigator.locks) void navigator.locks.request(key, () => show(message)).catch(() => show(message))
      else show(message)
    }
  }
  stream.addEventListener('session-ended', stop)
  return { stop, remindUnread: show }
}
