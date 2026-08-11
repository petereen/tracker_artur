import { Suspense, useEffect, useMemo, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  BarChart3, BriefcaseBusiness, CalendarDays, CheckSquare2, ChevronLeft, ChevronRight, FileCheck2, Goal, KeyRound,
  FolderArchive, LayoutDashboard, LogOut, Menu, Moon, Search, Send, Settings2, Sparkles, Sun, Users2, X, Upload, UserCircle2,
} from 'lucide-react'
import { useActor, useBrandingSettings, useEnterpriseLogout, useWorkerDirectory, useWorkerPerformance, useWorkerProfile } from '../api/enterprise'
import { EMPTY_ROLES, useAuthStore } from '../store/auth'
import { periodFromPreset } from './TimePeriodFilter'
import { OyunsAssistant } from './OyunsAssistant'
import { NotificationCenter } from './NotificationCenter'
import { WorkspaceSkeleton } from './Loading'
import { GlobalCommandBar } from './GlobalCommandBar'

const NAV = [
  { to: '/', label: 'nav.today', icon: LayoutDashboard, roles: [] },
  { to: '/calendar', label: 'nav.calendar', icon: CalendarDays, roles: [] },
  { to: '/tasks', label: 'nav.tasks', icon: CheckSquare2, roles: [] },
  { to: '/reports', label: 'nav.reports', icon: FileCheck2, roles: [] },
  { to: '/projects', label: 'nav.projects', icon: BriefcaseBusiness, roles: [] },
  { to: '/plans', label: 'nav.plans', icon: Goal, roles: [] },
  { to: '/analytics', label: 'nav.analytics', icon: BarChart3, roles: [] },
  { to: '/administration', label: 'nav.settings', icon: Settings2, roles: ['admin', 'manager', 'team_lead'] },
]

const NAV_GROUP_BREAKS = new Set(['/calendar', '/projects', '/analytics', '/administration'])

const TITLES: Record<string, string> = {
  '/': 'Өнөөдрийн ажлын орон зай', '/projects': 'Төслүүд', '/tasks': 'Даалгаврын самбар', '/calendar': 'Календарь',
  '/reports': 'Тайлан ба зөвшөөрөл', '/capacity': 'Багийн ачаалал', '/plans': 'Төлөвлөгөө',
  '/analytics': 'Гүйцэтгэлийн үзүүлэлт', '/administration': 'Системийн тохиргоо',
  '/administration/workspace': 'Logo оруулах',
  '/administration/collaboration': 'Чек ин тохиргоо',
  '/administration/access': 'Хандалтын удирдлага',
  '/administration/automation': 'Автоматжуулалт ба интеграци',
  '/administration/admin-access': 'Админ хандалт',
  '/administration/oyuns': 'OYUNS agent-ын тохиргоо',
  '/profile': 'Миний профайл',
  '/company-files': 'Компаний файлууд',
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
        const topicMap: Record<string, string> = { tasks: 'tasks', projects: 'projects', clocks: 'clock', capacity: 'capacity', reports: 'reports', okrs: 'objectives', notifications: 'notifications', company_files: 'company-files' }
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
  const setActor = useAuthStore((state) => state.setActor)
  const actorQuery = useActor(Boolean(token))
  const logout = useEnterpriseLogout()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [commandOpen, setCommandOpen] = useState(false)
  const [assistantOpen, setAssistantOpen] = useState(false)
  const [workersOpen, setWorkersOpen] = useState(false)
  const [workerSearch, setWorkerSearch] = useState('')
  const [selectedWorker, setSelectedWorker] = useState<number>()
  const [theme, setTheme] = useState<'light' | 'dark'>(() => (localStorage.getItem('oyuns-theme') as 'light' | 'dark') || 'light')
  const workers = useWorkerDirectory()
  const branding = useBrandingSettings()

  useEffect(() => setMobileOpen(false), [location.pathname])
  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem('oyuns-theme', theme) }, [theme])
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
  const nav = useMemo(() => NAV.filter((item) => !item.roles.length || item.roles.some((role) => roles.includes(role))), [roles])
  const canReviewWorkers = roles.some((role) => ['admin', 'manager', 'team_lead'].includes(role))
  const workerPerformance = useWorkerPerformance(selectedWorker, periodFromPreset('week'), canReviewWorkers)
  const workerProfile = useWorkerProfile(selectedWorker)
  const visibleWorkers = useMemo(() => (workers.data ?? []).filter((worker) => worker.name.toLowerCase().includes(workerSearch.toLowerCase())), [workerSearch, workers.data])
  const title = TITLES[location.pathname] ?? 'OYUNS Workspace'
  const logo = theme === 'dark' ? branding.data?.dark_logo : branding.data?.light_logo
  const commandChannels = useMemo(() => [...nav, { to: '/company-files', label: 'nav.companyFiles', icon: FolderArchive, roles: [] }].map((item) => ({ id: item.to, type: 'channel' as const, title: 'settings' in item ? String(item.label) : t(item.label), subtitle: 'Workspace section', icon: item.icon, run: () => navigate(item.to) })), [nav, navigate, t])
  const commandFeatures = useMemo(() => [
    { id: 'create-task', type: 'feature' as const, title: 'Create task', subtitle: 'Open a new task form', icon: CheckSquare2, run: () => navigate('/tasks?create=1') },
    { id: 'upload-file', type: 'feature' as const, title: 'Upload file', subtitle: 'Open the company file uploader', icon: Upload, run: () => navigate('/company-files?upload=1') },
    ...(roles.some((role) => ['admin', 'manager', 'team_lead'].includes(role)) ? [
      { id: 'workspace-settings', type: 'feature' as const, title: 'Workspace settings', subtitle: 'Branding and identity', icon: Settings2, run: () => navigate('/administration/workspace') },
      { id: 'collaboration-settings', type: 'feature' as const, title: 'Collaboration settings', subtitle: 'Check-ins and team workflows', icon: Users2, run: () => navigate('/administration/collaboration') },
      { id: 'access-settings', type: 'feature' as const, title: 'Access control', subtitle: 'Manage workspace access', icon: Settings2, run: () => navigate('/administration/access') },
    ] : []),
    { id: 'profile', type: 'feature' as const, title: 'Open profile', subtitle: 'Manage your account', icon: UserCircle2, run: () => navigate('/profile') },
  ], [navigate, roles])

  return (
    <RealtimeProvider>
      <div className="workspace-shell">
        <button className="mobile-menu-button" onClick={() => setMobileOpen(true)} aria-label="Цэс нээх"><Menu /></button>
        <aside className={`workspace-sidebar ${mobileOpen ? 'is-open' : ''}`}>
          <div className="sidebar-brand"><img src={logo || (theme === 'dark' ? '/oyuns-aio-logo.png' : '/favicon.png')} alt="OYUNS" /><button onClick={() => setMobileOpen(false)} aria-label="Цэс хаах"><X /></button></div>
          <nav aria-label="Үндсэн цэс">
            {nav.map(({ to, label, icon: Icon }) => (
              <div className={NAV_GROUP_BREAKS.has(to) ? 'nav-group nav-group-break' : 'nav-group'} key={to}>
                <NavLink to={to} end={to === '/'} className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
                  <Icon size={18} strokeWidth={1.8} aria-hidden /><span>{t(label)}</span>
                </NavLink>
              </div>
            ))}
          </nav>
          <div className="sidebar-footer">
            <NavLink to="/company-files" className={({ isActive }) => isActive ? 'sidebar-library-link active' : 'sidebar-library-link'}><FolderArchive size={17} /><span>{t('nav.companyFiles')}</span></NavLink>
            <div className="sidebar-profile">
              <button className="avatar" onClick={() => navigate('/profile')} aria-label="Профайл нээх">{actorQuery.data?.avatar_url ? <img src={actorQuery.data.avatar_url} alt="" /> : actorQuery.data?.name?.[0]?.toUpperCase() ?? actorQuery.data?.email?.[0]?.toUpperCase() ?? 'O'}</button>
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
              <NotificationCenter />
              <button className="theme-toggle" onClick={() => setTheme((current) => current === 'light' ? 'dark' : 'light')} aria-label={theme === 'light' ? 'Dark mode идэвхжүүлэх' : 'Light mode идэвхжүүлэх'} title={theme === 'light' ? 'Dark mode' : 'Light mode'}>{theme === 'light' ? <Moon size={16} /> : <Sun size={16} />}</button>
              <button className="search-trigger" onClick={() => setCommandOpen(true)}><Search size={16} /><span>{t('action.search')}</span><kbd>⌘K</kbd></button>
              <button className="ai-trigger" onClick={() => setAssistantOpen(true)}><Sparkles size={16} /> OYUNS</button>
            </div>
          </header>
          <div className="workspace-content"><Suspense fallback={<WorkspaceSkeleton />}><Outlet /></Suspense></div>
        </main>
        <nav className="mobile-tabbar" aria-label="Шуурхай цэс">
          {nav.slice(0, 4).map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => isActive ? 'active' : ''}>
              <Icon size={19} strokeWidth={1.9} aria-hidden />
              <span>{t(label)}</span>
            </NavLink>
          ))}
          <button onClick={() => setMobileOpen(true)} aria-label="Бусад цэс нээх">
            <Menu size={20} aria-hidden />
            <span>Бусад</span>
          </button>
        </nav>
        <aside className={`workers-drawer ${workersOpen ? 'open' : ''}`} aria-label="Ажилтны төлөв"><button className="workers-toggle" onClick={() => setWorkersOpen((value) => !value)} aria-label={workersOpen ? 'Ажилтны жагсаалт хаах' : 'Ажилтны жагсаалт нээх'}>{workersOpen ? <ChevronRight /> : <><ChevronLeft /><Users2 /></>}</button>{workersOpen && <div className="workers-content"><header><div><span className="eyebrow">Live presence</span><h2>Ажилтнууд</h2></div><button onClick={() => setWorkersOpen(false)}><X /></button></header><label className="worker-search"><Search size={15} /><input value={workerSearch} onChange={(event) => setWorkerSearch(event.target.value)} placeholder="Ажилтан хайх…" /></label><div className="worker-list">{visibleWorkers.map((worker) => <button key={worker.id} onClick={() => setSelectedWorker(worker.id)}><span className="worker-avatar">{worker.avatar_url ? <img src={worker.avatar_url} alt="" /> : worker.name[0]}</span><span><strong>{worker.name}</strong><small>{worker.presence === 'in_person' ? 'Оффис идэвхтэй' : worker.presence === 'remote' ? 'Remote идэвхтэй' : worker.presence === 'break' ? 'Завсарлага' : 'Offline'} · {worker.job_title || worker.telegram_username || 'Ажилтан'}</small></span><i className={`presence ${worker.presence}`} title={worker.presence} /></button>)}</div>{selectedWorker && <section className="worker-performance">{workerProfile.isLoading ? <p>Профайл ачаалж байна…</p> : <><header><strong>{workerProfile.data?.name}</strong><button onClick={() => setSelectedWorker(undefined)}><X size={14} /></button></header><p>{workerProfile.data?.phone_number || 'Утас оруулаагүй'}<br />{workerProfile.data?.work_direction || 'Чиглэл оруулаагүй'} · {workerProfile.data?.work_branch || 'Ажлын алба оруулаагүй'}</p>{workerProfile.data?.telegram_chat_url && <a className="telegram-chat-action" href={workerProfile.data.telegram_chat_url} target="_blank" rel="noreferrer"><Send size={14} />Telegram-аар чатлах</a>}{canReviewWorkers && <div><span>Ажилласан цаг<strong>{Math.round((workerPerformance.data?.worked_minutes ?? 0) / 60)}ц</strong></span><span>Даалгавар<strong>{workerPerformance.data?.completion_rate ?? 0}%</strong></span><span>Тайлан<strong>{workerPerformance.data?.report_submission_rate ?? 0}%</strong></span></div>}</>}</section>}</div>}</aside>
        <OyunsAssistant open={assistantOpen} onClose={() => setAssistantOpen(false)} />
        <GlobalCommandBar open={commandOpen} onClose={() => setCommandOpen(false)} accountId={actorQuery.data?.id} channels={commandChannels} features={commandFeatures} onWorker={(id) => { setSelectedWorker(id); setWorkersOpen(true) }} />
      </div>
    </RealtimeProvider>
  )
}
