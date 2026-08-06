import { useEffect, useRef, useState } from 'react'
import { Bell, CheckCheck } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useNotifications, useReadAllNotifications, useReadNotification, UserNotification } from '../api/enterprise'

function relativeTime(value: string) {
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 60_000))
  if (minutes < 1) return 'Одоо'
  if (minutes < 60) return `${minutes} мин`
  if (minutes < 1440) return `${Math.floor(minutes / 60)} цаг`
  return new Date(value).toLocaleDateString('mn-MN', { month: 'short', day: 'numeric' })
}

export function NotificationCenter() {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const notifications = useNotifications()
  const readOne = useReadNotification()
  const readAll = useReadAllNotifications()

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
  return <div className="notification-center" ref={root}>
    <button className="notification-trigger" onClick={() => setOpen((value) => !value)} aria-label={`Мэдэгдэл${unread ? `, ${unread} уншаагүй` : ''}`} aria-expanded={open}>
      <Bell size={17} />{unread > 0 && <span>{unread > 9 ? '9+' : unread}</span>}
    </button>
    {open && <section className="notification-popover" role="dialog" aria-label="Мэдэгдлүүд">
      <header><div><span className="eyebrow">Activity</span><h2>Мэдэгдэл</h2></div>{unread > 0 && <button onClick={() => readAll.mutate()} disabled={readAll.isPending}><CheckCheck size={15} />Бүгдийг унших</button>}</header>
      <div className="notification-list">
        {notifications.isLoading && <p>Мэдэгдэл ачаалж байна…</p>}
        {notifications.isError && <p>Мэдэгдэл ачаалж чадсангүй.</p>}
        {!notifications.isLoading && !notifications.data?.items.length && <p>Шинэ мэдэгдэл алга.</p>}
        {notifications.data?.items.map((item) => <button key={item.id} className={item.read_at ? '' : 'unread'} onClick={() => openItem(item)}>
          <i aria-hidden /><div><strong>{item.title}</strong><p>{item.body}</p><small>{relativeTime(item.created_at)} · Telegram: {item.telegram_status === 'sent' ? 'илгээгдсэн' : item.telegram_status === 'queued' ? 'хүлээгдэж байна' : item.telegram_status === 'failed' ? 'алдаа' : 'холбогдоогүй'}</small></div>
        </button>)}
      </div>
    </section>}
  </div>
}
