import { useEffect, useMemo, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'motion/react'
import { useTranslation } from 'react-i18next'
import {
  BarChart3, BriefcaseBusiness, CheckSquare2, Clock3, FileCheck2, Goal,
  LayoutDashboard, LogOut, Menu, Search, Settings2, Sparkles, Users2, X,
} from 'lucide-react'
import { useActor, useEnterpriseLogout } from '../api/enterprise'
import { useAuthStore } from '../store/auth'

const NAV = [
  { to: '/', label: 'nav.today', icon: LayoutDashboard, roles: [] },
  { to: '/projects', label: 'nav.projects', icon: BriefcaseBusiness, roles: [] },
  { to: '/tasks', label: 'nav.tasks', icon: CheckSquare2, roles: [] },
  { to: '/reports', label: 'nav.reports', icon: FileCheck2, roles: [] },
  { to: '/capacity', label: 'nav.capacity', icon: Users2, roles: ['admin', 'manager', 'team_lead'] },
  { to: '/okrs', label: 'nav.okrs', icon: Goal, roles: [] },
  { to: '/analytics', label: 'nav.analytics', icon: BarChart3, roles: ['admin', 'manager', 'team_lead'] },
  { to: '/administration', label: 'nav.settings', icon: Settings2, roles: ['admin'] },
]

const TITLES: Record<string, string> = {
  '/': 'Өнөөдрийн ажлын орон зай', '/projects': 'Төслүүд', '/tasks': 'Даалгаврын самбар',
  '/reports': 'Тайлан ба зөвшөөрөл', '/capacity': 'Багийн ачаалал', '/okrs': 'OKR ба зорилго',
  '/analytics': 'Гүйцэтгэлийн үзүүлэлт', '/administration': 'Системийн тохиргоо',
}

export function RealtimeProvider({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((state) => state.token)
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!token) return
    let socket: WebSocket | null = null
    let retry: number | undefined
    let attempts = 0
    let closed = false
    let cursor = Number(sessionStorage.getItem('oyuns-event-cursor') || 0)
    const connect = () => {
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
      socket = new WebSocket(`${protocol}//${location.host}/api/v1/realtime?token=${encodeURIComponent(token)}&cursor=${cursor}`)
      socket.onopen = () => { attempts = 0 }
      socket.onmessage = (message) => {
        const event = JSON.parse(message.data)
        cursor = event.id
        sessionStorage.setItem('oyuns-event-cursor', String(cursor))
        const topicMap: Record<string, string> = { tasks: 'tasks', projects: 'projects', clocks: 'clock', capacity: 'capacity', reports: 'reports', okrs: 'objectives' }
        const key = topicMap[event.topic]
        if (key) queryClient.invalidateQueries({ queryKey: ['v1', key] })
      }
      socket.onclose = () => {
        if (closed) return
        retry = window.setTimeout(connect, Math.min(30_000, 800 * 2 ** attempts++))
      }
    }
    connect()
    return () => { closed = true; if (retry) clearTimeout(retry); socket?.close() }
  }, [queryClient, token])

  return <>{children}</>
}

export function EnterpriseShell() {
  const { t, i18n } = useTranslation()
  const location = useLocation()
  const navigate = useNavigate()
  const token = useAuthStore((state) => state.token)
  const actorQuery = useActor(Boolean(token))
  const logout = useEnterpriseLogout()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [commandOpen, setCommandOpen] = useState(false)

  useEffect(() => setMobileOpen(false), [location.pathname])
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault(); setCommandOpen((open) => !open)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const roles = actorQuery.data?.roles ?? []
  useEffect(() => {
    if (actorQuery.data?.locale) i18n.changeLanguage(actorQuery.data.locale)
  }, [actorQuery.data?.locale, i18n])
  const nav = useMemo(() => NAV.filter((item) => !item.roles.length || item.roles.some((role) => roles.includes(role))), [roles])
  const title = TITLES[location.pathname] ?? 'OYUNS Workspace'

  return (
    <RealtimeProvider>
      <div className="workspace-shell">
        <button className="mobile-menu-button" onClick={() => setMobileOpen(true)} aria-label="Цэс нээх"><Menu /></button>
        <aside className={`workspace-sidebar ${mobileOpen ? 'is-open' : ''}`}>
          <div className="sidebar-brand"><img src="/oyuns-aio-logo.png" alt="OYUNS" /><button onClick={() => setMobileOpen(false)} aria-label="Цэс хаах"><X /></button></div>
          <nav aria-label="Үндсэн цэс">
            {nav.map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
                <Icon size={18} strokeWidth={1.8} aria-hidden /><span>{t(label)}</span>
              </NavLink>
            ))}
          </nav>
          <div className="sidebar-profile">
            <div className="avatar">{actorQuery.data?.email?.[0]?.toUpperCase() ?? 'O'}</div>
            <div><strong>{actorQuery.data?.email ?? '…'}</strong><span>{roles[0] ?? 'member'}</span></div>
            <button onClick={() => logout.mutate()} aria-label={t('action.logout')}><LogOut size={17} /></button>
          </div>
        </aside>
        {mobileOpen && <button className="sidebar-scrim" onClick={() => setMobileOpen(false)} aria-label="Цэс хаах" />}
        <main className="workspace-main">
          <header className="workspace-header">
            <div><span className="eyebrow">OYUNS / Workspace</span><h1>{title}</h1></div>
            <div className="header-actions">
              <button className="search-trigger" onClick={() => setCommandOpen(true)}><Search size={16} /><span>{t('action.search')}</span><kbd>⌘K</kbd></button>
              <button className="ai-trigger" onClick={() => navigate('/tasks?create=ai')}><Sparkles size={16} /> OYUNS</button>
            </div>
          </header>
          <div className="workspace-content"><Outlet /></div>
        </main>
        <AnimatePresence>
          {commandOpen && (
            <motion.div className="command-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={() => setCommandOpen(false)}>
              <motion.div className="command-panel" role="dialog" aria-modal="true" aria-label="Шуурхай навигаци" initial={{ opacity: 0, scale: .96, y: -12 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: .96, y: -12 }} transition={{ type: 'spring', bounce: 0, duration: .35 }} onMouseDown={(event) => event.stopPropagation()}>
                <div className="command-input"><Search size={18} /><input autoFocus placeholder="Төсөл, даалгавар эсвэл хэсэг хайх…" /></div>
                <div className="command-list">{nav.map(({ to, label, icon: Icon }) => <button key={to} onClick={() => { navigate(to); setCommandOpen(false) }}><Icon size={17} />{t(label)}<span>{t('action.open')}</span></button>)}</div>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </RealtimeProvider>
  )
}
