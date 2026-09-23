import { useEffect, useState, type ReactNode } from 'react'
import { ArrowLeft, Bot, BookOpen, Boxes, Building2, CalendarClock, CalendarDays, Check, ChevronDown, ClipboardList, Code2, KeyRound, Landmark, LocateFixed, MapPin, MonitorUp, ScanLine, Settings2, ShieldAlert, ShieldCheck, Trash2, UserPlus, UserRoundCog, Users2, Wifi, X } from 'lucide-react'
import { Link, NavLink } from 'react-router-dom'
import toast from 'react-hot-toast'
import { type ERPModule, useBrandingSettings, useCreateManagedAccount, useCreateWorktimeQrKiosk, useDeleteManagedAccount, useDeleteWorktimeQrKiosk, useERPMetadata, useGoogleCalendarConnect, useGoogleCalendarDisconnect, useGoogleCalendarStatus, useGoogleCalendarSyncMode, useHolidaySettings, useManagedAccounts, usePermissionSettings, useRenewWorktimeQrPairingCode, useRevokeWorktimeQrKiosk, useSetHolidayCountry, useUpdateBrandingSettings, useUpdateERPModules, useUpdateManagedAccount, useUpdatePermissionSettings, useUpdateWorktimeGeofenceSettings, useUploadBrandingLogo, useWorktimeGeofenceSettings, useWorktimeQrKiosks } from '../api/enterprise'
import { EMPTY_ROLES, useAuthStore } from '../store/auth'
import { EmployeesPage } from './EmployeesPage'
import { QuestionsPage } from './QuestionsPage'
import { SchedulePage } from './SchedulePage'
import { AdminAccessPanel, ManagerSettingsPage } from './ManagerSettingsPage'
import { KnowledgePage } from './KnowledgePage'
import { OnboardingPage } from './OnboardingPage'
import { DeveloperPage } from './DeveloperPage'
import { ERPBuilderPanels } from '../components/ERPBuilderPanels'
import { WorktimeMapPicker } from '../components/WorktimeMapPicker'

type SettingsTab = { to: string; label: string; roles?: string[] }
type SettingsCategory = { id: string; to: string; label: string; icon: typeof Settings2; roles: string[]; tabs: SettingsTab[] }

const SETTINGS_CATEGORIES: SettingsCategory[] = [
  {
    id: 'organization', to: '/administration/organization/profile', label: 'Байгууллага', icon: Building2, roles: ['admin', 'manager'],
    tabs: [
      { to: '/administration/organization/profile', label: 'Профайл ба брэндинг', roles: ['admin', 'manager'] },
      { to: '/administration/organization/modules', label: 'Модуль ба боломжууд', roles: ['admin'] },
    ],
  },
  {
    id: 'people', to: '/administration/people/users', label: 'Хэрэглэгч ба эрх', icon: Users2, roles: ['admin', 'manager'],
    tabs: [
      { to: '/administration/people/users', label: 'Ажилтан ба хэрэглэгч', roles: ['admin'] },
      { to: '/administration/people/permissions', label: 'Үүрэг ба эрх', roles: ['admin', 'manager'] },
    ],
  },
  {
    id: 'workflows', to: '/administration/workflows/worktime', label: 'Ажлын цаг ба процесс', icon: UserRoundCog, roles: ['admin', 'manager', 'team_lead'],
    tabs: [{ to: '/administration/workflows/worktime', label: 'Ажлын цаг ба check-in' }],
  },
  {
    id: 'integrations', to: '/administration/integrations/overview', label: 'Автоматжуулалт ба интеграци', icon: CalendarClock, roles: ['admin', 'manager', 'team_lead'],
    tabs: [{ to: '/administration/integrations/overview', label: 'Интеграци ба төхөөрөмж' }],
  },
  {
    id: 'ai', to: '/administration/ai/knowledge', label: 'OYUNS AI ба сургалт', icon: Bot, roles: ['admin', 'manager', 'team_lead', 'hr', 'member', 'contractor', 'client_auditor', 'legal_counsel'],
    tabs: [{ to: '/administration/ai/knowledge', label: 'Сургалт ба агент' }],
  },
  {
    id: 'security', to: '/administration/security/authentication', label: 'Систем ба аюулгүй байдал', icon: KeyRound, roles: ['admin'],
    tabs: [{ to: '/administration/security/authentication', label: 'Нэвтрэлт ба админ' }],
  },
]

const SETTINGS = SETTINGS_CATEGORIES

function firstAllowedSettingsPath(category: SettingsCategory, roles: string[]) {
  return category.tabs.find((tab) => !tab.roles || tab.roles.some((role) => roles.includes(role)))?.to || category.to
}

function SettingsSection({ title, icon: Icon, children, className = '', defaultOpen = false }: { title: string; icon: typeof Settings2; children: ReactNode; className?: string; defaultOpen?: boolean }) {
  return <details className={`settings-section ${className}`} open={defaultOpen} data-slot="settings-section">
    <summary className="settings-section-summary" data-slot="settings-section-summary">
      <Icon className="settings-section-icon" size={18} />
      <span className="settings-section-title">{title}</span>
      <ChevronDown className="settings-section-chevron" size={18} aria-hidden="true" />
    </summary>
    <div className="settings-section-body">{children}</div>
  </details>
}

const TASK_ASSIGNMENT_ROLES = [
  ['member', 'Member'], ['manager', 'Supervisor'], ['team_lead', 'Team lead'], ['hr', 'HR'],
  ['contractor', 'Contractor'], ['client_auditor', 'Client auditor'], ['admin', 'Admin'],
] as const
const ACCOUNT_ROLES = [
  ...TASK_ASSIGNMENT_ROLES.slice(0, 6), ['legal_counsel', 'Хуульч'], ['admin', 'Admin'],
] as const

function SettingsPage({ title, categoryId, activeTab, children }: { title: string; categoryId: string; activeTab: string; children: ReactNode }) {
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const settings = SETTINGS.filter((item) => item.roles.some((role) => roles.includes(role)))
  const category = SETTINGS_CATEGORIES.find((item) => item.id === categoryId) || SETTINGS_CATEGORIES[0]
  const tabs = category.tabs.filter((item) => !item.roles || item.roles.some((role) => roles.includes(role)))
  return <div className="settings-page">
    <div className="settings-layout">
      <aside className="settings-sidebar" aria-label="Админ тохиргооны ангилал">
        <Link to="/administration" className="settings-back"><ArrowLeft size={15} /><span>Бүх тохиргоо</span></Link>
        <nav className="settings-category-nav">{settings.map((item) => <NavLink key={item.id} to={firstAllowedSettingsPath(item, roles)} className={item.id === category.id ? 'active' : undefined}><item.icon size={17} /><span><strong>{item.label}</strong></span></NavLink>)}</nav>
      </aside>
      <main className="settings-main">
        <div className="view-toolbar settings-page-heading"><div><h2>{title}</h2></div><Settings2 /></div>
        <nav className="settings-tab-nav" aria-label={`${category.label} tabs`}>{tabs.map((tab) => <NavLink key={tab.to} to={tab.to} className={tab.to === activeTab ? 'active' : undefined}><span>{tab.label}</span></NavLink>)}</nav>
        <div className="settings-content">{children}</div>
      </main>
    </div>
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
  return <SettingsSection title="Лого ба theme" icon={Settings2} className="branding-settings panel"><div className="branding-grid">{(['light', 'dark'] as const).map((theme) => {
    const logo = theme === 'light' ? branding.data?.light_logo : branding.data?.dark_logo
    return <article className={`branding-card ${theme}`} key={theme}><div className="branding-preview"><img src={logo || '/favicon.png'} alt={`${theme} logo preview`} /></div><div className="branding-card-body"><strong>{theme === 'light' ? 'Light mode' : 'Dark mode'}</strong><select aria-label={`${theme} logo сонгох`} value={sourceFor(theme)} onChange={(event) => select(theme, event.target.value)} disabled={branding.isLoading || update.isPending}><option value="default">Автомат legacy</option>{branding.data?.legacy_options.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}{sourceFor(theme) === 'uploaded' && <option value="uploaded">Uploaded logo</option>}</select><label className="secondary-action compact branding-upload"><span>Шинэ зураг сонгох</span><input type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => { const file = event.target.files?.[0]; if (file) upload.mutate({ theme, file }); event.currentTarget.value = '' }} disabled={upload.isPending} /></label></div></article>
  })}</div></SettingsSection>
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

  if (metadata.isLoading) return <SettingsSection title="ERP модулиуд" icon={Boxes} className="account-admin panel"><p>ERP тохиргоог уншиж байна…</p></SettingsSection>
  if (metadata.isError || !metadata.data) return <SettingsSection title="ERP үйлчилгээ холбогдсонгүй" icon={Landmark} className="account-admin panel"><p>ERP тохиргоог ачаалж чадсангүй.</p></SettingsSection>

  return <SettingsSection title="ERP модулиуд" icon={Boxes} className="account-admin panel erp-admin-panel">
    <div className="erp-module-grid" aria-label="ERP module visibility">
      {modules.map((module) => {
        const enabled = metadata.data.modules[module]
        const label = metadata.data.module_labels[module] || module
        return <article key={module} className={`panel erp-module-card ${enabled ? 'enabled' : ''}`}><Landmark size={21} /><div><strong>{label}</strong><small>{enabled ? 'Workspace-д харагдана' : 'Workspace-ээс нуусан'}</small></div><button className="erp-toggle" onClick={() => toggleModule(module)} disabled={updateModules.isPending} aria-label={`${label} ${enabled ? 'disable' : 'enable'}`}><span /></button></article>
      })}
    </div>
    <p className="erp-settings-notice"><ShieldCheck size={15} /> API, posting, audit болон integrations нь capability-ээр хамгаалагдсан хэвээр.</p>
    <Link className="secondary-action compact erp-admin-open" to="/erp">ERP workspace нээх</Link>
  </SettingsSection>
}

export function AdministrationHubPage() {
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const settings = SETTINGS.filter((item) => item.roles.some((role) => roles.includes(role)))
  return <div className="settings-overview"><div className="settings-category-grid">{settings.map((item) => <Link to={firstAllowedSettingsPath(item, roles)} key={item.id}><item.icon /><div><strong>{item.label}</strong></div></Link>)}</div></div>
}

export function WorkspaceIdentitySettingsPage() {
  return <SettingsPage categoryId="organization" activeTab="/administration/organization/profile" title="Байгууллагын профайл"><BrandingSettingsPanel /></SettingsPage>
}

export function ERPSettingsPage() {
  return <SettingsPage categoryId="organization" activeTab="/administration/organization/modules" title="Модуль ба боломжууд"><ERPModuleSettingsPanel /></SettingsPage>
}

function TaskAssignmentPermissionsPanel() {
  const permissions = usePermissionSettings()
  const updatePermissions = useUpdatePermissionSettings()
  return <SettingsSection title="Даалгавар оноох эрх" icon={UserRoundCog} className="account-admin panel"><fieldset className="role-editor"><legend>Даалгавар оноож болох role</legend>{TASK_ASSIGNMENT_ROLES.map(([value, label]) => <label key={value}><input type="checkbox" checked={permissions.data?.task_assignment_roles.includes(value) ?? true} onChange={() => { const current = permissions.data?.task_assignment_roles ?? TASK_ASSIGNMENT_ROLES.map(([name]) => name); updatePermissions.mutate(current.includes(value) ? current.filter((item) => item !== value) : [...current, value]) }} disabled={updatePermissions.isPending} /><span>{label}</span></label>)}</fieldset></SettingsSection>
}

export function PermissionsSettingsPage() {
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  return <SettingsPage categoryId="people" activeTab="/administration/people/permissions" title="Үүрэг ба эрх"><TaskAssignmentPermissionsPanel />{roles.includes('admin') && <SettingsSection title="Системийн role" icon={ShieldCheck} className="settings-embedded"><ERPBuilderPanels /></SettingsSection>}</SettingsPage>
}

export function CollaborationSettingsPage() {
  return <SettingsPage categoryId="workflows" activeTab="/administration/workflows/worktime" title="Ажлын цаг ба процесс">
    <SettingsSection title="Check-in асуултууд" icon={ClipboardList} className="settings-embedded"><QuestionsPage /></SettingsSection>
    <SettingsSection title="Ажилтны хуваарь" icon={CalendarDays} className="settings-embedded"><SchedulePage /></SettingsSection>
    <WorktimeHolidayPanel />
    <WorktimeQrKioskPanel />
    <WorktimeGeofencePanel />
  </SettingsPage>
}

function WorktimeHolidayPanel() {
  const holidaySettings = useHolidaySettings()
  const setCountry = useSetHolidayCountry()
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const canEdit = roles.includes('admin')

  return <SettingsSection title="Нийтийн амралтын өдөр" icon={CalendarDays} className="settings-embedded worktime-holiday-admin">
    {holidaySettings.isError ? <div className="worktime-alert error" role="alert"><ShieldCheck size={17} />Амралтын өдрийн тохиргоог ачаалж чадсангүй.</div> : <div className="worktime-holiday-setting"><div><strong>Амралт: {holidaySettings.data?.country || 'MN'}</strong><p>Календарьт харуулах нийтийн амралтын өдрийн улсыг сонгоно.</p></div><select aria-label="Амралтын өдрийн улс" value={holidaySettings.data?.country || 'MN'} onChange={(event) => setCountry.mutate(event.target.value)} disabled={!canEdit || holidaySettings.isLoading || setCountry.isPending}>{holidaySettings.data?.countries.map((country) => <option key={country.countryCode} value={country.countryCode}>{country.name}</option>)}</select></div>}
  </SettingsSection>
}

function WorktimeQrKioskPanel() {
  const kiosks = useWorktimeQrKiosks()
  const create = useCreateWorktimeQrKiosk()
  const renew = useRenewWorktimeQrPairingCode()
  const revoke = useRevokeWorktimeQrKiosk()
  const remove = useDeleteWorktimeQrKiosk()
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
  return <SettingsSection title="Worktime QR дэлгэц" icon={MonitorUp} className="settings-embedded worktime-kiosk-admin"><WorktimeQrSetupGuide /><form className="kiosk-create-form" onSubmit={submit}><label>Дэлгэцийн нэр<input value={label} onChange={(event) => setLabel(event.target.value)} required /></label><label>Location ID<input value={locationId} onChange={(event) => setLocationId(event.target.value)} pattern="[A-Za-z0-9_-]+" required /></label><label>Харагдах нэр<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} required /></label><button className="primary-action" disabled={create.isPending}>Pairing код үүсгэх</button></form>{pairingCode && <div className="kiosk-pairing-code" role="status"><strong>{pairingCode}</strong><span>Энэ 8 тэмдэгттэй кодыг дэлгэцийн <a href="/worktimeqr" target="_blank" rel="noreferrer">/worktimeqr</a> хуудсанд 10 минутын дотор оруулна уу.</span><button className="secondary-action compact" onClick={() => navigator.clipboard?.writeText(pairingCode)}>Хуулах</button></div>}{kiosks.isError && <div className="worktime-alert error" role="alert"><ShieldCheck size={17} />QR дэлгэцийн өгөгдлийн хүснэгт бэлэн биш байна. Backend migration-ийг ажиллуулаад дахин оролдоно уу.</div>}<div className="kiosk-list">{kiosks.isLoading ? <p>Дэлгэцүүдийг ачаалж байна…</p> : (kiosks.data ?? []).map((kiosk) => <article key={kiosk.id} className={`kiosk-row ${kiosk.status}`}><div><strong>{kiosk.display_name}</strong><span>{kiosk.label} · {kiosk.location_id} · {kiosk.status === 'active' ? 'Идэвхтэй' : 'Цуцлагдсан'}</span></div><div className="kiosk-row-actions">{kiosk.status === 'active' ? <><button className="secondary-action compact" onClick={() => renewPairing(kiosk.id)} disabled={renew.isPending}>Дахин pair хийх</button><button className="danger-action compact" onClick={() => revoke.mutate(kiosk.id)} disabled={revoke.isPending}>Цуцлах</button></> : <button className="danger-action compact kiosk-delete-action" onClick={() => { if (window.confirm(`${kiosk.display_name} дэлгэцийг бүр мөсөн устгах уу?`)) remove.mutate(kiosk.id, { onSuccess: () => toast.success('QR дэлгэц устгагдлаа'), onError: () => toast.error('QR дэлгэцийг устгаж чадсангүй') }) }} disabled={remove.isPending} aria-label={`${kiosk.display_name} дэлгэцийг устгах`}><Trash2 size={14} />Устгах</button>}</div></article>)}</div></SettingsSection>
}

const WORKTIME_QR_SETUP_STEPS = [
  { icon: Settings2, title: 'Дэлгэцээ бүртгэх', text: 'Нэр, Location ID, харагдах нэрээ оруулаад “Pairing код үүсгэх” дээр дарна.' },
  { icon: ClipboardList, title: 'Нэг удаагийн код авах', text: 'Үүссэн 8 тэмдэгттэй код 10 минут хүчинтэй. Хугацаа дуусвал шинэ код үүсгээрэй.' },
  { icon: MonitorUp, title: 'Дэлгэц дээр нээх', text: 'Tablet, kiosk эсвэл TV-ийн browser-оор энэ системийн /worktimeqr хуудсыг HTTPS-ээр нээгээд кодыг оруулна.' },
  { icon: Wifi, title: 'Холболтоо баталгаажуулах', text: '“Дэлгэц холбох” дарсны дараа код оруулах хэсэг алга болж, дэлгэц дээр Live төлөв болон шинэчлэгддэг QR гарна.' },
  { icon: ScanLine, title: 'Туршилтын уншилт хийх', text: 'Ажилтны OYUNS Worktime scanner-аар QR-ийг уншуулж, check-in/check-out бүртгэл зөв үүссэнийг шалгана. Дэлгэцийн QR 30 секунд тутам солигдоно.' },
  { icon: MapPin, title: 'Бусад байршлыг нэмэх', text: 'Дэлгэц бүрт тусдаа бичлэг, ялгаатай нэр өгч, тухайн байршлын Location ID-г сонгоод төхөөрөмж бүрийг тус тусад нь pair хийнэ.' },
]

function WorktimeQrSetupGuide() {
  return <section className="worktime-qr-guide" data-slot="worktime-qr-guide" aria-labelledby="worktime-qr-guide-title">
    <header className="worktime-qr-guide-header" data-slot="worktime-qr-guide-header"><div><span className="worktime-qr-guide-kicker">ТОХИРУУЛАХ ЗААВАР · 6 АЛХАМ</span><h3 id="worktime-qr-guide-title">QR дэлгэцээ холбоорой</h3><p>Дэлгэц pairing хийхдээ кодыг төхөөрөмж дээр нэг удаа оруулна.</p></div><div className="worktime-qr-guide-progress" aria-label="Нийт 6 алхам"><span>6</span><small>алхам</small></div></header>
    <ol className="worktime-qr-guide-steps" data-slot="worktime-qr-guide-steps" aria-label="Тохируулах алхмууд">{WORKTIME_QR_SETUP_STEPS.map(({ icon: Icon, title, text }, index) => <li key={title} data-slot="worktime-qr-guide-step"><span className="worktime-qr-step-icon"><Icon size={19} aria-hidden="true" /></span><span className="worktime-qr-step-number">{String(index + 1).padStart(2, '0')}</span><div><strong>{title}</strong><p>{text}</p></div></li>)}</ol>
    <aside className="worktime-qr-troubleshooting" data-slot="worktime-qr-troubleshooting"><div className="worktime-qr-trouble-title"><ShieldAlert size={17} /><strong>Түгээмэл асуудал</strong></div><div><p><b>Кодын хугацаа дууссан:</b> Дэлгэцийн жагсаалтаас “Дахин pair хийх” дарж шинэ код авч оруулна.</p><p><b>Дэлгэц Offline/Disconnected:</b> Интернэтээ шалгаад /worktimeqr хуудсыг дахин ачаална. Холболт сэргээгүй бол pairing кодоо шинэчилж дахин холбоно.</p><p><b>Олон дэлгэц холбох:</b> Байршил бүрт тусдаа дэлгэц үүсгээд, нэг кодыг зөвхөн нэг төхөөрөмжид ашиглана.</p></div></aside>
    <p className="worktime-qr-guide-note">Тусгай pairing линк үүсдэггүй: төхөөрөмж дээр /worktimeqr хуудсыг нээж, энд гарсан кодыг оруулна.</p>
  </section>
}

function WorktimeGeofencePanel() {
  const settings = useWorktimeGeofenceSettings()
  const update = useUpdateWorktimeGeofenceSettings()
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const canEdit = roles.includes('admin')
  const [latitude, setLatitude] = useState('')
  const [longitude, setLongitude] = useState('')
  const [radius, setRadius] = useState('150')

  useEffect(() => {
    if (!settings.data) return
    setLatitude(settings.data.latitude == null ? '' : String(settings.data.latitude))
    setLongitude(settings.data.longitude == null ? '' : String(settings.data.longitude))
    setRadius(String(settings.data.radius_meters || 150))
  }, [settings.data])

  const useCurrentLocation = () => {
    if (!canEdit || !navigator.geolocation) {
      toast.error('Энэ төхөөрөмж байршил тодорхойлохыг дэмжихгүй байна.')
      return
    }
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setLatitude(position.coords.latitude.toFixed(6))
        setLongitude(position.coords.longitude.toFixed(6))
        toast.success('Одоогийн байршлыг бөглөсөн. Хадгалахаа бүү мартаарай.')
      },
      () => toast.error('Оффисын байршлыг тодорхойлж чадсангүй. Байршлын зөвшөөрлөө шалгана уу.'),
      { enableHighAccuracy: true, maximumAge: 0, timeout: 10_000 },
    )
  }

  const save = (event: React.FormEvent) => {
    event.preventDefault()
    const nextLatitude = Number(latitude)
    const nextLongitude = Number(longitude)
    const nextRadius = Number(radius)
    if (!Number.isFinite(nextLatitude) || !Number.isFinite(nextLongitude) || nextLatitude < -90 || nextLatitude > 90 || nextLongitude < -180 || nextLongitude > 180) {
      toast.error('Өргөрөг -90…90, уртраг -180…180 хооронд байх ёстой.')
      return
    }
    if (!Number.isInteger(nextRadius) || nextRadius < 25 || nextRadius > 5000) {
      toast.error('Радиус 25–5000м хооронд бүхэл тоо байх ёстой.')
      return
    }
    update.mutate({ latitude: nextLatitude, longitude: nextLongitude, radius_meters: nextRadius })
  }

  const mapLatitude = latitude.trim() ? Number(latitude) : null
  const mapLongitude = longitude.trim() ? Number(longitude) : null
  return <SettingsSection title="Ажлын цаг бүртгэх байршил" icon={MapPin} className="settings-embedded worktime-geofence-admin">{settings.isError ? <div className="worktime-alert error" role="alert"><ShieldCheck size={17} />Оффисын байршлын тохиргоог ачаалж чадсангүй.</div> : <form className="worktime-geofence-form" onSubmit={save}><WorktimeMapPicker latitude={Number.isFinite(mapLatitude) ? mapLatitude : null} longitude={Number.isFinite(mapLongitude) ? mapLongitude : null} radiusMeters={Number(radius) || 150} disabled={!canEdit || update.isPending} onChange={({ latitude: nextLatitude, longitude: nextLongitude }) => { setLatitude(nextLatitude.toFixed(6)); setLongitude(nextLongitude.toFixed(6)) }} /><div className="form-row"><label>Өргөрөг (latitude)<input type="number" step="any" min="-90" max="90" value={latitude} onChange={(event) => setLatitude(event.target.value)} disabled={!canEdit || update.isPending} placeholder="47.9184" required /></label><label>Уртраг (longitude)<input type="number" step="any" min="-180" max="180" value={longitude} onChange={(event) => setLongitude(event.target.value)} disabled={!canEdit || update.isPending} placeholder="106.9177" required /></label><label>Радиус (метр)<input type="number" step="1" min="25" max="5000" value={radius} onChange={(event) => setRadius(event.target.value)} disabled={!canEdit || update.isPending} required /></label></div><div className="worktime-geofence-actions"><button type="button" className="secondary-action" onClick={useCurrentLocation} disabled={!canEdit || update.isPending}><LocateFixed size={15} />Одоогийн байршил ашиглах</button><button type="submit" className="primary-action" disabled={!canEdit || update.isPending}>{update.isPending ? 'Хадгалж байна…' : 'Байршил хадгалах'}</button></div><p className="field-help">{settings.data?.configured ? `Идэвхтэй · ${settings.data.radius_meters}м радиус` : 'Байршил тохируулаагүй байна.'}{!canEdit && ' · Зөвхөн админ өөрчилнө.'}</p></form>}</SettingsSection>
}

function UnlinkedAccountsPanel() {
  const accounts = useManagedAccounts()
  const createAccount = useCreateManagedAccount()
  const updateAccount = useUpdateManagedAccount()
  const deleteAccount = useDeleteManagedAccount()
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
  const remove = (account: { id: number; email: string }) => {
    if (window.confirm(`${account.email} хэрэглэгчийг устгах уу?`)) deleteAccount.mutate(account.id)
  }
  return <SettingsSection title="Ажилтантай холбогдоогүй хэрэглэгчид" icon={Users2} className="account-admin panel"><form className="account-create-form" onSubmit={create}><label>Username<input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required /></label><label>Password<input value={password} onChange={(event) => setPassword(event.target.value)} type="password" minLength={10} autoComplete="new-password" required /></label><label>Role<select value={role} onChange={(event) => setRole(event.target.value)}>{ACCOUNT_ROLES.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label><button className="primary-action compact" disabled={createAccount.isPending}><UserPlus size={15} />Нэмэх</button></form><div className="account-list" aria-live="polite">{unlinkedAccounts.map((account) => <article key={account.id}><div className="account-identity"><strong>{account.email}</strong><span>{account.status} · ажилтантай холбогдоогүй</span></div><fieldset className="role-editor"><legend>Access roles</legend>{ACCOUNT_ROLES.map(([value, label]) => <label key={value}><input type="checkbox" checked={account.roles.includes(value)} onChange={() => toggleRole(account, value)} disabled={updateAccount.isPending} /><span>{label}</span></label>)}</fieldset><div className="settings-row-actions"><button type="button" className="settings-icon-action" onClick={() => changePassword(account)} aria-label={`${account.email} нууц үг солих`} title="Нууц үг солих"><KeyRound size={16} /></button><button type="button" className="settings-icon-action" onClick={() => updateAccount.mutate({ id: account.id, status: account.status === 'disabled' ? 'active' : 'disabled' })} aria-label={`${account.email} ${account.status === 'disabled' ? 'идэвхжүүлэх' : 'идэвхгүй болгох'}`} title={account.status === 'disabled' ? 'Идэвхжүүлэх' : 'Идэвхгүй болгох'}><span className="sr-only">{account.status === 'disabled' ? 'Идэвхжүүлэх' : 'Идэвхгүй болгох'}</span>{account.status === 'disabled' ? <Check size={16} /> : <X size={16} />}</button><button type="button" className="settings-icon-action danger" onClick={() => remove(account)} aria-label={`${account.email} устгах`} title="Устгах"><Trash2 size={16} /></button></div></article>)}</div></SettingsSection>
}

export function AccessControlSettingsPage() {
  return <SettingsPage categoryId="people" activeTab="/administration/people/users" title="Ажилтан ба хэрэглэгч"><SettingsSection title="Ажилтан ба эрхүүд" icon={Users2} className="settings-embedded access-settings"><EmployeesPage /></SettingsSection><UnlinkedAccountsPanel /><SettingsSection title="Онбординг" icon={UserRoundCog} className="settings-embedded"><OnboardingPage /></SettingsSection></SettingsPage>
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
  return <SettingsPage categoryId="integrations" activeTab="/administration/integrations/overview" title="Интеграци ба төхөөрөмж">
    <SettingsSection title="Google Calendar" icon={CalendarClock} className="integration-grid settings-integrations"><article className="integration-panel"><div><strong>Google Calendar</strong><p>{calendarStatus.data?.status === 'active' ? `Холбогдсон · webhook ${calendarStatus.data.watch_active ? 'идэвхтэй' : 'шинэчлэгдэж байна'}${calendarStatus.data.last_error ? ` · ${calendarStatus.data.last_error}` : ''}` : 'Холбогдоогүй'}</p>{calendarStatus.data?.status === 'active' && <select aria-label="Calendar sync mode" value={calendarStatus.data.sync_mode} onChange={(event) => syncMode.mutate(event.target.value as 'outbound' | 'bidirectional')}><option value="outbound">Зөвхөн OYUNS → Google</option><option value="bidirectional">Хоёр чиглэлтэй хугацааны sync</option></select>}</div>{calendarStatus.data?.status === 'active' ? <button className="secondary-action" onClick={() => disconnect.mutate()} disabled={disconnect.isPending}>Салгах</button> : <button className="secondary-action" onClick={connectCalendar} disabled={calendar.isPending}>Холбох</button>}</article></SettingsSection>
    <SettingsSection title="Мэдэгдэл ба Telegram" icon={UserRoundCog} className="settings-embedded"><ManagerSettingsPage /></SettingsSection>
  </SettingsPage>
}

export function AdminAccessSettingsPage() {
  return <SettingsPage categoryId="security" activeTab="/administration/security/authentication" title="Нэвтрэлт ба админ">
    <SettingsSection title="Админ хэрэглэгч ба нууц үг" icon={KeyRound} className="settings-embedded admin-access-settings"><div className="settings-form-stack"><AdminAccessPanel /></div></SettingsSection>
  </SettingsPage>
}

export function OyunsAssistantSettingsPage() {
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const canManageAgent = roles.includes('admin')
  return <SettingsPage categoryId="ai" activeTab="/administration/ai/knowledge" title="OYUNS AI ба сургалт">
    <SettingsSection title="Компанийн өгөгдлийн сан" icon={BookOpen} className="settings-embedded"><KnowledgePage /></SettingsSection>
    {canManageAgent && <SettingsSection title="OYUNS сургалт" icon={Code2} className="settings-embedded"><DeveloperPage /></SettingsSection>}
  </SettingsPage>
}
