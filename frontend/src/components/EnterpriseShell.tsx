import { Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { api } from '../api/client'
import {
  BarChart3, BriefcaseBusiness, CalendarDays, CheckSquare2, ChevronLeft, ChevronRight, FileCheck2, FileSignature, Goal, KeyRound, Landmark, ScanLine,
  FolderArchive, LayoutDashboard, LogOut, Menu, MessageCircle, Moon, Search, Send, Settings2, Sparkles, Sun, Users2, X, Upload, UserCircle2,
} from 'lucide-react'
import { acknowledgeChatReceipt, useActor, useBrandingSettings, useChatUnreadCount, useEnterpriseLogout, useERPMetadata, useOpenDirectConversation, useWorkerDirectory, useWorkerPerformance, useWorkerProfile } from '../api/enterprise'
import { EMPTY_ROLES, useAuthStore } from '../store/auth'
import { periodFromPreset } from './TimePeriodFilter'
import { OyunsAssistant } from './OyunsAssistant'
import { NotificationCenter } from './NotificationCenter'
import { WorkspaceModeProvider } from './WorkspaceModeProvider'
import { WorkspaceModeToggle } from './WorkspaceModeToggle'
import { WorkspaceSkeleton } from './Loading'
import { GlobalCommandBar } from './GlobalCommandBar'
import { getRealtimeUrl, resolvePublicAssetUrl, safeLocalStorage, safeSessionStorage } from '../platform/runtime'
import { showDesktopChatAlert } from '../platform/chat-notifications'

const NAV = [
  { to: '/', label: 'nav.today', icon: LayoutDashboard, roles: [] },
  { to: '/worktime', label: 'nav.worktime', icon: ScanLine, roles: [] },
  { to: '/chat', label: 'nav.chat', icon: MessageCircle, roles: [] },
  { to: '/calendar', label: 'nav.calendar', icon: CalendarDays, roles: [] },
  { to: '/tasks', label: 'nav.tasks', icon: CheckSquare2, roles: [] },
  { to: '/reports', label: 'nav.reports', icon: FileCheck2, roles: [] },
  { to: '/projects', label: 'nav.projects', icon: BriefcaseBusiness, roles: [] },
  { to: '/plans', label: 'nav.plans', icon: Goal, roles: [] },
  { to: '/contracts', label: 'nav.contracts', icon: FileSignature, roles: [] },
  { to: '/analytics', label: 'nav.analytics', icon: BarChart3, roles: [] },
  { to: '/administration', label: 'nav.settings', icon: Settings2, roles: ['admin', 'manager', 'team_lead'] },
]

const NAV_GROUP_BREAKS = new Set(['/calendar', '/reports', '/analytics', '/administration'])

const TITLES: Record<string, string> = {
  '/': 'Өнөөдрийн ажлын орон зай', '/worktime': 'Ажлын цагийн бүртгэл', '/projects': 'Төслүүд', '/tasks': 'Даалгаврын самбар', '/calendar': 'Календарь',
  '/reports': 'Тайлан ба зөвшөөрөл', '/capacity': 'Багийн ачаалал', '/plans': 'Төлөвлөгөө', '/contracts': 'Гэрээ',
  '/chat': 'Чат',
  '/analytics': 'Гүйцэтгэлийн үзүүлэлт', '/administration': 'Системийн тохиргоо',
  '/erp': 'ERP үйл ажиллагаа',
  '/administration/workspace': 'Logo оруулах',
  '/administration/collaboration': 'Чек ин тохиргоо',
  '/administration/access': 'Хандалтын удирдлага',
  '/administration/automation': 'Автоматжуулалт ба интеграци',
  '/administration/erp': 'ERP модулиуд',
  '/administration/admin-access': 'Админ хандалт',
  '/administration/oyuns': 'OYUNS agent-ын тохиргоо',
  '/profile': 'Миний профайл',
  '/company-files': 'Компаний файлууд',
}

export function RealtimeProvider({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((state) => state.token)
  const accountId = useAuthStore((state) => state.actor?.id)
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  useEffect(() => {
    if (!token || !accountId) return
    let socket: WebSocket | null = null
    let retry: number | undefined
    let heartbeat: number | undefined
    let attempts = 0
    let closed = false
    const cursorStorage = safeSessionStorage()
    const cursorKey = `oyuns-event-cursor:${accountId}`
    let cursor = Number(cursorStorage.get(cursorKey) || 0)
    const sendHeartbeat = () => {
      if (document.visibilityState === 'visible' && socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'presence.heartbeat' }))
    }
    const connect = () => {
      const endpoint = new URL(getRealtimeUrl())
      endpoint.searchParams.set('token', token)
      endpoint.searchParams.set('cursor', String(cursor))
      socket = new WebSocket(endpoint)
      socket.onopen = () => { attempts = 0; sendHeartbeat(); if (heartbeat) window.clearInterval(heartbeat); heartbeat = window.setInterval(sendHeartbeat, 25_000) }
      socket.onmessage = (message) => {
        const event = JSON.parse(message.data)
        cursor = event.id
        cursorStorage.set(cursorKey, String(cursor))
        const topicMap: Record<string, string> = { tasks: 'tasks', projects: 'projects', clocks: 'clock', capacity: 'capacity', reports: 'reports', contracts: 'contracts', okrs: 'objectives', notifications: 'notifications', company_files: 'company-files', erp: 'erp', chat: 'chat', chat_presence: 'chat' }
        const key = topicMap[event.topic]
        if (key) queryClient.invalidateQueries({ queryKey: ['v1', key] })
        if (event.topic === 'chat' && event.operation === 'message_sent' && event.payload?.sender_account_id !== accountId) {
          void acknowledgeChatReceipt(event.payload.conversation_public_id, event.payload.message_id, 'delivered')
          if (document.visibilityState !== 'visible') {
            void Promise.all([
              api.get('/v1/auth/preferences/chat-notifications').then((response) => response.data),
              api.get(`/v1/chat/conversations/${event.payload.conversation_public_id}`).then((response) => response.data),
            ]).then(([preferences, conversation]) => {
              if (!preferences.desktop_alerts_enabled || conversation.is_muted) return
              return showDesktopChatAlert({
                title: event.payload.conversation_title || event.payload.sender_name || 'OYUNS Chat',
                body: event.payload.preview || 'Шинэ мессеж',
                targetUrl: event.payload.target_url || `/chat/${event.payload.conversation_public_id}`,
                soundEnabled: preferences.sound_enabled,
              }, navigate)
            }).catch(() => undefined)
          }
        }
      }
      socket.onclose = () => {
        if (closed) return
        retry = window.setTimeout(connect, Math.min(30_000, 800 * 2 ** attempts++))
      }
    }
    const onVisibility = () => sendHeartbeat()
    document.addEventListener('visibilitychange', onVisibility)
    connect()
    return () => { closed = true; document.removeEventListener('visibilitychange', onVisibility); if (retry) clearTimeout(retry); if (heartbeat) clearInterval(heartbeat); socket?.close() }
  }, [accountId, navigate, queryClient, token])

  return <>{children}</>
}

export function EnterpriseShell() {
  const { t, i18n } = useTranslation()
  const location = useLocation()
  const navigate = useNavigate()
  const token = useAuthStore((state) => state.token)
  const setActor = useAuthStore((state) => state.setActor)
  const actorQuery = useActor(Boolean(token))
  const logout = useEnterpriseLogout()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [commandOpen, setCommandOpen] = useState(false)
  const [assistantOpen, setAssistantOpen] = useState(false)
  const [workersOpen, setWorkersOpen] = useState(false)
  const [workersToggleY, setWorkersToggleY] = useState(110)
  const [workersDragging, setWorkersDragging] = useState(false)
  const workersDrawerRef = useRef<HTMLElement>(null)
  const workersToggleRef = useRef<HTMLButtonElement>(null)
  const workersDragRef = useRef({ pointerId: -1, startY: 0, startToggleY: 0, moved: false })
  const suppressWorkersClickRef = useRef(false)
  const [workerSearch, setWorkerSearch] = useState('')
  const [selectedWorker, setSelectedWorker] = useState<number>()
  const [theme, setTheme] = useState<'light' | 'dark'>(() => (safeLocalStorage().get('oyuns-theme') as 'light' | 'dark') || 'light')
  const workers = useWorkerDirectory()
  const branding = useBrandingSettings()
  const erp = useERPMetadata(Boolean(token))
  const unreadChat = useChatUnreadCount(Boolean(token))
  const openDirectChat = useOpenDirectConversation()

  useEffect(() => setMobileOpen(false), [location.pathname])
  useEffect(() => {
    if (!workersOpen) return
    const dismissOnOutsidePointer = (event: PointerEvent) => {
      if (!workersDrawerRef.current?.contains(event.target as Node)) setWorkersOpen(false)
    }
    document.addEventListener('pointerdown', dismissOnOutsidePointer)
    return () => document.removeEventListener('pointerdown', dismissOnOutsidePointer)
  }, [workersOpen])
  useEffect(() => {
    const clampToggle = () => {
      const buttonHeight = workersToggleRef.current?.offsetHeight ?? 48
      const margin = 14
      setWorkersToggleY((current) => Math.min(Math.max(current, margin), Math.max(margin, window.innerHeight - buttonHeight - margin)))
    }
    clampToggle()
    window.addEventListener('resize', clampToggle)
    return () => window.removeEventListener('resize', clampToggle)
  }, [])
  useEffect(() => { document.documentElement.dataset.theme = theme; safeLocalStorage().set('oyuns-theme', theme) }, [theme])
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault(); setCommandOpen((open) => !open)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const roles = actorQuery.data?.roles ?? EMPTY_ROLES
  useEffect(() => {
    if (actorQuery.data) setActor(actorQuery.data)
  }, [actorQuery.data, setActor])
  useEffect(() => {
    if (actorQuery.data?.locale && i18n.language !== actorQuery.data.locale) i18n.changeLanguage(actorQuery.data.locale)
  }, [actorQuery.data?.locale, i18n])
  const nav = useMemo(() => {
    const base = NAV.filter((item) => !item.roles.length || item.roles.some((role) => roles.includes(role)))
    const canAccessERP = roles.includes('admin') || Object.values(erp.data?.modules ?? {}).some(Boolean)
    return canAccessERP ? [...base.slice(0, -1), { to: '/erp', label: 'ERP', icon: Landmark, roles: [] }, base[base.length - 1]] : base
  }, [erp.data, roles])
  const canReviewWorkers = roles.some((role) => ['admin', 'manager', 'team_lead'].includes(role))
  const workerPerformance = useWorkerPerformance(selectedWorker, periodFromPreset('week'), canReviewWorkers)
  const workerProfile = useWorkerProfile(selectedWorker)
  const visibleWorkers = useMemo(() => (workers.data ?? []).filter((worker) => worker.name.toLowerCase().includes(workerSearch.toLowerCase())), [workerSearch, workers.data])
  const title = TITLES[location.pathname] ?? 'OYUNS Workspace'
  const logo = theme === 'dark' ? branding.data?.dark_logo : branding.data?.light_logo
  const commandChannels = useMemo(() => [...nav, { to: '/company-files', label: 'nav.companyFiles', icon: FolderArchive, roles: [] }].map((item) => ({ id: item.to, type: 'channel' as const, title: 'settings' in item ? String(item.label) : t(item.label), subtitle: 'Workspace section', icon: item.icon, run: () => navigate(item.to) })), [nav, navigate, t])
  const commandFeatures = useMemo(() => [
    { id: 'create-task', type: 'feature' as const, title: 'Create task', subtitle: 'Open a new task form', icon: CheckSquare2, run: () => navigate('/tasks?create=1') },
    { id: 'create-contract', type: 'feature' as const, title: 'Create contract', subtitle: 'Open a new contract draft', icon: FileSignature, run: () => navigate('/contracts?create=1') },
    { id: 'upload-file', type: 'feature' as const, title: 'Upload file', subtitle: 'Open the company file uploader', icon: Upload, run: () => navigate('/company-files?upload=1') },
    ...(roles.some((role) => ['admin', 'manager', 'team_lead'].includes(role)) ? [
      { id: 'workspace-settings', type: 'feature' as const, title: 'Workspace settings', subtitle: 'Branding and identity', icon: Settings2, run: () => navigate('/administration/workspace') },
      { id: 'collaboration-settings', type: 'feature' as const, title: 'Collaboration settings', subtitle: 'Check-ins and team workflows', icon: Users2, run: () => navigate('/administration/collaboration') },
      { id: 'access-settings', type: 'feature' as const, title: 'Access control', subtitle: 'Manage workspace access', icon: Settings2, run: () => navigate('/administration/access') },
    ] : []),
    { id: 'profile', type: 'feature' as const, title: 'Open profile', subtitle: 'Manage your account', icon: UserCircle2, run: () => navigate('/profile') },
  ], [navigate, roles])
  const mobileNav = useMemo(() => ['/', '/calendar', '/tasks', '/chat'].map((to) => nav.find((item) => item.to === to)).filter(Boolean) as typeof nav, [nav])
  const openWorkerChat = async (employeeId: number) => {
    try {
      const conversation = await openDirectChat.mutateAsync({ employee_id: employeeId })
      setWorkersOpen(false)
      navigate(`/chat/${conversation.public_id}`)
    } catch (error: any) {
      toast.error(error.response?.data?.detail || 'Чат нээж чадсангүй')
    }
  }

  const handleWorkersPointerDown = (event: React.PointerEvent<HTMLButtonElement>) => {
    if (event.button !== 0 && event.pointerType !== 'touch') return
    const button = event.currentTarget
    button.setPointerCapture(event.pointerId)
    workersDragRef.current = { pointerId: event.pointerId, startY: event.clientY, startToggleY: workersToggleY, moved: false }
    suppressWorkersClickRef.current = false
    setWorkersDragging(true)
  }
  const handleWorkersPointerMove = (event: React.PointerEvent<HTMLButtonElement>) => {
    const drag = workersDragRef.current
    if (drag.pointerId !== event.pointerId) return
    const delta = event.clientY - drag.startY
    if (!drag.moved && Math.abs(delta) < 8) return
    drag.moved = true
    suppressWorkersClickRef.current = true
    const buttonHeight = workersToggleRef.current?.offsetHeight ?? 48
    const margin = 14
    const maxY = Math.max(margin, window.innerHeight - buttonHeight - margin)
    setWorkersToggleY(Math.min(Math.max(drag.startToggleY + delta, margin), maxY))
  }
  const finishWorkersPointer = (event: React.PointerEvent<HTMLButtonElement>) => {
    const drag = workersDragRef.current
    if (drag.pointerId !== event.pointerId) return
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    workersDragRef.current.pointerId = -1
    setWorkersDragging(false)
  }
  const handleWorkersClick = () => {
    if (suppressWorkersClickRef.current) {
      suppressWorkersClickRef.current = false
      return
    }
    setWorkersOpen((value) => !value)
  }

  return (
    <WorkspaceModeProvider>
    <RealtimeProvider>
      <div className="workspace-shell">
        <button className="mobile-menu-button" onClick={() => setMobileOpen(true)} aria-label="Цэс нээх"><Menu /></button>
        <aside className={`workspace-sidebar ${mobileOpen ? 'is-open' : ''}`}>
          <div className="sidebar-brand"><img src={logo || (theme === 'dark' ? '/oyuns-aio-logo.png' : '/favicon.png')} alt="OYUNS" /><button onClick={() => setMobileOpen(false)} aria-label="Цэс хаах"><X /></button></div>
          <nav aria-label="Үндсэн цэс">
            {nav.map(({ to, label, icon: Icon }) => (
              <div className={NAV_GROUP_BREAKS.has(to) ? 'nav-group nav-group-break' : 'nav-group'} key={to}>
                <NavLink to={to} end={to === '/'} className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
                  <Icon size={18} strokeWidth={1.8} aria-hidden /><span>{t(label)}</span>{to === '/chat' && Boolean(unreadChat.data?.unread_count) && <b className="nav-unread-badge" aria-label={`${unreadChat.data?.unread_count} уншаагүй чат`}>{(unreadChat.data?.unread_count ?? 0) > 99 ? '99+' : unreadChat.data?.unread_count}</b>}
                </NavLink>
              </div>
            ))}
          </nav>
          <div className="sidebar-footer">
            <NavLink to="/company-files" className={({ isActive }) => isActive ? 'sidebar-library-link active' : 'sidebar-library-link'}><FolderArchive size={17} /><span>{t('nav.companyFiles')}</span></NavLink>
            <div className="sidebar-profile">
              <button className="avatar" onClick={() => navigate('/profile')} aria-label="Профайл нээх">{actorQuery.data?.avatar_url ? <img src={resolvePublicAssetUrl(actorQuery.data.avatar_url) || undefined} alt="" /> : actorQuery.data?.name?.[0]?.toUpperCase() ?? actorQuery.data?.email?.[0]?.toUpperCase() ?? 'O'}</button>
              <button className="profile-identity" onClick={() => navigate('/profile')}><strong>{actorQuery.data?.name ?? actorQuery.data?.email ?? '…'}</strong><span>{roles[0] ?? 'member'}</span></button>
              <button onClick={() => logout.mutate()} aria-label={t('action.logout')}><LogOut size={17} /></button>
            </div>
          </div>
        </aside>
        {mobileOpen && <button className="sidebar-scrim" onClick={() => setMobileOpen(false)} aria-label="Цэс хаах" />}
        <main className="workspace-main">
          <header className="workspace-header">
            <div><span className="eyebrow">OYUNS / Workspace</span><h1>{title}</h1></div>
            <div className="header-actions">
              <WorkspaceModeToggle />
              <NotificationCenter />
              <button className="theme-toggle" onClick={() => setTheme((current) => current === 'light' ? 'dark' : 'light')} aria-label={theme === 'light' ? 'Dark mode идэвхжүүлэх' : 'Light mode идэвхжүүлэх'} title={theme === 'light' ? 'Dark mode' : 'Light mode'}>{theme === 'light' ? <Moon size={16} /> : <Sun size={16} />}</button>
              <button className="search-trigger" onClick={() => setCommandOpen(true)}><Search size={16} /><span>{t('action.search')}</span><kbd>⌘K</kbd></button>
              <button className="ai-trigger" onClick={() => setAssistantOpen(true)}><Sparkles size={16} /> OYUNS</button>
            </div>
          </header>
          <div className={`workspace-content ${location.pathname.startsWith('/chat') ? 'chat-route-content' : ''}`}><Suspense fallback={<WorkspaceSkeleton />}><Outlet /></Suspense></div>
        </main>
        <nav className="mobile-tabbar" aria-label="Шуурхай цэс">
          {mobileNav.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => isActive ? 'active' : ''}>
              <span className="mobile-tab-icon"><Icon size={19} strokeWidth={1.9} aria-hidden />{to === '/chat' && Boolean(unreadChat.data?.unread_count) && <b className="nav-unread-badge">{(unreadChat.data?.unread_count ?? 0) > 99 ? '99+' : unreadChat.data?.unread_count}</b>}</span>
              <span>{t(label)}</span>
            </NavLink>
          ))}
          <button onClick={() => setMobileOpen(true)} aria-label="Бусад цэс нээх">
            <Menu size={20} aria-hidden />
            <span>Бусад</span>
          </button>
        </nav>
        <aside ref={workersDrawerRef} className={`workers-drawer ${workersOpen ? 'open' : ''} ${workersDragging ? 'is-dragging' : ''}`} style={{ '--workers-toggle-y': `${workersToggleY}px` } as React.CSSProperties} aria-label="Ажилтны төлөв"><button ref={workersToggleRef} className="workers-toggle" onPointerDown={handleWorkersPointerDown} onPointerMove={handleWorkersPointerMove} onPointerUp={finishWorkersPointer} onPointerCancel={finishWorkersPointer} onClick={handleWorkersClick} aria-label="Ажилтны жагсаалт нээх"><ChevronLeft /><Users2 /></button><div className="workers-content"><header><div><span className="eyebrow">OYUNS</span><h2>Ажилтнууд</h2></div><button onClick={() => setWorkersOpen(false)} aria-label="Ажилтны жагсаалт хаах"><X /></button></header><label className="worker-search"><Search size={15} /><input value={workerSearch} onChange={(event) => setWorkerSearch(event.target.value)} placeholder="Ажилтан хайх…" /></label><div className="worker-list">{visibleWorkers.map((worker) => <button key={worker.id} onClick={() => setSelectedWorker(worker.id)}><span className="worker-avatar">{worker.avatar_url ? <img src={resolvePublicAssetUrl(worker.avatar_url) || undefined} alt="" /> : worker.name[0]}</span><span><strong>{worker.name}</strong><small>{worker.presence === 'in_person' ? 'Оффис идэвхтэй' : worker.presence === 'remote' ? 'Remote идэвхтэй' : worker.presence === 'break' ? 'Завсарлага' : 'Offline'} · {worker.job_title || worker.telegram_username || 'Ажилтан'}</small></span><i className={`presence ${worker.presence}`} title={worker.presence} /></button>)}</div>{selectedWorker && <section className="worker-performance">{workerProfile.isLoading ? <p>Профайл ачаалж байна…</p> : <><header><strong>{workerProfile.data?.name}</strong><button onClick={() => setSelectedWorker(undefined)}><X size={14} /></button></header><p>{workerProfile.data?.phone_number || 'Утас оруулаагүй'}<br />{workerProfile.data?.work_direction || 'Чиглэл оруулаагүй'} · {workerProfile.data?.work_branch || 'Ажлын алба оруулаагүй'}</p><div className="worker-chat-actions"><button className="worker-inapp-chat" disabled={!workerProfile.data?.chat_available || openDirectChat.isPending} onClick={() => selectedWorker && openWorkerChat(selectedWorker)}>Чатлах</button>{workerProfile.data?.telegram_chat_url && <a className="telegram-chat-action" href={workerProfile.data.telegram_chat_url} target="_blank" rel="noreferrer" aria-label="Telegram-аар чатлах" title="Telegram-аар чатлах"><Send size={17} /></a>}</div>{!workerProfile.data?.chat_available && <small className="worker-chat-hint">Workspace хандалт холбосны дараа чатлах боломжтой.</small>}{canReviewWorkers && <div><span>Ажилласан цаг<strong>{Math.round((workerPerformance.data?.worked_minutes ?? 0) / 60)}ц</strong></span><span>Даалгавар<strong>{workerPerformance.data?.completion_rate ?? 0}%</strong></span><span>Тайлан<strong>{workerPerformance.data?.report_submission_rate ?? 0}%</strong></span></div>}</>}</section>}</div></aside>
        <OyunsAssistant open={assistantOpen} onClose={() => setAssistantOpen(false)} />
        <GlobalCommandBar open={commandOpen} onClose={() => setCommandOpen(false)} accountId={actorQuery.data?.id} channels={commandChannels} features={commandFeatures} onWorker={(id) => { setSelectedWorker(id); setWorkersOpen(true) }} />
      </div>
    </RealtimeProvider>
    </WorkspaceModeProvider>
  )
}
