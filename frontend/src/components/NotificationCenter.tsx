import { useEffect, useRef, useState } from 'react'
import { Bell, Bookmark, CheckCheck } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useNotifications, useReadAllNotifications, useReadNotification, useToggleNotificationPriority, UserNotification } from '../api/enterprise'
import { InlinePending, QueryRegion, Skeleton } from './Loading'

function relativeTime(value: string) {
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 60_000))
  if (minutes < 1) return 'Одоо'
  if (minutes < 60) return `${minutes} мин`
  if (minutes < 1440) return `${Math.floor(minutes / 60)} цаг`
  return new Date(value).toLocaleDateString('mn-MN', { month: 'short', day: 'numeric' })
}

export function NotificationCenter() {
  const [open, setOpen] = useState(false)
  const [priorityOnly, setPriorityOnly] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const notifications = useNotifications()
  const readOne = useReadNotification()
  const readAll = useReadAllNotifications()
  const togglePriority = useToggleNotificationPriority()

  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false) }
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', escape) }
  }, [open])

  const openItem = async (item: UserNotification) => {
    if (!item.read_at) await readOne.mutateAsync(item.id)
    setOpen(false)
    if (item.target_url) navigate(item.target_url)
  }

  const unread = notifications.data?.unread_count ?? 0
  const items = notifications.data?.items ?? []
  const visibleItems = priorityOnly ? items.filter((item) => item.is_priority) : items
  return <div className="notification-center" ref={root}>
    <button className="notification-trigger" onClick={() => setOpen((value) => !value)} aria-label={`Мэдэгдэл${unread ? `, ${unread} уншаагүй` : ''}`} aria-expanded={open}>
      <Bell size={17} />{unread > 0 && <span>{unread > 9 ? '9+' : unread}</span>}
    </button>
    {open && <section className="notification-popover" role="dialog" aria-label="Мэдэгдлүүд">
      <header><div><span className="eyebrow">Activity</span><h2>Мэдэгдэл</h2></div>{unread > 0 && <button onClick={() => readAll.mutate()} disabled={readAll.isPending}><CheckCheck size={15} />Бүгдийг унших{readAll.isPending && <InlinePending label="Мэдэгдлүүдийг уншсан болгож байна…" />}</button>}</header>
      <nav className="notification-filters" aria-label="Мэдэгдлийн шүүлтүүр"><button className={!priorityOnly ? 'active' : ''} onClick={() => setPriorityOnly(false)} aria-pressed={!priorityOnly}>Бүгд</button><button className={priorityOnly ? 'active' : ''} onClick={() => setPriorityOnly(true)} aria-pressed={priorityOnly}><Bookmark size={13} />Чухал</button></nav>
      <div className="notification-list">
        {notifications.isLoading && <QueryRegion pending={notifications.isLoading} skeleton={<Skeleton variant="table-row" count={4} />}>{null}</QueryRegion>}
        {notifications.isError && <p>Мэдэгдэл ачаалж чадсангүй.</p>}
        {!notifications.isLoading && !visibleItems.length && <p>{priorityOnly ? 'Чухал мэдэгдэл алга.' : 'Шинэ мэдэгдэл алга.'}</p>}
        {visibleItems.map((item) => <div key={item.id} className={`notification-item ${item.read_at ? '' : 'unread'}`}>
          <button className="notification-item-main" onClick={() => openItem(item)}><i aria-hidden /><span><strong>{item.title}</strong><p>{item.body}</p><small>{relativeTime(item.created_at)} · Telegram: {item.telegram_status === 'sent' ? 'илгээгдсэн' : item.telegram_status === 'queued' ? 'хүлээгдэж байна' : item.telegram_status === 'failed' ? 'алдаа' : 'холбогдоогүй'}</small></span></button>
          <button className={`notification-priority ${item.is_priority ? 'active' : ''}`} onClick={() => togglePriority.mutate({ id: item.id, is_priority: !item.is_priority })} aria-label={item.is_priority ? 'Чухал төлөвийг болиулах' : 'Чухал гэж тэмдэглэх'} aria-pressed={item.is_priority}><Bookmark size={17} fill={item.is_priority ? 'currentColor' : 'none'} /></button>
        </div>)}
      </div>
    </section>}
  </div>
}
