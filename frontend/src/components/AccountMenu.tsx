import { useEffect, useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { BookOpen, ChevronsUpDown, LogOut, Moon, Sun, UserCircle2 } from 'lucide-react'
import { resolvePublicAssetUrl } from '../platform/runtime'

type Props = {
  actor?: { name?: string | null; email?: string | null; avatar_url?: string | null }
  theme: 'light' | 'dark'
  onToggleTheme: () => void
  onLogout: () => void
}

/** Sidebar account control: opens an action menu with the theme switch, profile, docs and log out. */
export function AccountMenu({ actor, theme, onToggleTheme, onLogout }: Props) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const menuId = useId()
  const displayName = actor?.name ?? actor?.email ?? '…'
  const initial = actor?.name?.[0]?.toUpperCase() ?? actor?.email?.[0]?.toUpperCase() ?? 'O'
  const avatar = actor?.avatar_url ? <img src={resolvePublicAssetUrl(actor.avatar_url) || undefined} alt="" /> : initial

  useEffect(() => {
    if (!open) return
    const onPointer = (event: PointerEvent) => { if (!rootRef.current?.contains(event.target as Node)) setOpen(false) }
    const onKey = (event: globalThis.KeyboardEvent) => { if (event.key === 'Escape') { setOpen(false); triggerRef.current?.focus() } }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]:not([aria-disabled="true"])')?.focus({ preventScroll: true })
    return () => { document.removeEventListener('pointerdown', onPointer); document.removeEventListener('keydown', onKey) }
  }, [open])

  const close = () => setOpen(false)
  const openProfile = () => { close(); navigate('/profile') }
  const logout = () => { close(); onLogout() }

  const onTriggerKey = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'ArrowUp' || event.key === 'ArrowDown') { event.preventDefault(); setOpen(true) }
  }
  const onMenuKey = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
    const items = Array.from(menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([aria-disabled="true"])') ?? [])
    if (!items.length) return
    event.preventDefault()
    const index = items.indexOf(document.activeElement as HTMLElement)
    const next = event.key === 'ArrowDown' ? (index + 1) % items.length : (index <= 0 ? items.length - 1 : index - 1)
    items[next].focus()
  }

  return <div ref={rootRef} className="sidebar-profile account-menu">
    {open && <div ref={menuRef} id={menuId} className="account-menu-panel" role="menu" aria-label={t('shell.account.menu')} onKeyDown={onMenuKey}>
      <div className="account-menu-head">
        <div className="account-menu-identity">
          <strong title={displayName}>{displayName}</strong>
          {actor?.email && actor.email !== displayName && <span title={actor.email}>{actor.email}</span>}
        </div>
        <button type="button" className="theme-toggle account-menu-theme" onClick={onToggleTheme} aria-label={t(theme === 'light' ? 'shell.theme.enableDark' : 'shell.theme.enableLight')} title={t(theme === 'light' ? 'shell.theme.dark' : 'shell.theme.light')}>
          {theme === 'light' ? <Moon size={16} aria-hidden /> : <Sun size={16} aria-hidden />}
        </button>
      </div>
      <div className="account-menu-list">
        <button type="button" role="menuitem" className="account-menu-item" onClick={openProfile}><UserCircle2 size={17} strokeWidth={1.8} aria-hidden /><span>{t('shell.account.profile')}</span></button>
        <button type="button" role="menuitem" className="account-menu-item" aria-disabled="true" title={t('shell.account.docsSoon')} onClick={(event) => event.preventDefault()}>
          <BookOpen size={17} strokeWidth={1.8} aria-hidden /><span>{t('shell.account.docs')}</span><em>{t('shell.account.soon')}</em>
        </button>
      </div>
      <div className="account-menu-list account-menu-foot">
        <button type="button" role="menuitem" className="account-menu-item danger" onClick={logout}><LogOut size={17} strokeWidth={1.8} aria-hidden /><span>{t('action.logout')}</span></button>
      </div>
    </div>}
    <button ref={triggerRef} type="button" className="account-menu-trigger" aria-label={t('shell.account.open')} aria-haspopup="menu" aria-expanded={open} aria-controls={open ? menuId : undefined} onClick={() => setOpen((current) => !current)} onKeyDown={onTriggerKey}>
      <span className="avatar">{avatar}</span>
      <span className="account-menu-identity"><strong>{displayName}</strong>{actor?.email && actor.email !== displayName && <span>{actor.email}</span>}</span>
      <ChevronsUpDown size={16} aria-hidden />
    </button>
  </div>
}
