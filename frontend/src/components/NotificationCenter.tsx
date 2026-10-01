import { useEffect, useRef, useState } from 'react'
import { Bell, Bookmark, CheckCheck } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { useNotifications, useReadAllNotifications, useReadNotification, useToggleNotificationPriority, UserNotification } from '../api/enterprise'
import { InlinePending, QueryRegion, Skeleton, toQueryRegionState } from './Loading'
import { intlLocale } from '../utils/locale'

function relativeTime(value: string, t: TFunction) {
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 60_000))
  if (minutes < 1) return t('notifications.now')
  if (minutes < 60) return t('notifications.minutes', { n: minutes })
  if (minutes < 1440) return t('notifications.hours', { n: Math.floor(minutes / 60) })
  return new Date(value).toLocaleDateString(intlLocale(), { month: 'short', day: 'numeric' })
}

export function NotificationCenter({ initialOpen = false, standalone = false, onClose }: { initialOpen?: boolean; standalone?: boolean; onClose?: () => void } = {}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(initialOpen)
  const [priorityOnly, setPriorityOnly] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const notifications = useNotifications()
  const readOne = useReadNotification()
  const readAll = useReadAllNotifications()
  const togglePriority = useToggleNotificationPriority()

  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent) => { if (!root.current?.contains(event.target as Node)) { setOpen(false); onClose?.() } }
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') { setOpen(false); onClose?.() } }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', escape) }
  }, [onClose, open])

  const openItem = async (item: UserNotification) => {
    if (!item.read_at) await readOne.mutateAsync(item.id)
    setOpen(false)
    onClose?.()
    if (item.target_url) navigate(item.target_url)
  }

  const unread = notifications.data?.unread_count ?? 0
  const items = notifications.data?.items ?? []
  const visibleItems = priorityOnly ? items.filter((item) => item.is_priority) : items
  return <div className={`notification-center${standalone ? ' notification-center-standalone' : ''}`} ref={root}>
    {!standalone && <button className="notification-trigger" onClick={() => setOpen((value) => !value)} aria-label={unread ? t('notifications.triggerUnread', { n: unread }) : t('notifications.trigger')} aria-expanded={open}>
      <Bell size={17} />{unread > 0 && <span>{unread > 9 ? '9+' : unread}</span>}
    </button>}
    {open && <section className="notification-popover" role="dialog" aria-label={t('notifications.dialog')}>
      <header><div><span className="eyebrow">{t('notifications.eyebrow')}</span><h2>{t('notifications.title')}</h2></div>{unread > 0 && <button onClick={() => readAll.mutate()} disabled={readAll.isPending}><CheckCheck size={15} />{t('notifications.readAll')}{readAll.isPending && <InlinePending label={t('notifications.readAllPending')} />}</button>}</header>
      <nav className="notification-filters" aria-label={t('notifications.filters')}><button className={!priorityOnly ? 'active' : ''} onClick={() => setPriorityOnly(false)} aria-pressed={!priorityOnly}>{t('notifications.all')}</button><button className={priorityOnly ? 'active' : ''} onClick={() => setPriorityOnly(true)} aria-pressed={priorityOnly}><Bookmark size={13} />{t('notifications.priority')}</button></nav>
      <div className="notification-list">
        <QueryRegion state={toQueryRegionState(notifications)} empty={Boolean(notifications.data && !visibleItems.length)} emptyFallback={<p>{priorityOnly ? t('notifications.emptyPriority') : t('notifications.empty')}</p>} errorFallback={() => <p role="alert">{t('notifications.loadFailed')}</p>} skeleton={<Skeleton variant="table-row" count={4} />}>
          {visibleItems.length ? <>{visibleItems.map((item) => <div key={item.id} className={`notification-item ${item.read_at ? '' : 'unread'}`}>
          <button className="notification-item-main" onClick={() => openItem(item)}><i aria-hidden /><span><strong>{item.title}</strong><p>{item.body}</p><small>{relativeTime(item.created_at, t)} · {t('notifications.telegram', { status: t(`notifications.telegramStatus.${['sent', 'queued', 'failed'].includes(item.telegram_status) ? item.telegram_status : 'none'}`) })}</small></span></button>
          <button className={`notification-priority ${item.is_priority ? 'active' : ''}`} onClick={() => togglePriority.mutate({ id: item.id, is_priority: !item.is_priority })} aria-label={t(item.is_priority ? 'notifications.unmarkPriority' : 'notifications.markPriority')} aria-pressed={item.is_priority}><Bookmark size={17} fill={item.is_priority ? 'currentColor' : 'none'} /></button>
        </div>)}</> : null}
        </QueryRegion>
      </div>
    </section>}
  </div>
}
