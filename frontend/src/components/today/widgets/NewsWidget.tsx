import { lazy, Suspense, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Megaphone, Pin, SquarePen } from 'lucide-react'
import { ANNOUNCEMENT_AUTHOR_ROLES } from '../../../api/announcements'
import { useAnnouncements, type Announcement } from '../../../api/today'
import { safeLocalStorage } from '../../../platform/runtime'
import { useAuthStore } from '../../../store/auth'
import { WidgetHeader } from './shared'

const readKey = (accountId: number | undefined) => `oyuns.news-read:${accountId ?? 'anonymous'}`

function readIds(accountId: number | undefined): Set<string> {
  try {
    return new Set(JSON.parse(safeLocalStorage().get(readKey(accountId)) || '[]'))
  } catch {
    return new Set()
  }
}

// The Markdown renderer is only needed once an article is opened.
const ArticleDialog = lazy(() => import('./NewsArticleDialog').then((module) => ({ default: module.NewsArticleDialog })))

const shortDate = (value: string) => {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : `${String(date.getMonth() + 1).padStart(2, '0')}.${String(date.getDate()).padStart(2, '0')}`
}

/** Company news & announcements: dense one-line rows, full article in a dialog. */
export function NewsWidget() {
  const { t } = useTranslation()
  const accountId = useAuthStore((state) => state.actor?.id)
  const canAuthor = useAuthStore((state) => Boolean(state.actor?.roles.some((role) => ANNOUNCEMENT_AUTHOR_ROLES.includes(role))))
  const news = useAnnouncements()
  const [open, setOpen] = useState<Announcement | null>(null)
  const [read, setRead] = useState(() => readIds(accountId))
  const items = [...(news.data ?? [])].sort((a, b) => Number(Boolean(b.is_pinned)) - Number(Boolean(a.is_pinned)) || b.published_at.localeCompare(a.published_at))
  const unread = items.filter((item) => !read.has(String(item.id))).length

  const openArticle = (article: Announcement) => {
    setOpen(article)
    const next = new Set(read).add(String(article.id))
    setRead(next)
    // Bounded so the stored list does not grow forever.
    safeLocalStorage().set(readKey(accountId), JSON.stringify([...next].slice(-300)))
  }

  return (
    <section className="today-widget today-news" aria-label={t('today.widget.news.title')}>
      <WidgetHeader icon={Megaphone} title={t('today.widget.news.title')} meta={unread ? t('today.news.unread', { n: unread }) : undefined}>
        {canAuthor && <Link to="/announcements" className="today-widget-link" aria-label={t('today.news.manage')} title={t('today.news.manage')}><SquarePen size={14} aria-hidden /></Link>}
      </WidgetHeader>
      {news.isLoading ? (
        <div className="today-news-list" aria-busy>{Array.from({ length: 5 }, (_, index) => <span key={index} className="skeleton today-news-skeleton" />)}</div>
      ) : news.isError ? (
        <p className="today-widget-empty">{t('today.news.loadFailed')} <button type="button" className="today-widget-link" onClick={() => news.refetch()}>{t('common.retry')}</button></p>
      ) : items.length ? (
        <ul className="today-news-list">
          {items.map((item) => {
            const isUnread = !read.has(String(item.id))
            return (
              <li key={item.id}>
                <button type="button" className={`today-news-row${isUnread ? ' is-unread' : ''}`} onClick={() => openArticle(item)}>
                  {item.is_pinned ? <Pin size={11} className="today-news-pin" aria-label={t('today.news.pinned')} /> : <span className="today-news-dot" aria-hidden />}
                  <span className="today-news-title">{item.title}</span>
                  <time dateTime={item.published_at}>{shortDate(item.published_at)}</time>
                </button>
              </li>
            )
          })}
        </ul>
      ) : (
        <div className="today-widget-empty"><strong>{t('today.news.emptyTitle')}</strong><span>{t('today.news.emptyBody')}</span></div>
      )}
      {open && <Suspense fallback={null}><ArticleDialog article={open} onClose={() => setOpen(null)} /></Suspense>}
    </section>
  )
}
