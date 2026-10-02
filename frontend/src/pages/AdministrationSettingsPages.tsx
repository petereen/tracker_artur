import { createElement, useEffect, useState, type ReactNode } from 'react'
import { ArrowLeft, Bell, Bot, BookOpen, Building2, Globe, Send, CalendarClock, CalendarDays, Check, ChevronDown, ClipboardList, Code2, FileCheck2, KeyRound, LocateFixed, MapPin, MonitorUp, ScanLine, Settings2, ShieldAlert, ShieldCheck, Trash2, UserPlus, UserRoundCog, Users2, Wifi, X } from 'lucide-react'
import { Link, NavLink } from 'react-router-dom'
import toast from 'react-hot-toast'
import { useBrandingSettings, useCreateManagedAccount, useCreateWorktimeQrKiosk, useDeleteManagedAccount, useDeleteWorktimeQrKiosk, useGoogleCalendarConnect, useGoogleCalendarDisconnect, useGoogleCalendarStatus, useGoogleCalendarSyncMode, useHolidaySettings, useManagedAccounts, usePermissionSettings, useRenewWorktimeQrPairingCode, useRevokeWorktimeQrKiosk, useSetHolidayCountry, useUpdateBrandingSettings, useUpdateManagedAccount, useUpdatePermissionSettings, useUpdateWorktimeGeofenceSettings, useUploadBrandingLogo, useWorktimeGeofenceSettings, useWorktimeQrKiosks } from '../api/enterprise'
import { EMPTY_ROLES, useAuthStore } from '../store/auth'
import { EmployeesPage } from './EmployeesPage'
import { QuestionsPage } from './QuestionsPage'
import { SchedulePage } from './SchedulePage'
import { AdminAccessPanel, ManagerSettingsPage } from './ManagerSettingsPage'
import { KnowledgePage } from './KnowledgePage'
import { AiAccessSettings } from '../components/AiAccessSettings'
import { AiAgentSettings } from '../components/AiAgentSettings'
import { OnboardingPage } from './OnboardingPage'
import { DeveloperPage } from './DeveloperPage'
import { ERPBuilderPanels } from '../components/ERPBuilderPanels'
import { RoleBuilder } from '../components/RoleBuilder'
import { ERPModuleSettings } from '../components/ERPModuleSettings'
import { WorktimeMapPicker } from '../components/WorktimeMapPicker'
import { WorktimeMethodsSettings } from '../components/WorktimeMethodsSettings'
import { WorktimeAutoSettings } from '../components/WorktimeAutoSettings'
import { TwoFactorSettings } from '../components/TwoFactorSettings'
import { ReportPolicySettings } from '../components/ReportPolicySettings'
import { SeatMeter, TenantLicenseSettings } from '../components/TenantLicenseSettings'
import { TenantBrandingSettings } from '../components/TenantBrandingSettings'
import { TenantDomainSettings } from '../components/TenantDomainSettings'
import { TenantTelegramBotSettings } from '../components/TenantTelegramBotSettings'
import { SeatLimitNotice } from '../components/SeatLimitNotice'
import { NotificationSettings } from '../components/NotificationSettings'
import { Banner } from '@astryxdesign/core/Banner'
import { tenancyErrorMessage, useTenantSeats } from '../api/tenancy'
import { useTranslation } from 'react-i18next'

type SettingsTab = { to: string; label: string; roles?: string[]; icon?: typeof Settings2 }
type SettingsCategory = { id: string; to: string; label: string; icon: typeof Settings2; roles: string[]; tabs: SettingsTab[] }

const SETTINGS_CATEGORIES: SettingsCategory[] = [
  {
    id: 'organization', to: '/administration/organization/profile', label: 'st.cat.organization', icon: Building2, roles: ['admin', 'manager'],
    tabs: [
      { to: '/administration/organization/profile', label: 'st.tab.profile', icon: Building2, roles: ['admin', 'manager'] },
      { to: '/administration/organization/modules', label: 'st.tab.modules', icon: Settings2, roles: ['admin'] },
      { to: '/administration/organization/domains', label: 'st.tab.domains', icon: Globe, roles: ['admin'] },
    ],
  },
  {
    id: 'people', to: '/administration/people/users', label: 'st.cat.people', icon: Users2, roles: ['admin', 'manager'],
    tabs: [
      { to: '/administration/people/users', label: 'st.tab.users', icon: Users2, roles: ['admin'] },
      { to: '/administration/people/permissions', label: 'st.tab.permissions', icon: ShieldCheck, roles: ['admin', 'manager'] },
    ],
  },
  {
    id: 'workflows', to: '/administration/workflows/worktime', label: 'st.cat.workflows', icon: UserRoundCog, roles: ['admin', 'manager', 'team_lead'],
    tabs: [
      { to: '/administration/workflows/worktime', label: 'st.tab.worktime', icon: CalendarClock },
      { to: '/administration/workflows/reports', label: 'st.tab.reports', icon: ClipboardList },
    ],
  },
  {
    id: 'integrations', to: '/administration/integrations/overview', label: 'st.cat.integrations', icon: CalendarClock, roles: ['admin', 'manager', 'team_lead'],
    tabs: [{ to: '/administration/integrations/overview', label: 'st.tab.integrations', icon: Send }],
  },
  {
    id: 'ai', to: '/administration/ai/knowledge', label: 'st.cat.ai', icon: Bot, roles: ['admin', 'manager', 'team_lead', 'hr', 'member', 'contractor', 'client_auditor', 'legal_counsel'],
    tabs: [{ to: '/administration/ai/knowledge', label: 'st.tab.knowledge', icon: BookOpen }],
  },
  {
    id: 'security', to: '/administration/security/authentication', label: 'st.cat.security', icon: KeyRound, roles: ['admin'],
    tabs: [
      { to: '/administration/security/authentication', label: 'st.tab.authentication', icon: KeyRound },
      { to: '/administration/security/license', label: 'st.tab.license', icon: FileCheck2 },
    ],
  },
]

const SETTINGS = SETTINGS_CATEGORIES

function firstAllowedSettingsPath(category: SettingsCategory, roles: string[]) {
  return category.tabs.find((tab) => !tab.roles || tab.roles.some((role) => roles.includes(role)))?.to || category.to
}

/** Every admin setting is a collapsed section until the admin opens it. */
function SettingsSection({ title, icon: Icon, children, className = '' }: { title: string; icon: typeof Settings2; children: ReactNode; className?: string }) {
  return <details className={`settings-section ${className}`} data-slot="settings-section">
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
  ...TASK_ASSIGNMENT_ROLES.slice(0, 6), ['legal_counsel', 'st.role.legal'], ['admin', 'Admin'],
] as const

function SettingsPage({ title, categoryId, activeTab, children }: { title: string; categoryId: string; activeTab: string; children: ReactNode }) {
  const { t } = useTranslation()
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const settings = SETTINGS.filter((item) => item.roles.some((role) => roles.includes(role)))
  const category = SETTINGS_CATEGORIES.find((item) => item.id === categoryId) || SETTINGS_CATEGORIES[0]
  const tabs = category.tabs.filter((item) => !item.roles || item.roles.some((role) => roles.includes(role)))
  return <div className="settings-page">
    <div className="settings-layout">
      <aside className="settings-sidebar" aria-label={t('st.adm.categoriesAria')}>
        <Link to="/administration" className="settings-back"><ArrowLeft size={15} /><span>{t('st.adm.allSettings')}</span></Link>
        <nav className="settings-category-nav">{settings.map((item) => <NavLink key={item.id} to={firstAllowedSettingsPath(item, roles)} className={item.id === category.id ? 'active' : undefined}><item.icon size={17} /><span><strong>{t(item.label)}</strong></span></NavLink>)}</nav>
      </aside>
      <main className="settings-main">
        <div className="view-toolbar settings-page-heading"><div><h2>{title}</h2></div><Settings2 /></div>
        <nav className="page-tabs"><div className="page-tabs-list" aria-label={t('st.adm.tabsAria', { name: t(category.label) })}>{tabs.map((tab) => <NavLink key={tab.to} to={tab.to} className={tab.to === activeTab ? 'active' : undefined}>{createElement(tab.icon || category.icon, { size: 15 })}{t(tab.label)}</NavLink>)}</div></nav>
        <div className="settings-content">{children}</div>
      </main>
    </div>
  </div>
}

function BrandingSettingsPanel() {
  const { t } = useTranslation()
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
  return <SettingsSection title={t('st.adm.logoTheme')} icon={Settings2} className="branding-settings panel"><div className="branding-grid">{(['light', 'dark'] as const).map((theme) => {
    const logo = theme === 'light' ? branding.data?.light_logo : branding.data?.dark_logo
    return <article className={`branding-card ${theme}`} key={theme}><div className="branding-preview"><img src={logo || '/favicon.png'} alt={t('st.adm.logoPreview', { theme: theme === 'light' ? t('st.adm.lightMode') : t('st.adm.darkMode') })} /></div><div className="branding-card-body"><strong>{theme === 'light' ? t('st.adm.lightMode') : t('st.adm.darkMode')}</strong><select aria-label={t('st.adm.logoSelect', { theme: theme === 'light' ? t('st.adm.lightMode') : t('st.adm.darkMode') })} value={sourceFor(theme)} onChange={(event) => select(theme, event.target.value)} disabled={branding.isLoading || update.isPending}><option value="default">{t('st.adm.logoPick')}</option>{branding.data?.legacy_options.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}{sourceFor(theme) === 'uploaded' && <option value="uploaded">{t('st.adm.uploadedLogo')}</option>}</select><label className="secondary-action compact branding-upload"><span>{t('st.adm.newImage')}</span><input type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => { const file = event.target.files?.[0]; if (file) upload.mutate({ theme, file }); event.currentTarget.value = '' }} disabled={upload.isPending} /></label></div></article>
  })}</div></SettingsSection>
}

export function AdministrationHubPage() {
  const { t } = useTranslation()
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const settings = SETTINGS.filter((item) => item.roles.some((role) => roles.includes(role)))
  return <div className="settings-overview"><div className="settings-category-grid">{settings.map((item) => <Link to={firstAllowedSettingsPath(item, roles)} key={item.id}><item.icon /><div><strong>{t(item.label)}</strong></div></Link>)}</div></div>
}

export function WorkspaceIdentitySettingsPage() {
  const { t } = useTranslation()
  return <SettingsPage categoryId="organization" activeTab="/administration/organization/profile" title={t('st.adm.orgProfile')}><SettingsSection title={t('st.adm.orgBranding')} icon={Building2} className="settings-embedded"><TenantBrandingSettings /></SettingsSection><BrandingSettingsPanel /></SettingsPage>
}

export function LicenseSettingsPage() {
  const { t } = useTranslation()
  return <SettingsPage categoryId="security" activeTab="/administration/security/license" title={t('st.tab.license')}><SettingsSection title={t('st.adm.licenseSeats')} icon={ShieldCheck} className="settings-embedded"><TenantLicenseSettings /></SettingsSection></SettingsPage>
}

export function DomainSettingsPage() {
  const { t } = useTranslation()
  return <SettingsPage categoryId="organization" activeTab="/administration/organization/domains" title={t('st.tab.domains')}><SettingsSection title={t('st.adm.domainCloudflare')} icon={Globe} className="settings-embedded"><TenantDomainSettings /></SettingsSection></SettingsPage>
}

/** Active users vs the license's seat ceiling, above user management. */
function SeatUsagePanel() {
  const { t } = useTranslation()
  const seats = useTenantSeats()
  if (!seats.data) return null
  const full = seats.data.limit !== null && seats.data.used >= seats.data.limit
  return <SettingsSection title={seats.data.limit === null ? t('st.adm.seatsTitleUnlimited', { used: seats.data.used }) : t('st.adm.seatsTitle', { used: seats.data.used, limit: seats.data.limit })} icon={ShieldCheck} className="settings-embedded">
    <div className="settings-form-stack">
      <SeatMeter seats={seats.data} />
      {full && <Banner status="warning" collapsible={false} title={t('st.adm.seatsFull')}
        description={t('st.adm.seatsFullDesc')}
        endContent={<Link to="/administration/security/license">{t('st.adm.upgrade')}</Link>} />}
    </div>
  </SettingsSection>
}

export function ERPSettingsPage() {
  const { t } = useTranslation()
  return <SettingsPage categoryId="organization" activeTab="/administration/organization/modules" title={t('st.tab.modules')}><SettingsSection title={t('st.adm.modules')} icon={Settings2} className="settings-embedded"><ERPModuleSettings /></SettingsSection></SettingsPage>
}

function TaskAssignmentPermissionsPanel() {
  const { t } = useTranslation()
  const permissions = usePermissionSettings()
  const updatePermissions = useUpdatePermissionSettings()
  return <SettingsSection title={t('st.adm.taskAssign')} icon={UserRoundCog} className="account-admin panel"><fieldset className="role-editor"><legend>{t('st.adm.taskAssignRoles')}</legend>{TASK_ASSIGNMENT_ROLES.map(([value, label]) => <label key={value}><input type="checkbox" checked={permissions.data?.task_assignment_roles.includes(value) ?? true} onChange={() => { const current = permissions.data?.task_assignment_roles ?? TASK_ASSIGNMENT_ROLES.map(([name]) => name); updatePermissions.mutate(current.includes(value) ? current.filter((item) => item !== value) : [...current, value]) }} disabled={updatePermissions.isPending} /><span>{label}</span></label>)}</fieldset></SettingsSection>
}

export function PermissionsSettingsPage() {
  const { t } = useTranslation()
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  return <SettingsPage categoryId="people" activeTab="/administration/people/permissions" title={t('st.tab.permissions')}><TaskAssignmentPermissionsPanel />{roles.includes('admin') && <SettingsSection title={t('st.adm.roleBuilder')} icon={ShieldCheck} className="settings-embedded"><RoleBuilder /></SettingsSection>}{roles.includes('admin') && <SettingsSection title={t('st.adm.erpForms')} icon={ClipboardList} className="settings-embedded"><ERPBuilderPanels /></SettingsSection>}</SettingsPage>
}

export function CollaborationSettingsPage() {
  const { t } = useTranslation()
  return <SettingsPage categoryId="workflows" activeTab="/administration/workflows/worktime" title={t('st.cat.workflows')}>
    <SettingsSection title={t('st.adm.checkinQuestions')} icon={ClipboardList} className="settings-embedded"><QuestionsPage /></SettingsSection>
    <SettingsSection title={t('st.adm.employeeSchedule')} icon={CalendarDays} className="settings-embedded"><SchedulePage /></SettingsSection>
    <WorktimeHolidayPanel />
    <SettingsSection title={t('st.adm.worktimeMethods')} icon={ScanLine} className="settings-embedded"><WorktimeMethodsSettings /></SettingsSection>
    <WorktimeQrKioskPanel />
    <WorktimeGeofencePanel />
    <SettingsSection title={t('wta.adm.section')} icon={MapPin} className="settings-embedded"><WorktimeAutoSettings /></SettingsSection>
  </SettingsPage>
}

export function ReportSettingsPage() {
  const { t } = useTranslation()
  return <SettingsPage categoryId="workflows" activeTab="/administration/workflows/reports" title={t('st.tab.reports')}>
    <SettingsSection title={t('st.adm.reportFrequency')} icon={FileCheck2} className="settings-embedded"><ReportPolicySettings /></SettingsSection>
  </SettingsPage>
}

function WorktimeHolidayPanel() {
  const { t } = useTranslation()
  const holidaySettings = useHolidaySettings()
  const setCountry = useSetHolidayCountry()
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const canEdit = roles.includes('admin')

  return <SettingsSection title={t('st.adm.holidays')} icon={CalendarDays} className="settings-embedded worktime-holiday-admin">
    {holidaySettings.isError ? <div className="worktime-alert error" role="alert"><ShieldCheck size={17} />{t('st.adm.holidaysLoadFailed')}</div> : <div className="worktime-holiday-setting"><div><strong>{t('st.adm.holidayLabel', { country: holidaySettings.data?.country || 'MN' })}</strong><p>{t('st.adm.holidayCountryHint')}</p></div><select aria-label={t('st.adm.holidayCountry')} value={holidaySettings.data?.country || 'MN'} onChange={(event) => setCountry.mutate(event.target.value)} disabled={!canEdit || holidaySettings.isLoading || setCountry.isPending}>{holidaySettings.data?.countries.map((country) => <option key={country.countryCode} value={country.countryCode}>{country.name}</option>)}</select></div>}
  </SettingsSection>
}

function WorktimeQrKioskPanel() {
  const { t } = useTranslation()
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
      toast.error(typeof detail === 'object' ? detail.message || t('st.adm.kioskCreateFailed') : detail || t('st.adm.kioskCreateFailed'))
    }
  }
  const renewPairing = async (id: number) => {
    try {
      setPairingCode((await renew.mutateAsync(id)).pairing_code || null)
    } catch (error: any) {
      const detail = error?.response?.data?.detail
      toast.error(typeof detail === 'object' ? detail.message || t('st.adm.pairingRenewFailed') : detail || t('st.adm.pairingRenewFailed'))
    }
  }
  return <SettingsSection title={t('st.adm.qrScreen')} icon={MonitorUp} className="settings-embedded worktime-kiosk-admin"><WorktimeQrSetupGuide /><form className="kiosk-create-form" onSubmit={submit}><label>{t('st.adm.screenName')}<input value={label} onChange={(event) => setLabel(event.target.value)} required /></label><label>{t('st.adm.locationId')}<input value={locationId} onChange={(event) => setLocationId(event.target.value)} pattern="[A-Za-z0-9_-]+" required /></label><label>{t('st.adm.displayName')}<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} required /></label><button className="primary-action" disabled={create.isPending}>{t('st.adm.createPairing')}</button></form>{pairingCode && <div className="kiosk-pairing-code" role="status"><strong>{pairingCode}</strong><span>{(() => { const [before, after] = t('st.adm.pairingInstruction').split('{link}'); return <>{before}<a href="/worktimeqr" target="_blank" rel="noreferrer">/worktimeqr</a>{after}</> })()}</span><button className="secondary-action compact" onClick={() => navigator.clipboard?.writeText(pairingCode)}>{t('st.adm.copy')}</button></div>}{kiosks.isError && <div className="worktime-alert error" role="alert"><ShieldCheck size={17} />{t('st.adm.kioskTableMissing')}</div>}<div className="kiosk-list">{kiosks.isLoading ? <p>{t('st.adm.screensLoading')}</p> : (kiosks.data ?? []).map((kiosk) => <article key={kiosk.id} className={`kiosk-row ${kiosk.status}`}><div><strong>{kiosk.display_name}</strong><span>{kiosk.label} · {kiosk.location_id} · {kiosk.status === 'active' ? t('st.adm.statusActive') : t('st.adm.statusRevoked')}</span></div><div className="kiosk-row-actions">{kiosk.status === 'active' ? <><button className="secondary-action compact" onClick={() => renewPairing(kiosk.id)} disabled={renew.isPending}>{t('st.adm.repair')}</button><button className="danger-action compact" onClick={() => revoke.mutate(kiosk.id)} disabled={revoke.isPending}>{t('st.adm.revoke')}</button></> : <button className="danger-action compact kiosk-delete-action" onClick={() => { if (window.confirm(t('st.adm.kioskDeleteConfirm', { name: kiosk.display_name }))) remove.mutate(kiosk.id, { onSuccess: () => toast.success(t('st.adm.kioskDeleted')), onError: () => toast.error(t('st.adm.kioskDeleteFailed')) }) }} disabled={remove.isPending} aria-label={t('st.adm.kioskDeleteAria', { name: kiosk.display_name })}><Trash2 size={14} />{t('st.adm.delete')}</button>}</div></article>)}</div></SettingsSection>
}

const WORKTIME_QR_SETUP_STEPS = [
  { icon: Settings2, title: 'st.step.register.title', text: 'st.step.register.text' },
  { icon: ClipboardList, title: 'st.step.code.title', text: 'st.step.code.text' },
  { icon: MonitorUp, title: 'st.step.open.title', text: 'st.step.open.text' },
  { icon: Wifi, title: 'st.step.connect.title', text: 'st.step.connect.text' },
  { icon: ScanLine, title: 'st.step.test.title', text: 'st.step.test.text' },
  { icon: MapPin, title: 'st.step.multi.title', text: 'st.step.multi.text' },
]

function WorktimeQrSetupGuide() {
  const { t } = useTranslation()
  return <section className="worktime-qr-guide" data-slot="worktime-qr-guide" aria-labelledby="worktime-qr-guide-title">
    <header className="worktime-qr-guide-header" data-slot="worktime-qr-guide-header"><div><span className="worktime-qr-guide-kicker">{t('st.adm.guideKicker')}</span><h3 id="worktime-qr-guide-title">{t('st.adm.guideTitle')}</h3><p>{t('st.adm.guideLead')}</p></div><div className="worktime-qr-guide-progress" aria-label={t('st.adm.guideStepsAria')}><span>6</span><small>{t('st.adm.guideStepsUnit')}</small></div></header>
    <ol className="worktime-qr-guide-steps" data-slot="worktime-qr-guide-steps" aria-label={t('st.adm.guideSteps')}>{WORKTIME_QR_SETUP_STEPS.map(({ icon: Icon, title, text }, index) => <li key={title} data-slot="worktime-qr-guide-step"><span className="worktime-qr-step-icon"><Icon size={19} aria-hidden="true" /></span><span className="worktime-qr-step-number">{String(index + 1).padStart(2, '0')}</span><div><strong>{t(title)}</strong><p>{t(text)}</p></div></li>)}</ol>
    <aside className="worktime-qr-troubleshooting" data-slot="worktime-qr-troubleshooting"><div className="worktime-qr-trouble-title"><ShieldAlert size={17} /><strong>{t('st.adm.troubleTitle')}</strong></div><div><p><b>{t('st.adm.troubleExpired')}</b> {t('st.adm.troubleExpiredText')}</p><p><b>{t('st.adm.troubleOffline')}</b> {t('st.adm.troubleOfflineText')}</p><p><b>{t('st.adm.troubleMulti')}</b> {t('st.adm.troubleMultiText')}</p></div></aside>
    <p className="worktime-qr-guide-note">{t('st.adm.guideNote')}</p>
  </section>
}

function WorktimeGeofencePanel() {
  const { t } = useTranslation()
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
      toast.error(t('st.adm.geoUnsupported'))
      return
    }
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setLatitude(position.coords.latitude.toFixed(6))
        setLongitude(position.coords.longitude.toFixed(6))
        toast.success(t('st.adm.geoFilled'))
      },
      () => toast.error(t('st.adm.geoFailed')),
      { enableHighAccuracy: true, maximumAge: 0, timeout: 10_000 },
    )
  }

  const save = (event: React.FormEvent) => {
    event.preventDefault()
    const nextLatitude = Number(latitude)
    const nextLongitude = Number(longitude)
    const nextRadius = Number(radius)
    if (!Number.isFinite(nextLatitude) || !Number.isFinite(nextLongitude) || nextLatitude < -90 || nextLatitude > 90 || nextLongitude < -180 || nextLongitude > 180) {
      toast.error(t('st.adm.geoLatLonRange'))
      return
    }
    if (!Number.isInteger(nextRadius) || nextRadius < 25 || nextRadius > 5000) {
      toast.error(t('st.adm.geoRadiusRange'))
      return
    }
    update.mutate({ latitude: nextLatitude, longitude: nextLongitude, radius_meters: nextRadius })
  }

  const mapLatitude = latitude.trim() ? Number(latitude) : null
  const mapLongitude = longitude.trim() ? Number(longitude) : null
  return <SettingsSection title={t('st.adm.geoTitle')} icon={MapPin} className="settings-embedded worktime-geofence-admin">{settings.isError ? <div className="worktime-alert error" role="alert"><ShieldCheck size={17} />{t('st.adm.geoLoadFailed')}</div> : <form className="worktime-geofence-form" onSubmit={save}><WorktimeMapPicker latitude={Number.isFinite(mapLatitude) ? mapLatitude : null} longitude={Number.isFinite(mapLongitude) ? mapLongitude : null} radiusMeters={Number(radius) || 150} disabled={!canEdit || update.isPending} onChange={({ latitude: nextLatitude, longitude: nextLongitude }) => { setLatitude(nextLatitude.toFixed(6)); setLongitude(nextLongitude.toFixed(6)) }} /><div className="form-row"><label>{t('st.adm.latitude')}<input type="number" step="any" min="-90" max="90" value={latitude} onChange={(event) => setLatitude(event.target.value)} disabled={!canEdit || update.isPending} placeholder="47.9184" required /></label><label>{t('st.adm.longitude')}<input type="number" step="any" min="-180" max="180" value={longitude} onChange={(event) => setLongitude(event.target.value)} disabled={!canEdit || update.isPending} placeholder="106.9177" required /></label><label>{t('st.adm.radius')}<input type="number" step="1" min="25" max="5000" value={radius} onChange={(event) => setRadius(event.target.value)} disabled={!canEdit || update.isPending} required /></label></div><div className="worktime-geofence-actions"><button type="button" className="secondary-action" onClick={useCurrentLocation} disabled={!canEdit || update.isPending}><LocateFixed size={15} />{t('st.adm.useCurrent')}</button><button type="submit" className="primary-action" disabled={!canEdit || update.isPending}>{update.isPending ? t('st.adm.saving') : t('st.adm.saveLocation')}</button></div><p className="field-help">{settings.data?.configured ? t('st.adm.geoActive', { radius: settings.data.radius_meters }) : t('st.adm.geoNotConfigured')}{!canEdit && ` · ${t('st.adm.adminOnly')}`}</p></form>}</SettingsSection>
}

function UnlinkedAccountsPanel() {
  const { t } = useTranslation()
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
      setUsername(''); setPassword(''); toast.success(t('st.adm.userCreated'))
    } catch (error: any) { toast.error(tenancyErrorMessage(error, t('st.adm.userCreateFailed'))) }
  }
  const toggleRole = (account: { id: number; roles: string[] }, roleName: string) => {
    const roles = account.roles.includes(roleName) ? account.roles.filter((item) => item !== roleName) : [...account.roles, roleName]
    if (!roles.length) { toast.error(t('st.adm.minOneRole')); return }
    updateAccount.mutate({ id: account.id, roles })
  }
  const changePassword = async (account: { id: number; email: string }) => {
    const next = window.prompt(t('st.adm.promptPassword', { email: account.email }))
    if (!next) return
    if (next.length < 10) { toast.error(t('st.adm.passwordMin')); return }
    try { await updateAccount.mutateAsync({ id: account.id, password: next }); toast.success(t('st.adm.passwordUpdated')) } catch { /* API hook displays server feedback */ }
  }
  const remove = (account: { id: number; email: string }) => {
    if (window.confirm(t('st.adm.confirmDeleteUser', { email: account.email }))) deleteAccount.mutate(account.id)
  }
  return <SettingsSection title={t('st.adm.unlinkedUsers')} icon={Users2} className="account-admin panel"><SeatLimitNotice context="account" /><form className="account-create-form" onSubmit={create}><label>{t('st.adm.username')}<input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required /></label><label>{t('st.adm.password')}<input value={password} onChange={(event) => setPassword(event.target.value)} type="password" minLength={10} autoComplete="new-password" required /></label><label>{t('st.adm.role')}<select value={role} onChange={(event) => setRole(event.target.value)}>{ACCOUNT_ROLES.map(([value, label]) => <option value={value} key={value}>{label.startsWith('st.') ? t(label) : label}</option>)}</select></label><button className="primary-action compact" disabled={createAccount.isPending}><UserPlus size={15} />{t('st.adm.add')}</button></form><div className="account-list" aria-live="polite">{unlinkedAccounts.map((account) => <article key={account.id}><div className="account-identity"><strong>{account.email}</strong><span>{t('st.adm.unlinkedStatus', { status: account.status })}</span></div><fieldset className="role-editor"><legend>{t('st.adm.accessRoles')}</legend>{ACCOUNT_ROLES.map(([value, label]) => <label key={value}><input type="checkbox" checked={account.roles.includes(value)} onChange={() => toggleRole(account, value)} disabled={updateAccount.isPending} /><span>{label.startsWith('st.') ? t(label) : label}</span></label>)}</fieldset><div className="settings-row-actions"><button type="button" className="settings-icon-action" onClick={() => changePassword(account)} aria-label={t('st.adm.changePasswordFor', { email: account.email })} title={t('st.adm.changePassword')}><KeyRound size={16} /></button><button type="button" className="settings-icon-action" onClick={() => updateAccount.mutate({ id: account.id, status: account.status === 'disabled' ? 'active' : 'disabled' })} aria-label={account.status === 'disabled' ? t('st.adm.activateFor', { email: account.email }) : t('st.adm.deactivateFor', { email: account.email })} title={account.status === 'disabled' ? t('st.adm.activate') : t('st.adm.deactivate')}><span className="sr-only">{account.status === 'disabled' ? t('st.adm.activate') : t('st.adm.deactivate')}</span>{account.status === 'disabled' ? <Check size={16} /> : <X size={16} />}</button><button type="button" className="settings-icon-action danger" onClick={() => remove(account)} aria-label={t('st.adm.deleteFor', { email: account.email })} title={t('st.adm.delete')}><Trash2 size={16} /></button></div></article>)}</div></SettingsSection>
}

export function AccessControlSettingsPage() {
  const { t } = useTranslation()
  return <SettingsPage categoryId="people" activeTab="/administration/people/users" title={t('st.tab.users')}><SeatUsagePanel /><SettingsSection title={t('st.adm.employeesAndRoles')} icon={Users2} className="settings-embedded access-settings"><EmployeesPage /></SettingsSection><UnlinkedAccountsPanel /><SettingsSection title={t('st.adm.onboarding')} icon={UserRoundCog} className="settings-embedded"><OnboardingPage /></SettingsSection></SettingsPage>
}

export function AutomationSettingsPage() {
  const { t } = useTranslation()
  const isAdmin = useAuthStore((state) => (state.actor?.account_roles ?? state.actor?.roles ?? EMPTY_ROLES).includes('admin'))
  const calendar = useGoogleCalendarConnect()
  const calendarStatus = useGoogleCalendarStatus()
  const syncMode = useGoogleCalendarSyncMode()
  const disconnect = useGoogleCalendarDisconnect()
  const connectCalendar = async () => {
    try {
      const result = await calendar.mutateAsync()
      if (result.authorization_url) window.location.assign(result.authorization_url)
      else toast.error(t('st.adm.googleOauthMissing'))
    } catch { /* mutation feedback is handled by the API hook */ }
  }
  return <SettingsPage categoryId="integrations" activeTab="/administration/integrations/overview" title={t('st.tab.integrations')}>
    <SettingsSection title="Google Calendar" icon={CalendarClock} className="integration-grid settings-integrations"><article className="integration-panel"><div><strong>Google Calendar</strong><p>{calendarStatus.data?.status === 'active' ? `${t('st.adm.gcConnected', { state: calendarStatus.data.watch_active ? t('st.adm.gcWatchActive') : t('st.adm.gcWatchUpdating') })}${calendarStatus.data.last_error ? ` · ${calendarStatus.data.last_error}` : ''}` : t('st.adm.notConnected')}</p>{calendarStatus.data?.status === 'active' && <select aria-label={t('st.adm.syncModeAria')} value={calendarStatus.data.sync_mode} onChange={(event) => syncMode.mutate(event.target.value as 'outbound' | 'bidirectional')}><option value="outbound">{t('st.adm.syncOutbound')}</option><option value="bidirectional">{t('st.adm.syncBidirectional')}</option></select>}</div>{calendarStatus.data?.status === 'active' ? <button className="secondary-action" onClick={() => disconnect.mutate()} disabled={disconnect.isPending}>{t('st.adm.disconnect')}</button> : <button className="secondary-action" onClick={connectCalendar} disabled={calendar.isPending}>{t('st.adm.connect')}</button>}</article></SettingsSection>
    {isAdmin && <SettingsSection title={t('st.adm.telegramBot')} icon={Send} className="settings-embedded"><TenantTelegramBotSettings /></SettingsSection>}
    {isAdmin && <SettingsSection title={t('st.adm.notificationsAll')} icon={Bell} className="settings-embedded"><NotificationSettings /></SettingsSection>}
    <SettingsSection title={t('st.adm.notificationsTelegram')} icon={UserRoundCog} className="settings-embedded"><ManagerSettingsPage /></SettingsSection>
  </SettingsPage>
}

export function AdminAccessSettingsPage() {
  const { t } = useTranslation()
  return <SettingsPage categoryId="security" activeTab="/administration/security/authentication" title={t('st.tab.authentication')}>
    <SettingsSection title={t('st.adm.adminUserPassword')} icon={KeyRound} className="settings-embedded admin-access-settings"><div className="settings-form-stack"><AdminAccessPanel /></div></SettingsSection>
    <SettingsSection title={t('tfa.set.section')} icon={ShieldCheck} className="settings-embedded"><TwoFactorSettings /></SettingsSection>
  </SettingsPage>
}

export function OyunsAssistantSettingsPage() {
  const { t } = useTranslation()
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const canManageAgent = roles.includes('admin')
  return <SettingsPage categoryId="ai" activeTab="/administration/ai/knowledge" title={t('st.cat.ai')}>
    {canManageAgent && <SettingsSection title={t('st.adm.aiModelKey')} icon={KeyRound} className="settings-embedded"><AiAgentSettings /></SettingsSection>}
    {canManageAgent && <SettingsSection title={t('st.adm.aiAccess')} icon={ShieldCheck} className="settings-embedded"><AiAccessSettings /></SettingsSection>}
    <SettingsSection title={t('st.adm.companyData')} icon={BookOpen} className="settings-embedded"><KnowledgePage /></SettingsSection>
    {canManageAgent && <SettingsSection title={t('st.adm.oyunsTraining')} icon={Code2} className="settings-embedded"><DeveloperPage /></SettingsSection>}
  </SettingsPage>
}
