import { useState, type ReactNode } from 'react'
import { ArrowLeft, Bot, BookOpen, Boxes, CalendarClock, CalendarDays, ClipboardList, Code2, KeyRound, Landmark, MonitorUp, Settings2, ShieldCheck, UserPlus, UserRoundCog, Users2 } from 'lucide-react'
import { Link, NavLink } from 'react-router-dom'
import toast from 'react-hot-toast'
import { type ERPModule, useBrandingSettings, useCreateManagedAccount, useCreateWorktimeQrKiosk, useERPMetadata, useGoogleCalendarConnect, useGoogleCalendarDisconnect, useGoogleCalendarStatus, useGoogleCalendarSyncMode, useManagedAccounts, usePermissionSettings, useRenewWorktimeQrPairingCode, useRevokeWorktimeQrKiosk, useUpdateBrandingSettings, useUpdateERPModules, useUpdateManagedAccount, useUpdatePermissionSettings, useUploadBrandingLogo, useWorktimeQrKiosks } from '../api/enterprise'
import { EMPTY_ROLES, useAuthStore } from '../store/auth'
import { EmployeesPage } from './EmployeesPage'
import { QuestionsPage } from './QuestionsPage'
import { SchedulePage } from './SchedulePage'
import { AdminAccessPanel, ManagerSettingsPage } from './ManagerSettingsPage'
import { KnowledgePage } from './KnowledgePage'
import { OnboardingPage } from './OnboardingPage'
import { DeveloperPage } from './DeveloperPage'
import { ERPBuilderPanels } from '../components/ERPBuilderPanels'

const SETTINGS = [
  { to: '/administration/workspace', title: 'Logo оруулах', text: 'Лого, light болон dark горим', icon: Settings2 },
  { to: '/administration/collaboration', title: 'Чек ин тохиргоо', text: 'Даалгавар, check-in болон ажлын хуваарь', icon: UserRoundCog },
  { to: '/administration/access', title: 'Хандалтын удирдлага', text: 'Ажилтан, Telegram холболт, эрх ба төлөв', icon: ShieldCheck },
  { to: '/administration/automation', title: 'Автоматжуулалт ба интеграци', text: 'Telegram мэдэгдэл, календарь, онбординг', icon: CalendarClock },
  { to: '/administration/erp', title: 'ERP модулиуд', text: 'Санхүү, борлуулалт, агуулах болон бусад workflow', icon: Landmark },
  { to: '/administration/admin-access', title: 'Админ хандалт', text: 'Админ хэрэглэгч, нууц үг болон эрх', icon: KeyRound },
  { to: '/administration/oyuns', title: 'OYUNS agent', text: 'Компаний өгөгдлийн сан ба агентын сургалт', icon: Bot },
]

const ROLES = [
  ['member', 'Member'], ['manager', 'Supervisor'], ['team_lead', 'Team lead'], ['hr', 'HR'],
  ['contractor', 'Contractor'], ['client_auditor', 'Client auditor'], ['admin', 'Admin'],
] as const

function SettingsPage({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return <div className="settings-page">
    <nav className="settings-subnav" aria-label="Системийн тохиргооны цэс">
      <Link to="/administration" className="settings-back"><ArrowLeft size={15} />Бүх тохиргоо</Link>
      <div>{SETTINGS.map(({ to, title: itemTitle, icon: Icon }) => <NavLink key={to} to={to}><Icon size={15} /><span>{itemTitle}</span></NavLink>)}</div>
    </nav>
    <div className="view-toolbar settings-page-heading"><div><h2>{title}</h2><p>{description}</p></div></div>
    <div className="settings-content">{children}</div>
  </div>
}

function BrandingSettingsPanel() {
  const branding = useBrandingSettings()
  const update = useUpdateBrandingSettings()
  const upload = useUploadBrandingLogo()
  const sourceFor = (theme: 'light' | 'dark') => {
    const source = theme === 'light' ? branding.data?.light_source : branding.data?.dark_source
    return source?.startsWith('data:image/') ? 'uploaded' : source || 'default'
  }
  const select = (theme: 'light' | 'dark', source: string) => {
    if (source !== 'uploaded') update.mutate({ theme, source: source as 'legacy-aio' | 'legacy-icon' | 'default' })
  }
  return <section className="branding-settings panel"><div className="panel-heading"><div><span className="eyebrow">Workspace identity</span><h2>Лого ба theme</h2><p>Light болон dark горимд тусдаа лого сонгох эсвэл шинэ зураг байршуулна.</p></div><Settings2 /></div><div className="branding-grid">{(['light', 'dark'] as const).map((theme) => {
    const logo = theme === 'light' ? branding.data?.light_logo : branding.data?.dark_logo
    return <article className={`branding-card ${theme}`} key={theme}><div className="branding-preview"><img src={logo || '/favicon.png'} alt={`${theme} logo preview`} /></div><div className="branding-card-body"><strong>{theme === 'light' ? 'Light mode' : 'Dark mode'}</strong><select aria-label={`${theme} logo сонгох`} value={sourceFor(theme)} onChange={(event) => select(theme, event.target.value)} disabled={branding.isLoading || update.isPending}><option value="default">Автомат legacy</option>{branding.data?.legacy_options.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}{sourceFor(theme) === 'uploaded' && <option value="uploaded">Uploaded logo</option>}</select><label className="secondary-action compact branding-upload"><span>Шинэ зураг сонгох</span><input type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => { const file = event.target.files?.[0]; if (file) upload.mutate({ theme, file }); event.currentTarget.value = '' }} disabled={upload.isPending} /></label></div></article>
  })}</div></section>
}

function ERPModuleSettingsPanel() {
  const metadata = useERPMetadata()
  const updateModules = useUpdateERPModules()
  const modules = metadata.data ? (Object.keys(metadata.data.modules) as ERPModule[]) : []

  const toggleModule = (module: ERPModule) => {
    if (!metadata.data) return
    updateModules.mutate({ ...metadata.data.modules, [module]: !metadata.data.modules[module] }, {
      onSuccess: () => toast.success('ERP module visibility updated'),
      onError: (error: any) => toast.error(error.response?.data?.detail || 'Module settings could not be updated'),
    })
  }

  if (metadata.isLoading) return <section className="account-admin panel"><p>ERP тохиргоог уншиж байна…</p></section>
  if (metadata.isError || !metadata.data) return <section className="account-admin panel"><div className="panel-heading"><div><span className="eyebrow">Configurable ERP</span><h2>ERP үйлчилгээ холбогдсонгүй</h2><p>ERP migration болон backend service ажиллаж байгаа эсэхийг шалгана уу.</p></div><Landmark /></div></section>

  return <section className="account-admin panel erp-admin-panel">
    <div className="panel-heading"><div><span className="eyebrow">Configurable ERP</span><h2>ERP модулиуд</h2><p>Эндээс байгууллагадаа хэрэгтэй workflow-уудыг асаана. Visibility нь permission/security control биш.</p></div><Boxes /></div>
    <div className="erp-module-grid" aria-label="ERP module visibility">
      {modules.map((module) => {
        const enabled = metadata.data.modules[module]
        const label = metadata.data.module_labels[module] || module
        return <article key={module} className={`panel erp-module-card ${enabled ? 'enabled' : ''}`}><Landmark size={21} /><div><strong>{label}</strong><small>{enabled ? 'Workspace-д харагдана' : 'Workspace-ээс нуусан'}</small></div><button className="erp-toggle" onClick={() => toggleModule(module)} disabled={updateModules.isPending} aria-label={`${label} ${enabled ? 'disable' : 'enable'}`}><span /></button></article>
      })}
    </div>
    <p className="erp-settings-notice"><ShieldCheck size={15} /> API, posting, audit болон integrations нь capability-ээр хамгаалагдсан хэвээр.</p>
    <Link className="secondary-action compact erp-admin-open" to="/erp">ERP workspace нээх</Link>
  </section>
}

export function AdministrationHubPage() {
  return <div className="settings-overview"><div className="view-toolbar"><div><h2>Системийн тохиргоо</h2><p></p></div><Settings2 /></div><div className="settings-category-grid">{SETTINGS.map(({ to, title, text, icon: Icon }) => <Link to={to} key={to}><Icon /><div><strong>{title}</strong><span>{text}</span></div></Link>)}</div></div>
}

export function WorkspaceIdentitySettingsPage() {
  return <SettingsPage title="Logo оруулах" description="Танай байгууллагын лого болон theme бүрийн харагдах байдлыг удирдана."><BrandingSettingsPanel /></SettingsPage>
}

export function ERPSettingsPage() {
  return <SettingsPage title="ERP модулиуд" description="ERP workflow-уудын харагдац, role болон үүсгэх маягтыг удирдана."><ERPModuleSettingsPanel /><ERPBuilderPanels /></SettingsPage>
}

export function CollaborationSettingsPage() {
  const permissions = usePermissionSettings()
  const updatePermissions = useUpdatePermissionSettings()
  const actorRoles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const canManagePermissions = actorRoles.some((item) => ['admin', 'manager'].includes(item))
  return <SettingsPage title="Чек ин тохиргоо" description="Даалгавар оноох дүрэм, check-in урсгал, ажилтны хуваарийг нэг дор тохируулна.">
    {canManagePermissions && <section className="account-admin panel"><div className="panel-heading"><div><span className="eyebrow">Collaboration access</span><h2>Даалгавар оноох эрх</h2><p>Сонгосон role-той, ажилтантай холбогдсон хэрэглэгч бусад ажилтанд даалгавар өгч болно.</p></div><UserRoundCog /></div><fieldset className="role-editor"><legend>Даалгавар оноож болох role</legend>{ROLES.map(([value, label]) => <label key={value}><input type="checkbox" checked={permissions.data?.task_assignment_roles.includes(value) ?? true} onChange={() => { const current = permissions.data?.task_assignment_roles ?? ROLES.map(([name]) => name); updatePermissions.mutate(current.includes(value) ? current.filter((item) => item !== value) : [...current, value]) }} disabled={updatePermissions.isPending} /><span>{label}</span></label>)}</fieldset></section>}
    <section className="settings-embedded"><div className="settings-embedded-heading"><ClipboardList /><div><h3>Check-in асуултууд</h3><p>Өдрийн асуултын банк болон хариулах хүрээ.</p></div></div><QuestionsPage /></section>
    <section className="settings-embedded"><div className="settings-embedded-heading"><CalendarDays /><div><h3>Ажилтны хуваарь</h3><p>Check-in, сануулга болон ажлын өдрүүд.</p></div></div><SchedulePage /></section>
    <WorktimeQrKioskPanel />
  </SettingsPage>
}

function WorktimeQrKioskPanel() {
  const kiosks = useWorktimeQrKiosks()
  const create = useCreateWorktimeQrKiosk()
  const renew = useRenewWorktimeQrPairingCode()
  const revoke = useRevokeWorktimeQrKiosk()
  const [label, setLabel] = useState('Main office display')
  const [locationId, setLocationId] = useState('main_office')
  const [displayName, setDisplayName] = useState('Main office')
  const [pairingCode, setPairingCode] = useState<string | null>(null)
  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    try {
      const result = await create.mutateAsync({ label, location_id: locationId, display_name: displayName })
      setPairingCode(result.pairing_code || null)
    } catch (error: any) {
      const detail = error?.response?.data?.detail
      toast.error(typeof detail === 'object' ? detail.message || 'QR дэлгэц үүсгэсэнгүй' : detail || 'QR дэлгэц үүсгэсэнгүй')
    }
  }
  const renewPairing = async (id: number) => {
    try {
      setPairingCode((await renew.mutateAsync(id)).pairing_code || null)
    } catch (error: any) {
      const detail = error?.response?.data?.detail
      toast.error(typeof detail === 'object' ? detail.message || 'Pairing код шинэчилсэнгүй' : detail || 'Pairing код шинэчилсэнгүй')
    }
  }
  return <section className="settings-embedded worktime-kiosk-admin"><div className="settings-embedded-heading"><MonitorUp /><div><h3>Worktime QR дэлгэц</h3><p>TV дэлгэцийг pairing кодоор нэг удаа холбож, оффисын динамик QR үүсгэнэ.</p></div></div><form className="kiosk-create-form" onSubmit={submit}><label>Дэлгэцийн нэр<input value={label} onChange={(event) => setLabel(event.target.value)} required /></label><label>Location ID<input value={locationId} onChange={(event) => setLocationId(event.target.value)} pattern="[A-Za-z0-9_-]+" required /></label><label>Харагдах нэр<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} required /></label><button className="primary-action" disabled={create.isPending}>Pairing код үүсгэх</button></form>{pairingCode && <div className="kiosk-pairing-code" role="status"><strong>{pairingCode}</strong><span>Энэ кодыг TV дээрх <a href="/worktimeqr" target="_blank" rel="noreferrer">/worktimeqr</a> дэлгэцэд 10 минутын дотор оруулна уу.</span><button className="secondary-action compact" onClick={() => navigator.clipboard?.writeText(pairingCode)}>Хуулах</button></div>}{kiosks.isError && <div className="worktime-alert error" role="alert"><ShieldCheck size={17} />QR дэлгэцийн өгөгдлийн хүснэгт бэлэн биш байна. Backend migration-ийг ажиллуулаад дахин оролдоно уу.</div>}<div className="kiosk-list">{kiosks.isLoading ? <p>Дэлгэцүүдийг ачаалж байна…</p> : (kiosks.data ?? []).map((kiosk) => <article key={kiosk.id} className={`kiosk-row ${kiosk.status}`}><div><strong>{kiosk.display_name}</strong><span>{kiosk.label} · {kiosk.location_id} · {kiosk.status === 'active' ? 'Идэвхтэй' : 'Цуцлагдсан'}</span></div>{kiosk.status === 'active' && <div className="kiosk-row-actions"><button className="secondary-action compact" onClick={() => renewPairing(kiosk.id)} disabled={renew.isPending}>Дахин pair хийх</button><button className="danger-action compact" onClick={() => revoke.mutate(kiosk.id)} disabled={revoke.isPending}>Цуцлах</button></div>}</article>)}</div></section>
}

function UnlinkedAccountsPanel() {
  const accounts = useManagedAccounts()
  const createAccount = useCreateManagedAccount()
  const updateAccount = useUpdateManagedAccount()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('member')
  const unlinkedAccounts = accounts.data?.filter((account) => !account.employee_id) ?? []
  const create = async (event: React.FormEvent) => {
    event.preventDefault()
    try {
      await createAccount.mutateAsync({ email: username, password, roles: [role], locale: 'mn' })
      setUsername(''); setPassword(''); toast.success('Хэрэглэгч үүслээ')
    } catch (error: any) { toast.error(error.response?.data?.detail || 'Хэрэглэгч үүссэнгүй') }
  }
  const toggleRole = (account: { id: number; roles: string[] }, roleName: string) => {
    const roles = account.roles.includes(roleName) ? account.roles.filter((item) => item !== roleName) : [...account.roles, roleName]
    if (!roles.length) { toast.error('Хэрэглэгч дор хаяж нэг эрхтэй байна'); return }
    updateAccount.mutate({ id: account.id, roles })
  }
  const changePassword = async (account: { id: number; email: string }) => {
    const next = window.prompt(`${account.email} шинэ нууц үг (10+ тэмдэгт):`)
    if (!next) return
    if (next.length < 10) { toast.error('Нууц үг 10+ тэмдэгт байх ёстой'); return }
    try { await updateAccount.mutateAsync({ id: account.id, password: next }); toast.success('Нууц үг шинэчлэгдлээ') } catch { /* API hook displays server feedback */ }
  }
  return <section className="account-admin panel"><div className="panel-heading"><div><span className="eyebrow">Standalone access</span><h2>Ажилтантай холбогдоогүй хэрэглэгчид</h2><p>Системийн хэрэглэгчийг энд үүсгэнэ. Ажилтны хандалтыг ажилтны хүснэгтээс холбоно.</p></div><Users2 /></div><form className="account-create-form" onSubmit={create}><label>Username<input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required /></label><label>Password<input value={password} onChange={(event) => setPassword(event.target.value)} type="password" minLength={10} autoComplete="new-password" required /></label><label>Role<select value={role} onChange={(event) => setRole(event.target.value)}>{ROLES.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label><button className="primary-action compact" disabled={createAccount.isPending}><UserPlus size={15} />Нэмэх</button></form><div className="account-list" aria-live="polite">{unlinkedAccounts.map((account) => <article key={account.id}><div className="account-identity"><strong>{account.email}</strong><span>{account.status} · ажилтантай холбоогүй</span></div><fieldset className="role-editor"><legend>Access roles</legend>{ROLES.map(([value, label]) => <label key={value}><input type="checkbox" checked={account.roles.includes(value)} onChange={() => toggleRole(account, value)} disabled={updateAccount.isPending} /><span>{label}</span></label>)}</fieldset><div><button className="icon-action" onClick={() => changePassword(account)} aria-label={`${account.email} password солих`}><KeyRound size={15} /></button><button className="secondary-action compact" onClick={() => updateAccount.mutate({ id: account.id, status: account.status === 'disabled' ? 'active' : 'disabled' })}>{account.status === 'disabled' ? 'Идэвхжүүлэх' : 'Идэвхгүй болгох'}</button></div></article>)}</div></section>
}

export function AccessControlSettingsPage() {
  return <SettingsPage title="Хандалтын удирдлага" description="Ажилтан, Telegram холболт, холбогдсон бүртгэл болон access role-уудыг нэг газраас удирдана."><section className="settings-embedded access-settings"><div className="settings-embedded-heading"><Users2 /><div><h3>Ажилтан ба эрхүүд</h3><p>Ажилтны бүртгэлээс хандалт холбож, role болон идэвхтэй төлвийг шинэчилнэ.</p></div></div><EmployeesPage /></section><UnlinkedAccountsPanel /></SettingsPage>
}

export function AutomationSettingsPage() {
  const calendar = useGoogleCalendarConnect()
  const calendarStatus = useGoogleCalendarStatus()
  const syncMode = useGoogleCalendarSyncMode()
  const disconnect = useGoogleCalendarDisconnect()
  const connectCalendar = async () => {
    try {
      const result = await calendar.mutateAsync()
      if (result.authorization_url) window.location.assign(result.authorization_url)
      else toast.error('Google OAuth тохиргоо дутуу байна')
    } catch { /* mutation feedback is handled by the API hook */ }
  }
  return <SettingsPage title="Автоматжуулалт ба интеграци" description="Telegram мэдэгдэл, Google Calendar болон шинэ ажилтны урсгалыг тохируулна.">
    <section className="integration-grid settings-integrations"><article className="panel integration-panel"><CalendarClock /><div><strong>Google Calendar</strong><p>{calendarStatus.data?.status === 'active' ? `Холбогдсон · webhook ${calendarStatus.data.watch_active ? 'идэвхтэй' : 'шинэчлэгдэж байна'}${calendarStatus.data.last_error ? ` · ${calendarStatus.data.last_error}` : ''}` : 'Өөрийн Google Calendar-тай даалгаврын хугацааг синк хийнэ.'}</p>{calendarStatus.data?.status === 'active' && <select aria-label="Calendar sync mode" value={calendarStatus.data.sync_mode} onChange={(event) => syncMode.mutate(event.target.value as 'outbound' | 'bidirectional')}><option value="outbound">Зөвхөн OYUNS → Google</option><option value="bidirectional">Хоёр чиглэлтэй хугацааны sync</option></select>}</div>{calendarStatus.data?.status === 'active' ? <button className="secondary-action" onClick={() => disconnect.mutate()} disabled={disconnect.isPending}>Салгах</button> : <button className="secondary-action" onClick={connectCalendar} disabled={calendar.isPending}>Холбох</button>}</article></section>
    <section className="settings-embedded"><div className="settings-embedded-heading"><UserRoundCog /><div><h3>Мэдэгдэл ба Telegram</h3><p>Удирдлагын хураангуй, мэдэгдэл болон Telegram тохиргоо.</p></div></div><ManagerSettingsPage /></section>
    <section className="settings-embedded"><div className="settings-embedded-heading"><Bot /><div><h3>Онбординг</h3><p>Шинэ ажилтны мэндчилгээ болон зөөлөн эхлэл.</p></div></div><OnboardingPage /></section>
  </SettingsPage>
}

export function AdminAccessSettingsPage() {
  return <SettingsPage title="Админ хандалт" description="Админ хэрэглэгч нэмэх, эрхийг цуцлах болон өөрийн нууц үгийг шинэчилнэ.">
    <section className="settings-embedded admin-access-settings"><div className="settings-embedded-heading"><KeyRound /><div><h3>Админ хэрэглэгч ба нууц үг</h3><p>Эдгээр тохиргоо нь автоматжуулалт болон интеграцийн тохиргооноос тусдаа байна.</p></div></div><div className="flex flex-col gap-4 max-w-[700px]"><AdminAccessPanel /></div></section>
  </SettingsPage>
}

export function OyunsAssistantSettingsPage() {
  return <SettingsPage title="OYUNS agent" description="Агентын ашиглах компаний өгөгдлийн санг хянах болон хөгжүүлэх">
    <section className="settings-embedded"><div className="settings-embedded-heading"><BookOpen /><div><h3>Компаний өгөгдлийн сан</h3><p>OYUNS-ийн баталгаатай эх сурвалжууд.</p></div></div><KnowledgePage /></section>
    <section className="settings-embedded"><div className="settings-embedded-heading"><Code2 /><div><h3>OYUNS сургалт</h3><p>Тодорхойгүй хүсэлтийг review хийж, ойлголт нэмнэ.</p></div></div><DeveloperPage /></section>
  </SettingsPage>
}
