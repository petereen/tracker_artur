import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { api } from '../api/client'
import {
  BarChart3, BriefcaseBusiness, Calculator, BookText, Handshake, PiggyBank, CalendarDays, CheckSquare2, ChevronLeft, ChevronRight, FileCheck2, FileSignature, Goal, KeyRound, ScanLine, UserRoundCog,
  FolderArchive, LayoutDashboard, LayoutGrid, LogOut, MessageCircle, Moon, Search, Send, Settings2, Sparkles, Sun, Users2, X, Upload, UserCircle2,
} from 'lucide-react'
import { isFeatureEnabled, useTenantContext } from '../api/tenancy'
import { acknowledgeChatReceipt, useActor, useBrandingSettings, useChatUnreadCount, useEnterpriseLogout, useERPAccountPermissions, useERPMetadata, useOpenDirectConversation, useWorkerDirectory, useWorkerPerformance, useWorkerProfile } from '../api/enterprise'
import { useCRMCapabilities } from '../api/crm'
import { useBudgetCapabilities } from '../api/budget'
import { EMPTY_ROLES, useAuthStore } from '../store/auth'
import { periodFromPreset } from './TimePeriodFilter'
import { WorkspaceModeProvider } from './WorkspaceModeProvider'
import { WorkspaceModeToggle } from './WorkspaceModeToggle'
import { WorkspaceRouteSkeleton } from './Loading'
import { MobileMoreSheet } from './MobileMoreSheet'
import { PullToRefresh } from './PullToRefresh'
import { getRealtimeUrl, resolvePublicAssetUrl, safeLocalStorage, safeSessionStorage } from '../platform/runtime'
import { useColorThemeStore } from '../store/colorTheme'
import { showDesktopChatAlert } from '../platform/chat-notifications'
import { setTelemetryTag } from '../platform/telemetry'
import { preloadRoute } from '../platform/route-preload'
import { OPEN_ASSISTANT_EVENT, OPEN_SEARCH_EVENT } from '../platform/app-events'

const NAV = [
  { to: '/', label: 'nav.today', icon: LayoutDashboard, roles: [] },
  { to: '/worktime', label: 'nav.worktime', icon: ScanLine, roles: [] },
  { to: '/hr', label: 'nav.hr', icon: UserRoundCog, roles: [] },
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

const NAV_GROUP_BREAKS =new Set(['/calendar', '/reports', '/analytics', '/administration'])
const PAYROLL_ROLES = ['admin', 'hr']
const LazyOyunsAssistant = lazy(() => import('./OyunsAssistant').then((module) => ({ default: module.OyunsAssistant })))
const LazyGlobalCommandBar = lazy(() => import('./GlobalCommandBar').then((module) => ({ default: module.GlobalCommandBar })))
const LazyNotificationCenter = lazy(() => import('./NotificationCenter').then((module) => ({ default: module.NotificationCenter })))

const TITLES: Record<string, string> = {
  '/': 'Өнөөдрийн ажлын орон зай', '/worktime': 'Ажлын цагийн бүртгэл', '/hr': 'Хүний нөөц', '/projects': 'Төслүүд', '/tasks': 'Даалгаврын самбар', '/calendar': 'Календарь',
  '/reports': 'Тайлан ба зөвшөөрөл', '/capacity': 'Багийн ачаалал', '/plans': 'Төлөвлөгөө', '/contracts': 'Гэрээ',
  '/chat': 'Чат',
  '/analytics': 'Гүйцэтгэлийн үзүүлэлт', '/administration': 'Системийн тохиргоо', '/contracts/archive': 'Гэрээний архив',
  '/erp/payroll': 'Цалингийн тооцоо',
  '/erp/crm': 'CRM · Харилцаа холбоо',
  '/erp/crm/customers': 'CRM · Харилцагч',
  '/erp/crm/settings': 'CRM · Тохиргоо',
  '/erp/accounts': 'Дансны төлөвлөгөө',
  '/erp/budget': 'Төсөв, гүйцэтгэл',
  '/erp/budget/analysis': 'Төсөв · Анализ',
  '/erp/budget/accounts': 'Төсөв · Төсөвт данс',
  '/erp/payroll/tax-benefits': 'Татвар ба хангамж',
  '/administration/organization/profile': 'Байгууллагын профайл / Company Profile',
  '/administration/organization/modules': 'Модуль ба боломжууд / Modules & Features',
  '/administration/workflows/worktime': 'Ажлын цаг ба процесс / Worktime & Processes',
  '/administration/workflows/reports': 'Тайлангийн тохиргоо / Report Settings',
  '/administration/people/users': 'Ажилтан ба хэрэглэгч / Employees & Users',
  '/administration/people/permissions': 'Үүрэг ба эрх / Roles & Permissions',
  '/administration/integrations/overview': 'Интеграци ба төхөөрөмж / Integrations & Devices',
  '/administration/security/authentication': 'Нэвтрэлт ба админ / Authentication & Admin',
  '/administration/ai/knowledge': 'OYUNS AI ба сургалт / OYUNS AI & Knowledge',
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
        const topicMap: Record<string, string> = { tasks: 'tasks', projects: 'projects', clocks: 'clock', capacity: 'capacity', reports: 'reports', contracts: 'contracts', contract_archive: 'contract-archive', okrs: 'objectives', notifications: 'notifications', hr: 'hr', company_files: 'company-files', erp: 'erp', chat: 'chat', chat_presence: 'chat' }
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
  const theme = useColorThemeStore((state) => state.theme)
  const setTheme = useColorThemeStore((state) => state.setTheme)
  const workers = useWorkerDirectory(workersOpen)
  const branding = useBrandingSettings()
  const actorResolved = Boolean(actorQuery.data)
  const roles = actorResolved ? actorQuery.data?.roles ?? EMPTY_ROLES : EMPTY_ROLES
  const erp = useERPMetadata(Boolean(token && roles.some((role) => PAYROLL_ROLES.includes(role))))
  const crm = useCRMCapabilities(Boolean(token && actorResolved))
  const showCRM = Boolean(crm.data?.module_enabled && (crm.data.activities.view || crm.data.parties.view))
  const budget = useBudgetCapabilities(Boolean(token && actorResolved))
  const showBudget = Boolean(budget.data?.module_enabled && budget.data.budgets.view)
  const accountPermissions = useERPAccountPermissions(Boolean(token && actorResolved))
  const showAccounts = Boolean(accountPermissions.data?.view)
  // Modules outside the tenant's license disappear from navigation (the API
  // answers 403 feature_not_licensed for them anyway).
  const tenant = useTenantContext(Boolean(token && actorResolved))
  const contractsLicensed = isFeatureEnabled(tenant.data, 'contracts')
  const assistantLicensed = isFeatureEnabled(tenant.data, 'ai_assistant')
  const unreadChat = useChatUnreadCount(Boolean(token))
  const openDirectChat = useOpenDirectConversation()

  const [headerScrolled, setHeaderScrolled] = useState(false)
  useEffect(() => setMobileOpen(false), [location.pathname])
  useEffect(() => {
    let frame = 0
    const onScroll = () => {
      if (frame) return
      frame = window.requestAnimationFrame(() => { frame = 0; setHeaderScrolled(window.scrollY > 4) })
    }
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => { window.removeEventListener('scroll', onScroll); if (frame) window.cancelAnimationFrame(frame) }
  }, [])
  useEffect(() => {
    // Phones: hide the tab bar while the on-screen keyboard is up, like native apps do. A focused
    // field alone isn't enough (autofocus shows no keyboard), so also require the viewport to shrink.
    const root = document.documentElement
    const viewport = window.visualViewport
    const coarse = window.matchMedia?.('(pointer: coarse)')
    const isEditable = (node: Element | null) => node instanceof HTMLElement && (node.isContentEditable || (node.tagName === 'INPUT' && !['checkbox', 'radio', 'range', 'button', 'submit', 'file', 'color'].includes((node as HTMLInputElement).type)) || node.tagName === 'TEXTAREA')
    const height = () => viewport?.height ?? window.innerHeight
    let baseline = height()
    let baselineWidth = window.innerWidth
    const update = () => {
      const current = height()
      const editing = isEditable(document.activeElement)
      if (window.innerWidth !== baselineWidth) { baselineWidth = window.innerWidth; baseline = current }
      if (!editing) baseline = current
      baseline = Math.max(baseline, current)
      root.classList.toggle('keyboard-open', Boolean(coarse?.matches) && editing && baseline - current > 150)
    }
    const deferredUpdate = () => window.setTimeout(update, 80)
    viewport?.addEventListener('resize', update)
    window.addEventListener('resize', update)
    document.addEventListener('focusin', deferredUpdate)
    document.addEventListener('focusout', deferredUpdate)
    return () => {
      viewport?.removeEventListener('resize', update)
      window.removeEventListener('resize', update)
      document.removeEventListener('focusin', deferredUpdate)
      document.removeEventListener('focusout', deferredUpdate)
      root.classList.remove('keyboard-open')
    }
  }, [])
  useEffect(() => {
    const normalizedRoute = location.pathname
      .replace(/\/\d+(?=\/|$)/g, '/:id')
      .replace(/\/[^/]+(?=\/print$)/g, '/:publicId')
    const viewport = window.innerWidth < 800 ? 'mobile' : window.innerWidth < 1200 ? 'tablet' : 'desktop'
    setTelemetryTag('loading.route', normalizedRoute || '/')
    setTelemetryTag('loading.viewport', viewport)
    setTelemetryTag('loading.version', 'skeleton-v1')
  }, [location.pathname])
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
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault(); setCommandOpen((open) => !open)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  // Pages (e.g. Today quick actions) open search / the assistant without prop drilling.
  useEffect(() => {
    const openSearch = () => setCommandOpen(true)
    const openAssistant = () => { if (assistantLicensed) setAssistantOpen(true) }
    window.addEventListener(OPEN_SEARCH_EVENT, openSearch)
    window.addEventListener(OPEN_ASSISTANT_EVENT, openAssistant)
    return () => {
      window.removeEventListener(OPEN_SEARCH_EVENT, openSearch)
      window.removeEventListener(OPEN_ASSISTANT_EVENT, openAssistant)
    }
  }, [assistantLicensed])

  useEffect(() => {
    if (actorQuery.data) setActor(actorQuery.data)
  }, [actorQuery.data, setActor])
  useEffect(() => {
    if (actorQuery.data?.locale && i18n.language !== actorQuery.data.locale) i18n.changeLanguage(actorQuery.data.locale)
  }, [actorQuery.data?.locale, i18n])
  const nav = useMemo(() => {
    const hrItem = NAV.find((item) => item.to === '/hr')
    const payrollItem = { to: '/erp/payroll', label: 'Цалин', icon: Calculator, roles: [] }
    const base = NAV.filter((item) => item.to !== '/hr' && (item.to !== '/contracts' || contractsLicensed) && (!item.roles.length || item.roles.some((role) => roles.includes(role))))
    const showPayroll = Boolean(erp.data?.modules.payroll && roles.some((role) => PAYROLL_ROLES.includes(role)))
    const withHr = base.flatMap((item) => item.to === '/chat' && hrItem ? [hrItem, item] : [item])
    // CRM access comes from ERP capabilities, so sales staff without a
    // management role still see it; it sits just above Settings.
    const crmItem = { to: '/erp/crm', label: 'CRM', icon: Handshake, roles: [] }
    const budgetItem = { to: '/erp/budget', label: 'Төсөв', icon: PiggyBank, roles: [] }
    // Chart of accounts: the one place to manage the accounts payroll and budget pick from.
    const accountsItem = { to: '/erp/accounts', label: 'Данс', icon: BookText, roles: [] }
    const capabilityItems = [...(showCRM ? [crmItem] : []), ...(showAccounts ? [accountsItem] : []), ...(showBudget ? [budgetItem] : [])]
    const withCRM = (items: typeof withHr) => (capabilityItems.length ? [...items.slice(0, -1), ...capabilityItems, items[items.length - 1]] : items)
    // ERP modules have no hub page of their own: each enabled module gets its
    // own entry, and module switches live in Settings → Modules.
    return withCRM(showPayroll ? [...withHr.slice(0, -1), payrollItem, withHr[withHr.length - 1]] : withHr)
  }, [contractsLicensed, erp.data, roles, showAccounts, showBudget, showCRM])
  const canReviewWorkers = roles.some((role) => ['admin', 'manager', 'team_lead'].includes(role))
  const workerPerformance = useWorkerPerformance(selectedWorker, periodFromPreset('week'), canReviewWorkers)
  const workerProfile = useWorkerProfile(selectedWorker)
  const visibleWorkers = useMemo(() => (workers.data ?? []).filter((worker) => worker.name.toLowerCase().includes(workerSearch.toLowerCase())), [workerSearch, workers.data])
  const title = useMemo(() => {
    if (TITLES[location.pathname]) return TITLES[location.pathname]
    const section = Object.keys(TITLES).filter((path) => path !== '/' && location.pathname.startsWith(`${path}/`)).sort((a, b) => b.length - a.length)[0]
    return section ? TITLES[section] : 'OYUNS Workspace'
  }, [location.pathname])
  const logo = theme === 'dark' ? branding.data?.dark_logo : branding.data?.light_logo
  const commandChannels = useMemo(() => [...nav, { to: '/company-files', label: 'nav.companyFiles', icon: FolderArchive, roles: [] }].map((item) => ({ id: item.to, type: 'channel' as const, title: 'settings' in item ? String(item.label) : t(item.label), subtitle: 'Workspace section', icon: item.icon, run: () => navigate(item.to) })), [nav, navigate, t])
  const commandFeatures = useMemo(() => [
    { id: 'create-task', type: 'feature' as const, title: 'Create task', subtitle: 'Open a new task form', icon: CheckSquare2, run: () => navigate('/tasks?create=1') },
    { id: 'create-contract', type: 'feature' as const, title: 'Create contract', subtitle: 'Open a new contract draft', icon: FileSignature, run: () => navigate('/contracts?create=1') },
    { id: 'upload-file', type: 'feature' as const, title: 'Upload file', subtitle: 'Open the company file uploader', icon: Upload, run: () => navigate('/company-files?upload=1') },
    ...(roles.some((role) => ['admin', 'manager', 'team_lead'].includes(role)) ? [
      { id: 'workspace-settings', type: 'feature' as const, title: 'Байгууллага / Organization', subtitle: 'Профайл ба брэндинг / Profile & branding', icon: Settings2, run: () => navigate('/administration/organization/profile') },
      { id: 'collaboration-settings', type: 'feature' as const, title: 'Ажлын цаг / Worktime', subtitle: 'Check-in ба процесс / Check-in & workflows', icon: Users2, run: () => navigate('/administration/workflows/worktime') },
      ...(roles.includes('admin') ? [{ id: 'access-settings', type: 'feature' as const, title: 'Хэрэглэгч ба эрх / People & access', subtitle: 'Ажилтан, role ба эрх / Employees, roles & permissions', icon: Settings2, run: () => navigate('/administration/people/users') }] : []),
    ] : []),
    { id: 'profile', type: 'feature' as const, title: 'Open profile', subtitle: 'Manage your account', icon: UserCircle2, run: () => navigate('/profile') },
  ], [navigate, roles])
  const mobileNav = useMemo(() => ['/', '/calendar', '/tasks', '/chat'].map((to) => nav.find((item) => item.to === to)).filter(Boolean) as typeof nav, [nav])
  const moreNav = useMemo(() => nav.filter((item) => !mobileNav.includes(item)), [mobileNav, nav])
  const moreActive = !mobileNav.some((item) => item.to === '/' ? location.pathname === '/' : location.pathname.startsWith(item.to))
  const unreadCount = unreadChat.data?.unread_count ?? 0
  const isChatRoute = location.pathname.startsWith('/chat')
  const avatarContent = actorQuery.data?.avatar_url ? <img src={resolvePublicAssetUrl(actorQuery.data.avatar_url) || undefined} alt="" /> : actorQuery.data?.name?.[0]?.toUpperCase() ?? actorQuery.data?.email?.[0]?.toUpperCase() ?? 'O'
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
        <aside className="workspace-sidebar">
          <div className="sidebar-brand">{branding.isPending ? null : <img src={logo || (theme === 'dark' ? '/oyuns-aio-logo.png' : '/favicon.png')} alt="OYUNS" />}</div>
          <nav aria-label="Үндсэн цэс">
            {nav.map(({ to, label, icon: Icon }) => (
              <div className={NAV_GROUP_BREAKS.has(to) ? 'nav-group nav-group-break' : 'nav-group'} key={to}>
                <NavLink to={to} end={to === '/'} onMouseEnter={() => preloadRoute(to)} onFocus={() => preloadRoute(to)} className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
                  <Icon size={18} strokeWidth={1.8} aria-hidden /><span>{t(label)}</span>{to === '/chat' && Boolean(unreadChat.data?.unread_count) && <b className="nav-unread-badge" aria-label={`${unreadChat.data?.unread_count} уншаагүй чат`}>{(unreadChat.data?.unread_count ?? 0) > 99 ? '99+' : unreadChat.data?.unread_count}</b>}
                </NavLink>
              </div>
            ))}
          </nav>
          <div className="sidebar-footer">
            <NavLink to="/company-files" className={({ isActive }) => isActive ? 'sidebar-library-link active' : 'sidebar-library-link'}><FolderArchive size={17} /><span>{t('nav.companyFiles')}</span></NavLink>
            <div className="sidebar-profile">
              <button className="avatar" onClick={() => navigate('/profile')} aria-label="Профайл нээх">{avatarContent}</button>
              <button className="profile-identity" onClick={() => navigate('/profile')}><strong>{actorQuery.data?.name ?? actorQuery.data?.email ?? '…'}</strong><span>{roles[0] ?? 'member'}</span></button>
              <button onClick={() => logout.mutate()} aria-label={t('action.logout')}><LogOut size={17} /></button>
            </div>
          </div>
        </aside>
        <main className="workspace-main">
          <header className={`workspace-header ${headerScrolled ? 'is-scrolled' : ''}`}>
            <button className="avatar header-avatar" onClick={() => navigate('/profile')} aria-label="Профайл нээх">{avatarContent}</button>
            <h1>{title}</h1>
            <div className="header-actions">
              <WorkspaceModeToggle />
              <Suspense fallback={null}><LazyNotificationCenter /></Suspense>
              <button className="theme-toggle" onClick={() => setTheme((current) => current === 'light' ? 'dark' : 'light')} aria-label={theme === 'light' ? 'Dark mode идэвхжүүлэх' : 'Light mode идэвхжүүлэх'} title={theme === 'light' ? 'Dark mode' : 'Light mode'}>{theme === 'light' ? <Moon size={16} /> : <Sun size={16} />}</button>
              <button className="search-trigger" onClick={() => setCommandOpen(true)}><Search size={16} /><span>{t('action.search')}</span><kbd>⌘K</kbd></button>
              {assistantLicensed && <button className="ai-trigger" onClick={() => setAssistantOpen(true)}><Sparkles size={16} /> OYUNS</button>}
            </div>
          </header>
          <PullToRefresh enabled={!isChatRoute} />
          <div className={`workspace-content ${isChatRoute ? 'chat-route-content' : ''}`}><Suspense fallback={<WorkspaceRouteSkeleton pathname={location.pathname} />}><Outlet /></Suspense></div>
        </main>
        <nav className="mobile-tabbar" aria-label="Шуурхай цэс">
          {mobileNav.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === '/'} onTouchStart={() => preloadRoute(to)} onClick={() => { if (location.pathname === to) window.scrollTo({ top: 0, behavior: 'smooth' }) }} className={({ isActive }) => isActive ? 'active' : ''}>
              <span className="mobile-tab-icon"><Icon size={20} strokeWidth={1.9} aria-hidden />{to === '/chat' && unreadCount > 0 && <b className="nav-unread-badge" aria-label={`${unreadCount} уншаагүй чат`}>{unreadCount > 99 ? '99+' : unreadCount}</b>}</span>
              <span>{t(label)}</span>
            </NavLink>
          ))}
          <button className={mobileOpen || moreActive ? 'active' : ''} onClick={() => setMobileOpen(true)} aria-label="Бусад цэс нээх" aria-expanded={mobileOpen} aria-haspopup="dialog">
            <span className="mobile-tab-icon"><LayoutGrid size={20} strokeWidth={1.9} aria-hidden /></span>
            <span>Бусад</span>
          </button>
        </nav>
        <MobileMoreSheet
          open={mobileOpen}
          onClose={() => setMobileOpen(false)}
          items={moreNav}
          unreadChat={unreadCount}
          actor={actorQuery.data}
          role={roles[0]}
          theme={theme}
          onToggleTheme={() => setTheme((current) => current === 'light' ? 'dark' : 'light')}
          onSearch={() => setCommandOpen(true)}
          onWorkers={() => setWorkersOpen(true)}
          onLogout={() => logout.mutate()}
        />
        {workersOpen && <button type="button" className="workers-scrim" aria-label="Ажилтны жагсаалт хаах" onClick={() => setWorkersOpen(false)} />}
        <aside ref={workersDrawerRef} className={`workers-drawer ${workersOpen ? 'open' : ''} ${workersDragging ? 'is-dragging' : ''}`} style={{ '--workers-toggle-y': `${workersToggleY}px` } as React.CSSProperties} aria-label="Ажилтны төлөв"><button ref={workersToggleRef} className="workers-toggle" onPointerDown={handleWorkersPointerDown} onPointerMove={handleWorkersPointerMove} onPointerUp={finishWorkersPointer} onPointerCancel={finishWorkersPointer} onClick={handleWorkersClick} aria-label="Ажилтны жагсаалт нээх"><ChevronLeft /><Users2 /></button><div className="workers-content"><header><div><span className="eyebrow">OYUNS</span><h2>Ажилтнууд</h2></div><button onClick={() => setWorkersOpen(false)} aria-label="Ажилтны жагсаалт хаах"><X /></button></header><label className="worker-search"><Search size={15} /><input value={workerSearch} onChange={(event) => setWorkerSearch(event.target.value)} placeholder="Ажилтан хайх…" /></label><div className="worker-list">{visibleWorkers.map((worker) => <button key={worker.id} onClick={() => setSelectedWorker(worker.id)}><span className="worker-avatar">{worker.avatar_url ? <img src={resolvePublicAssetUrl(worker.avatar_url) || undefined} alt="" /> : worker.name[0]}</span><span><strong>{worker.name}</strong><small>{worker.presence === 'in_person' ? 'Оффис идэвхтэй' : worker.presence === 'remote' ? 'Remote идэвхтэй' : worker.presence === 'break' ? 'Завсарлага' : 'Offline'} · {worker.job_title || worker.telegram_username || 'Ажилтан'}</small></span><i className={`presence ${worker.presence}`} title={worker.presence} /></button>)}</div>{selectedWorker && <section className="worker-performance">{workerProfile.isLoading ? <p>Профайл ачаалж байна…</p> : <><header><strong>{workerProfile.data?.name}</strong><button onClick={() => setSelectedWorker(undefined)}><X size={14} /></button></header><p>{workerProfile.data?.phone_number || 'Утас оруулаагүй'}<br />{workerProfile.data?.work_direction || 'Чиглэл оруулаагүй'} · {workerProfile.data?.work_branch || 'Ажлын алба оруулаагүй'}</p><div className="worker-chat-actions"><button className="worker-inapp-chat" disabled={!workerProfile.data?.chat_available || openDirectChat.isPending} onClick={() => selectedWorker && openWorkerChat(selectedWorker)}>Чатлах</button>{workerProfile.data?.telegram_chat_url && <a className="telegram-chat-action" href={workerProfile.data.telegram_chat_url} target="_blank" rel="noreferrer" aria-label="Telegram-аар чатлах" title="Telegram-аар чатлах"><Send size={17} /></a>}</div>{!workerProfile.data?.chat_available && <small className="worker-chat-hint">Workspace хандалт холбосны дараа чатлах боломжтой.</small>}{canReviewWorkers && <div><span>Ажилласан цаг<strong>{Math.round((workerPerformance.data?.worked_minutes ?? 0) / 60)}ц</strong></span><span>Даалгавар<strong>{workerPerformance.data?.completion_rate ?? 0}%</strong></span><span>Тайлан<strong>{workerPerformance.data?.report_submission_rate ?? 0}%</strong></span></div>}</>}</section>}</div></aside>
        {assistantOpen && <Suspense fallback={null}><LazyOyunsAssistant open onClose={() => setAssistantOpen(false)} /></Suspense>}
        {commandOpen && <Suspense fallback={null}><LazyGlobalCommandBar open onClose={() => setCommandOpen(false)} accountId={actorQuery.data?.id} channels={commandChannels} features={commandFeatures} onWorker={(id) => { setSelectedWorker(id); setWorkersOpen(true) }} /></Suspense>}
      </div>
    </RealtimeProvider>
    </WorkspaceModeProvider>
  )
}
