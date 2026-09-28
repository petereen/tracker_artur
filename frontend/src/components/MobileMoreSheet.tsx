import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { NavLink } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ChevronRight, FolderArchive, LogOut, Moon, Search, Sun, Users2, type LucideIcon } from 'lucide-react'
import { preloadRoute } from '../platform/route-preload'
import { resolvePublicAssetUrl } from '../platform/runtime'
import { WorkspaceModeToggle } from './WorkspaceModeToggle'

type NavEntry = { to: string; label: string; icon: LucideIcon }

type Props = {
  open: boolean
  onClose: () => void
  items: NavEntry[]
  unreadChat: number
  actor?: { name?: string | null; email?: string | null; avatar_url?: string | null }
  role?: string
  theme: 'light' | 'dark'
  onToggleTheme: () => void
  onSearch: () => void
  onWorkers: () => void
  onLogout: () => void
}

const DISMISS_DISTANCE = 110

// Phone-only replacement for the desktop sidebar: an app-drawer style bottom sheet that
// can be dragged down to dismiss. Portaled to <body> so page stacking contexts can't trap it.
export function MobileMoreSheet({ open, onClose, items, unreadChat, actor, role, theme, onToggleTheme, onSearch, onWorkers, onLogout }: Props) {
  const { t } = useTranslation()
  const sheetRef = useRef<HTMLDivElement>(null)
  const drag = useRef({ startY: 0, active: false, fromScroll: false })
  const [offset, setOffset] = useState(0)
  const [dragging, setDragging] = useState(false)

  useEffect(() => {
    if (!open) return
    setOffset(0)
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', closeOnEscape)
    sheetRef.current?.focus({ preventScroll: true })
    return () => { document.body.style.overflow = previousOverflow; document.removeEventListener('keydown', closeOnEscape) }
  }, [onClose, open])

  if (!open) return null

  const onTouchStart = (event: React.TouchEvent) => {
    const body = sheetRef.current?.querySelector('.mobile-more-body')
    drag.current = { startY: event.touches[0].clientY, active: true, fromScroll: Boolean(body?.contains(event.target as Node) && body.scrollTop > 0) }
  }
  const onTouchMove = (event: React.TouchEvent) => {
    if (!drag.current.active || drag.current.fromScroll) return
    const delta = event.touches[0].clientY - drag.current.startY
    if (delta <= 0) { if (offset) setOffset(0); return }
    setDragging(true)
    setOffset(delta)
  }
  const onTouchEnd = () => {
    drag.current.active = false
    setDragging(false)
    if (offset > DISMISS_DISTANCE) onClose()
    else setOffset(0)
  }
  const initial = actor?.name?.[0]?.toUpperCase() ?? actor?.email?.[0]?.toUpperCase() ?? 'O'

  return createPortal(
    <div className="mobile-more-root">
      <button type="button" className="mobile-more-scrim" aria-label="Цэс хаах" onClick={onClose} style={{ opacity: Math.max(0, 1 - offset / 400) }} />
      <div
        ref={sheetRef}
        className={`mobile-more-sheet ${dragging ? 'is-dragging' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label="Бусад цэс"
        tabIndex={-1}
        style={offset ? { transform: `translate3d(0, ${offset}px, 0)` } : undefined}
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
        onTouchCancel={onTouchEnd}
      >
        <div className="mobile-sheet-grabber" aria-hidden />
        <div className="mobile-more-body">
          <NavLink to="/profile" className="mobile-more-profile" onClick={onClose}>
            <span className="avatar">{actor?.avatar_url ? <img src={resolvePublicAssetUrl(actor.avatar_url) || undefined} alt="" /> : initial}</span>
            <span><strong>{actor?.name ?? actor?.email ?? '…'}</strong><small>{role ?? 'member'}</small></span>
            <ChevronRight size={18} aria-hidden />
          </NavLink>
          <button type="button" className="mobile-more-search" onClick={() => { onClose(); onSearch() }}>
            <Search size={17} aria-hidden /><span>{t('action.search')}</span>
          </button>
          <nav className="mobile-more-grid" aria-label="Бүх цэс">
            {items.map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={to} end={to === '/' || to === '/erp'} onClick={onClose} onTouchStart={() => preloadRoute(to)} className={({ isActive }) => isActive ? 'active' : ''}>
                <span className="mobile-more-tile"><Icon size={22} strokeWidth={1.8} aria-hidden />{to === '/chat' && unreadChat > 0 && <b className="nav-unread-badge">{unreadChat > 99 ? '99+' : unreadChat}</b>}</span>
                <span className="mobile-more-label">{label.startsWith('nav.') ? t(label) : label}</span>
              </NavLink>
            ))}
            <NavLink to="/company-files" onClick={onClose} className={({ isActive }) => isActive ? 'active' : ''}>
              <span className="mobile-more-tile"><FolderArchive size={22} strokeWidth={1.8} aria-hidden /></span>
              <span className="mobile-more-label">{t('nav.companyFiles')}</span>
            </NavLink>
          </nav>
          <div className="mobile-more-list">
            <div className="mobile-more-row mobile-more-mode"><WorkspaceModeToggle /></div>
            <button type="button" className="mobile-more-row" onClick={() => { onClose(); onWorkers() }}>
              <Users2 size={18} aria-hidden /><span>Ажилтнууд</span><ChevronRight size={17} aria-hidden />
            </button>
            <button type="button" className="mobile-more-row" role="switch" aria-checked={theme === 'dark'} onClick={onToggleTheme}>
              {theme === 'dark' ? <Moon size={18} aria-hidden /> : <Sun size={18} aria-hidden />}<span>Харанхуй горим</span><i className={`mobile-switch ${theme === 'dark' ? 'on' : ''}`} aria-hidden />
            </button>
            <button type="button" className="mobile-more-row danger" onClick={() => { onClose(); onLogout() }}>
              <LogOut size={18} aria-hidden /><span>{t('action.logout')}</span>
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  )
}
