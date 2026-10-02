import i18n from '../i18n'
import { useTranslation } from 'react-i18next'
import { useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import toast from 'react-hot-toast'
import { Archive, ArchiveRestore, Building2, CalendarDays, Check, Clock, Copy, Link2, Pencil, Plus, Search, Trash2, UserPlus, Users, Wallet, X, type LucideIcon } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useHREmployeeRoles, useSetHREmployeeRoles, useActor, useArchiveHREmployee, useCreateHRDepartment, useCreateHREmployee, useDecideHRLeave, useDeleteHRDepartment, useDeleteHREmployeePermanently, useHRDepartments, useHREmployees, useHRLeaveBalances, useHRLeaveRequests, useSetHRLeaveBalance, useSubmitHRLeave, useUpdateHRDepartment, useUpdateHREmployee, useUpdateHRLeave } from '../api/enterprise'
import type { HRDepartment, HREmployee, HREmploymentStatus, HREmploymentType, HRLeaveRequest } from '../api/enterprise'
import { Badge, Btn, Card, Input, Modal, Select } from '../components/ui'
import { WorktimeLocationLogCard } from '../components/WorktimeLocationLog'
import { WorkerActionsMenu } from '../components/WorkerActionsMenu'
import { SeatLimitNotice } from '../components/SeatLimitNotice'
import { MonthlyPayrollProfileDrawer } from '../components/MonthlyPayrollProfileDrawer'
import { EmployeeWorktimeStats } from '../components/EmployeeWorktimeStats'
import { AttendanceGrid } from '../components/attendance/AttendanceGrid'
import { normalizeRegistrationNumber, parseRegistrationNumber } from '../utils/registrationNumber'
import { telegramBotRequiredHint, useTenantContext } from '../api/tenancy'
import { CreateButton } from '../components/CreateButton'

type Tab = 'directory' | 'departments' | 'leave' | 'attendance' | 'payroll'
const errorText = (error: any) => {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((item) => String(item?.msg || '').replace(/^Value error, /, '')).filter(Boolean).join('; ') || i18n.t('hr.error.invalid')
  if (detail && typeof detail === 'object') {
    if (typeof detail.message === 'string') return detail.message
    if (detail.code === 'leave_balance_insufficient') return i18n.t('hr.error.insufficientLeave', { days: detail.available_days ?? 0 })
  }
  return i18n.t('hr.error.failed')
}

export const EMPLOYMENT_STATUS_LABELS: Record<HREmploymentStatus, string> = {
  get active() { return i18n.t('hr.active') },
  get probation() { return i18n.t('hr.status.probation') },
  get on_leave() { return i18n.t('hr.status.onLeave') },
  get suspended() { return i18n.t('hr.status.suspended') },
  get inactive() { return i18n.t('hr.inactive') },
  get terminated() { return i18n.t('hr.drawer.terminated') },
}
const STATUS_COLORS: Record<HREmploymentStatus, 'green' | 'blue' | 'purple' | 'yellow' | 'muted' | 'red'> = { active: 'green', probation: 'blue', on_leave: 'purple', suspended: 'yellow', inactive: 'muted', terminated: 'red' }
const EMPLOYMENT_TYPE_LABELS: Record<HREmploymentType, string> = {
  get full_time() { return i18n.t('hr.type.fullTime') },
  get part_time() { return i18n.t('hr.type.partTime') },
  get contract() { return i18n.t('hr.type.contract') },
  get intern() { return i18n.t('hr.type.intern') },
}
const GENDER_LABELS = {
  get male() { return i18n.t('hr.gender.male') },
  get female() { return i18n.t('hr.gender.female') },
} as const
const WORKING_STATUSES: HREmploymentStatus[] = ['active', 'probation']
const statusOptions = (statuses: HREmploymentStatus[]) => statuses.map((value) => ({ value, label: EMPLOYMENT_STATUS_LABELS[value] }))

function StatusBadge({ employee }: { employee: HREmployee }) {
  const { t } = useTranslation()
  if (employee.is_archived) return <Badge color="muted">{t('hr.archived')}</Badge>
  const status = employee.employment_status in EMPLOYMENT_STATUS_LABELS ? employee.employment_status : employee.is_active ? 'active' : 'inactive'
  return <Badge color={STATUS_COLORS[status]}>{EMPLOYMENT_STATUS_LABELS[status]}</Badge>
}

export function HRWorkspacePage() {
  const { t } = useTranslation()
  const actor = useActor()
  const isHR = Boolean(actor.data?.roles?.some((role) => role === 'admin' || role === 'hr'))
  const isManager = Boolean(actor.data?.roles?.some((role) => ['admin', 'hr', 'manager', 'team_lead'].includes(role)))
  const [tab, setTab] = useState<Tab>('directory')
  const [search, setSearch] = useState('')
  const [department, setDepartment] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [includeArchived, setIncludeArchived] = useState(false)
  const [selected, setSelected] = useState<HREmployee | null>(null)
  const [editing, setEditing] = useState<HREmployee | 'new' | null>(null)
  const [invite, setInvite] = useState<string | null>(null)
  const employees = useHREmployees({ search: search || undefined, department_id: department ? Number(department) : undefined, status: statusFilter || undefined, include_archived: includeArchived })
  const allEmployees = useHREmployees({ page_size: 200 })
  const departments = useHRDepartments()
  const leave = useHRLeaveRequests({ status: isManager ? undefined : undefined })
  const balances = useHRLeaveBalances({ employee_id: isHR ? undefined : actor.data?.employee_id || undefined })
  const visibleTabs: Tab[] = isHR ? ['directory', 'departments', 'leave', 'attendance', 'payroll'] : ['directory', 'leave', 'attendance']
  const navIcons: Record<Tab, LucideIcon> = { directory: Users, departments: Building2, leave: CalendarDays, attendance: Clock, payroll: Wallet }
  const navLabels: Record<Tab, string> = { directory: t('hr.tab.directory'), departments: t('hr.tab.departments'), leave: t('hr.tab.leave'), attendance: t('hr.tab.attendance'), payroll: t('hr.tab.payroll') }
  return <div className="hr-workspace">
    <div className="page-tabs">
      <nav className="page-tabs-list" aria-label={t('hr.sectionsLabel')}>{visibleTabs.map((item) => <button key={item} className={tab === item ? 'active' : ''} onClick={() => setTab(item)}>{(() => { const Icon = navIcons[item]; return <Icon size={15} /> })()}{navLabels[item]}</button>)}</nav>
      {isHR && <div className="page-tabs-actions"><CreateButton label={t('hr.addWorker')} icon={<UserPlus size={16} />} onClick={() => setEditing('new')} /></div>}
    </div>
    {tab === 'directory' && <Directory employees={employees.data?.items || []} departments={departments.data || []} search={search} setSearch={setSearch} department={department} setDepartment={setDepartment} statusFilter={statusFilter} setStatusFilter={setStatusFilter} includeArchived={includeArchived} setIncludeArchived={setIncludeArchived} canEdit={isHR} onSelect={setSelected} onEdit={setEditing} />}
    {tab === 'departments' && isHR && <DepartmentsPanel departments={departments.data || []} employees={allEmployees.data?.items || []} />}
    {tab === 'leave' && <LeavePanel isHR={isHR} isManager={isManager} balances={balances.data || []} requests={leave.data || []} employees={employees.data?.items || []} />}
    {tab === 'attendance' && <Card className="hr-attendance-card"><AttendanceGrid canEdit={isManager} onOpenLeave={() => setTab('leave')} /></Card>}
    {tab === 'attendance' && isHR && <WorktimeLocationLogCard />}
    {tab === 'payroll' && isHR && <PayrollPanel onGoEmployees={() => setTab('directory')} />}
    {selected && <EmployeeDrawer employee={selected} isHR={isHR} canSeeStats={isManager} onClose={() => setSelected(null)} onEdit={() => { setEditing(selected); setSelected(null) }} />}
    {editing && <WorkerFormModal employee={editing === 'new' ? null : editing} departments={departments.data || []} employees={allEmployees.data?.items || []} onClose={() => setEditing(null)} onCreated={(url) => { setEditing(null); if (url) setInvite(url); else toast.success(t('hr.workerAdded')) }} />}
    {invite && <Modal title={t('hr.inviteReady')} onClose={() => setInvite(null)}><div className="hr-invite-result"><p>{t('hr.inviteHint')}</p><code>{invite}</code><div><Btn variant="primary" onClick={() => { void navigator.clipboard?.writeText(invite); toast.success(t('hr.copied')) }}><Copy size={14} />{t('hr.copy')}</Btn><a className="secondary-action" href={invite} target="_blank" rel="noreferrer"><Link2 size={14} />{t('hr.open')}</a></div></div></Modal>}
  </div>
}

function Directory({ employees, departments, search, setSearch, department, setDepartment, statusFilter, setStatusFilter, includeArchived, setIncludeArchived, canEdit, onSelect, onEdit }: { employees: HREmployee[]; departments: HRDepartment[]; search: string; setSearch: (value: string) => void; department: string; setDepartment: (value: string) => void; statusFilter: string; setStatusFilter: (value: string) => void; includeArchived: boolean; setIncludeArchived: (value: boolean) => void; canEdit: boolean; onSelect: (employee: HREmployee) => void; onEdit: (employee: HREmployee) => void }) {
  const { t } = useTranslation()
  const [openMenuId, setOpenMenuId] = useState<number | null>(null)
  const update = useUpdateHREmployee()
  const archive = useArchiveHREmployee()
  const removeForever = useDeleteHREmployeePermanently()
  const run = (promise: Promise<unknown>, message: string) => promise.then(() => toast.success(message)).catch((error) => toast.error(errorText(error)))
  // "active"/"inactive" are server-side groups (working vs. not); the rest match one status.
  const statusFilterOptions = [{ value: '', label: t('hr.dir.allStatuses') }, { value: 'active', label: t('hr.dir.working') }, { value: 'inactive', label: t('hr.dir.notWorking') }, ...statusOptions(['probation', 'on_leave', 'suspended', 'terminated'])]
  return <Card className="hr-directory-card">
    <div className="hr-toolbar hr-directory-toolbar">
      <label className="hr-search"><Search size={15} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={canEdit ? t('hr.dir.searchFull') : t('hr.dir.searchShort')} /></label>
      <Select value={department} onChange={setDepartment} options={[{ value: '', label: t('hr.dir.allDepartments') }, ...departments.map((item) => ({ value: String(item.id), label: item.is_active ? item.name : t('hr.inactiveItem', { name: item.name }) }))]} />
      <Select value={statusFilter} onChange={setStatusFilter} options={statusFilterOptions} />
      {canEdit && <label className="employee-archive-toggle"><input type="checkbox" checked={includeArchived} onChange={(event) => setIncludeArchived(event.target.checked)} />{t('hr.archived')}</label>}
    </div>
    <div className="hr-directory-table"><table><thead><tr><th>{t('hr.dir.employee')}</th><th>{t('hr.position')}</th><th>{t('hr.department')}</th><th>{t('hr.telegram')}</th><th>{t('hr.status')}</th>{canEdit && <th />}</tr></thead><tbody>{employees.map((employee) => <tr key={employee.id} onClick={() => onSelect(employee)}>
      <td><div className="hr-person"><span>{(employee.first_name || employee.name || '?')[0]}</span><strong>{employee.name}</strong></div></td>
      <td>{employee.job_title || employee.employment_role || '—'}</td>
      <td>{employee.department_name || t('hr.unknown')}</td>
      <td>{employee.telegram_status === 'connected' ? <Badge color="green">{t('hr.tg.connected')}</Badge> : employee.telegram_status === 'pending_invite' ? <Badge color="yellow">{t('hr.tg.pending')}</Badge> : <Badge color="muted">{t('hr.tg.notInvited')}</Badge>}</td>
      <td><StatusBadge employee={employee} /></td>
      {canEdit && <td onClick={(event) => event.stopPropagation()}><WorkerActionsMenu
        worker={{ ...employee, deleted_at: employee.is_archived ? 'archived' : null }}
        open={openMenuId === employee.id}
        onOpen={() => setOpenMenuId(openMenuId === employee.id ? null : employee.id)}
        onEdit={() => { setOpenMenuId(null); onEdit(employee) }}
        onDelete={() => { setOpenMenuId(null); if (window.confirm(t('hr.dir.archiveConfirm', { name: employee.name }))) void run(archive.mutateAsync(employee.id), t('hr.dir.archivedToast')) }}
        onSetActive={(active) => { setOpenMenuId(null); void run(update.mutateAsync({ id: employee.id, is_active: active, restore: active && employee.is_archived }), active ? t('hr.dir.activatedToast') : t('hr.dir.deactivatedToast')) }}
        onPermanentDelete={() => { setOpenMenuId(null); if (window.confirm(t('hr.dir.deleteForeverConfirm', { name: employee.name }))) void run(removeForever.mutateAsync(employee.id), t('hr.dir.deletedToast')) }}
      /></td>}
    </tr>)}</tbody></table>{!employees.length && <div className="hr-empty">{t('hr.emp.notFound')}</div>}</div>
  </Card>
}

type WorkerForm = {
  last_name: string; first_name: string; name: string; registration_number: string; birthday: string; gender: string
  phone_number: string; email: string; address: string; emergency_contact_name: string; emergency_contact_phone: string
  department_id: string; manager_id: string; job_title: string; employment_role: string; employment_type: string; employment_status: string
  start_date: string; probation_end_date: string; end_date: string; termination_reason: string; telegram_id: string; annual_leave_days: string
}
const WORKER_ID_FIELDS = new Set(['department_id', 'manager_id'])
const workerForm = (employee: HREmployee | null): WorkerForm => ({
  last_name: employee?.last_name || '', first_name: employee?.first_name || '', name: employee?.name || '',
  registration_number: employee?.registration_number || '', birthday: employee?.birthday || '', gender: employee?.gender || '',
  phone_number: employee?.phone_number || '', email: employee?.email || '', address: employee?.address || '',
  emergency_contact_name: employee?.emergency_contact_name || '', emergency_contact_phone: employee?.emergency_contact_phone || '',
  department_id: employee?.department_id ? String(employee.department_id) : '', manager_id: employee?.manager_id ? String(employee.manager_id) : '',
  job_title: employee?.job_title || '', employment_role: employee?.employment_role || '', employment_type: employee?.employment_type || 'full_time',
  employment_status: employee?.employment_status || 'active', start_date: employee?.start_date || '', probation_end_date: employee?.probation_end_date || '',
  end_date: employee?.end_date || '', termination_reason: employee?.termination_reason || '', telegram_id: '', annual_leave_days: '',
})
const formValue = (key: string, value: string) => value.trim() === '' ? null : WORKER_ID_FIELDS.has(key) ? Number(value) : value.trim()

function WorkerFormModal({ employee, departments, employees, onClose, onCreated }: { employee: HREmployee | null; departments: HRDepartment[]; employees: HREmployee[]; onClose: () => void; onCreated: (url: string | null) => void }) {
  const { t } = useTranslation()
  const create = useCreateHREmployee(); const update = useUpdateHREmployee()
  const tenant = useTenantContext()
  // Without the tenant's own Telegram bot a Telegram ID cannot be used.
  const botConnected = tenant.data?.telegram_bot_connected !== false
  const initial = useMemo(() => workerForm(employee), [employee])
  const [form, setForm] = useState<WorkerForm>(initial)
  const set = (key: keyof WorkerForm) => (value: string) => setForm((current) => ({ ...current, [key]: value }))
  const setRegistration = (value: string) => setForm((current) => {
    const decoded = parseRegistrationNumber(value)
    return { ...current, registration_number: value, birthday: current.birthday || decoded?.birthday || '', gender: current.gender || decoded?.gender || '' }
  })
  const registrationInvalid = form.registration_number.trim() !== '' && !parseRegistrationNumber(form.registration_number)
  const status = form.employment_status as HREmploymentStatus
  const nameMissing = employee ? !form.name.trim() : !(form.name.trim() || form.first_name.trim() || form.last_name.trim())
  const departmentOptions = [{ value: '', label: t('hr.notSelected') }, ...departments.filter((item) => item.is_active || String(item.id) === form.department_id).map((item) => ({ value: String(item.id), label: item.name }))]
  const managerOptions = [{ value: '', label: t('hr.notSelected') }, ...employees.filter((item) => item.id !== employee?.id && item.is_active && !item.is_archived).map((item) => ({ value: String(item.id), label: item.name }))]
  const pending = create.isPending || update.isPending
  const submit = async () => {
    const values: Record<string, unknown> = {}
    for (const key of Object.keys(form) as (keyof WorkerForm)[]) {
      if (key === 'telegram_id' || key === 'annual_leave_days') continue
      const next = key === 'registration_number' ? normalizeRegistrationNumber(form[key]) : form[key]
      // Edits send only what changed, so an archived worker is not restored by saving.
      if (employee && next === initial[key]) continue
      values[key] = formValue(key, next)
    }
    try {
      if (employee) {
        if (!Object.keys(values).length) { onClose(); return }
        await update.mutateAsync({ id: employee.id, ...values })
        toast.success(t('hr.emp.saved')); onClose()
      } else {
        const result = await create.mutateAsync({ ...values, telegram_id: botConnected ? form.telegram_id.trim() || null : null, annual_leave_days: form.annual_leave_days ? Number(form.annual_leave_days) : null })
        if (result.seat_warning) toast(result.seat_warning, { icon: '⚠️', duration: 8000 })
        onCreated(result.invite?.deep_link ?? null)
      }
    } catch (error) { toast.error(errorText(error)) }
  }
  return <Modal title={employee ? t('hr.form.editTitle', { name: employee.name }) : t('hr.addWorker')} onClose={onClose} className="hr-worker-modal">
    {!employee && <SeatLimitNotice />}
    <h4 className="hr-form-section">{t('hr.form.personal')}</h4>
    <div className="hr-form-grid">
      <Input label={t('hr.form.lastName')} value={form.last_name} onChange={set('last_name')} fullWidth />
      <Input label={t('hr.name')} value={form.first_name} onChange={set('first_name')} fullWidth />
      <Input label={employee ? t('hr.form.displayName') : t('hr.form.displayNameHint')} value={form.name} onChange={set('name')} fullWidth />
      <div><Input label={t('hr.form.registry')} value={form.registration_number} onChange={setRegistration} placeholder={t('hr.form.registryPlaceholder')} fullWidth />{registrationInvalid && <p className="hr-field-error">{t('hr.form.registryHint')}</p>}</div>
      <Input label={t('hr.form.birthDate')} type="date" value={form.birthday} onChange={set('birthday')} fullWidth />
      <Select label={t('hr.form.gender')} value={form.gender} onChange={set('gender')} options={[{ value: '', label: t('hr.notSelected') }, { value: 'male', label: GENDER_LABELS.male }, { value: 'female', label: GENDER_LABELS.female }]} fullWidth />
      <Input label={t('hr.form.phone')} type="tel" value={form.phone_number} onChange={set('phone_number')} placeholder="9911 2233" fullWidth />
      <Input label={t('hr.form.email')} type="email" value={form.email} onChange={set('email')} fullWidth />
      <div className="hr-form-wide"><Input label={t('hr.form.address')} value={form.address} onChange={set('address')} fullWidth /></div>
    </div>
    <h4 className="hr-form-section">{t('hr.form.employment')}</h4>
    <div className="hr-form-grid">
      <Select label={t('hr.department')} value={form.department_id} onChange={set('department_id')} options={departmentOptions} fullWidth />
      <Select label={t('hr.form.manager')} value={form.manager_id} onChange={set('manager_id')} options={managerOptions} fullWidth />
      <Input label={t('hr.position')} value={form.job_title} onChange={set('job_title')} fullWidth />
      <Input label={t('hr.form.role')} value={form.employment_role} onChange={set('employment_role')} fullWidth />
      <Select label={t('hr.form.employmentType')} value={form.employment_type} onChange={set('employment_type')} options={Object.entries(EMPLOYMENT_TYPE_LABELS).map(([value, label]) => ({ value, label }))} fullWidth />
      <Select label={t('hr.status')} value={form.employment_status} onChange={set('employment_status')} options={statusOptions(employee ? ['active', 'probation', 'on_leave', 'suspended', 'inactive', 'terminated'] : WORKING_STATUSES)} fullWidth />
      <Input label={t('hr.form.hireDate')} type="date" value={form.start_date} onChange={set('start_date')} fullWidth />
      {(status === 'probation' || form.probation_end_date) && <Input label={t('hr.form.probationEnd')} type="date" value={form.probation_end_date} onChange={set('probation_end_date')} fullWidth />}
      {status === 'terminated' && <><Input label={t('hr.form.terminationDate')} type="date" value={form.end_date} onChange={set('end_date')} fullWidth /><Input label={t('hr.form.terminationReason')} value={form.termination_reason} onChange={set('termination_reason')} fullWidth /></>}
      {!employee && <><Input label={t('hr.form.annualLeave')} type="number" min="0" max="366" value={form.annual_leave_days} onChange={set('annual_leave_days')} placeholder="15" fullWidth /><Input label={t('hr.form.telegramOptional')} value={botConnected ? form.telegram_id : ''} onChange={set('telegram_id')} placeholder="123456789" fullWidth disabled={!botConnected} hint={botConnected ? undefined : telegramBotRequiredHint()} /></>}
    </div>
    {employee && !WORKING_STATUSES.includes(status) && WORKING_STATUSES.includes(employee.employment_status) && <p className="hr-form-note">{t('hr.form.inactiveHint')}</p>}
    <h4 className="hr-form-section">{t('hr.form.emergency')}</h4>
    <div className="hr-form-grid">
      <Input label={t('hr.form.contactPerson')} value={form.emergency_contact_name} onChange={set('emergency_contact_name')} placeholder={t('hr.form.contactName')} fullWidth />
      <Input label={t('hr.form.phone')} type="tel" value={form.emergency_contact_phone} onChange={set('emergency_contact_phone')} fullWidth />
    </div>
    <div className="hr-modal-actions"><Btn onClick={onClose}>{t('hr.cancelAlt')}</Btn><Btn variant="primary" onClick={submit} disabled={nameMissing || registrationInvalid || pending}>{employee ? <><Check size={14} />{t('hr.save')}</> : <><Plus size={14} />{botConnected ? t('hr.form.createInvite') : t('hr.form.create')}</>}</Btn></div>
  </Modal>
}

const ROLE_LABELS: Record<string, string> = {
  member: 'Member', manager: 'Supervisor', team_lead: 'Team lead', hr: 'HR', contractor: 'Contractor', client_auditor: 'Client auditor',
  get legal_counsel() { return i18n.t('hr.role.legalCounsel') }, admin: 'Admin',
}

function EmployeeRolesSection({ employee }: { employee: HREmployee }) {
  const { t } = useTranslation()
  const rolesQuery = useHREmployeeRoles(employee.account_id ? employee.id : undefined); const setRoles = useSetHREmployeeRoles()
  const data = rolesQuery.data
  const toggle = async (role: string) => {
    if (!data) return
    const next = data.roles.includes(role) ? data.roles.filter((item) => item !== role) : [...data.roles, role]
    if (!next.length) { toast.error(t('hr.emp.minOneRole')); return }
    try { await setRoles.mutateAsync({ employeeId: employee.id, roles: next }); toast.success(t('hr.roles.updated')) } catch (error) { toast.error(errorText(error)) }
  }
  return <section className="hr-drawer-section"><h3>{t('hr.roles.title')}</h3>{!employee.account_id ? <p>{t('hr.roles.noAccount')}</p> : !data ? <p>{t('hr.loading')}</p> : <><fieldset className="role-editor" disabled={data.locked || setRoles.isPending}><legend>{t('hr.roles.accessRoles')}</legend>{data.assignable_roles.map((role) => <label key={role}><input type="checkbox" checked={data.roles.includes(role)} onChange={() => toggle(role)} /><span>{ROLE_LABELS[role] || role}</span></label>)}</fieldset>{data.locked && <p>{t('hr.roles.adminHint')}</p>}</>}</section>
}

function EmployeeDrawer({ employee, isHR, canSeeStats, onClose, onEdit }: { employee: HREmployee; isHR: boolean; canSeeStats: boolean; onClose: () => void; onEdit: () => void }) {
  const { t } = useTranslation()
  const [showPayrollSettings, setShowPayrollSettings] = useState(false);
  const hasPrivate = isHR || Boolean(employee.registration_number || employee.phone_number || employee.email || employee.birthday)
  // Portaled: the route enter animation leaves a stacking context on the page,
  // which would otherwise trap the fixed drawer under the sticky top navbar.
  return createPortal(<>{!showPayrollSettings && <div className="hr-drawer-backdrop" onClick={onClose}><aside className="hr-drawer" role="dialog" aria-label={`${employee.name} profile`} onClick={(event) => event.stopPropagation()}>
    <header><div><span className="eyebrow">{t('hr.drawer.eyebrow')}</span><h2>{employee.name}</h2><p>{employee.telegram_username ? `@${employee.telegram_username.replace(/^@/, '')}` : t('hr.drawer.noTelegram')}</p><div className="hr-drawer-badges"><StatusBadge employee={employee} /></div></div><div className="hr-drawer-header-actions">{isHR && <button onClick={onEdit} aria-label={t('hr.workerActions.edit')}><Pencil size={16} /></button>}<button onClick={onClose} aria-label={t('hr.close')}><X size={18} /></button></div></header>
    <section className="hr-drawer-section"><h3>{t('hr.form.employment')}</h3><dl>
      <dt>{t('hr.department')}</dt><dd>{employee.department_name || '—'}</dd>
      <dt>{t('hr.position')}</dt><dd>{employee.job_title || '—'}</dd>
      <dt>{t('hr.form.manager')}</dt><dd>{employee.manager_name || '—'}</dd>
      <dt>{t('hr.form.employmentType')}</dt><dd>{EMPLOYMENT_TYPE_LABELS[employee.employment_type] || '—'}</dd>
      <dt>{t('hr.drawer.hired')}</dt><dd>{employee.start_date || '—'}</dd>
      {employee.probation_end_date && <><dt>{t('hr.drawer.probationEnd')}</dt><dd>{employee.probation_end_date}</dd></>}
      {employee.end_date && <><dt>{t('hr.drawer.terminated')}</dt><dd>{employee.end_date}</dd></>}
      {employee.termination_reason && <><dt>{t('hr.form.terminationReason')}</dt><dd>{employee.termination_reason}</dd></>}
      <dt>{t('hr.telegram')}</dt><dd>{employee.telegram_status}</dd>
    </dl></section>
    {hasPrivate && <section className="hr-drawer-section"><h3>{t('hr.form.personal')}</h3><dl>
      <dt>{t('hr.form.registry')}</dt><dd>{employee.registration_number || '—'}</dd>
      <dt>{t('hr.form.birthDate')}</dt><dd>{employee.birthday || '—'}</dd>
      <dt>{t('hr.form.gender')}</dt><dd>{employee.gender ? GENDER_LABELS[employee.gender] : '—'}</dd>
      <dt>{t('hr.form.phone')}</dt><dd>{employee.phone_number || '—'}</dd>
      <dt>{t('hr.form.email')}</dt><dd>{employee.email || '—'}</dd>
      <dt>{t('hr.drawer.address')}</dt><dd>{employee.address || '—'}</dd>
      <dt>{t('hr.drawer.emergency')}</dt><dd>{[employee.emergency_contact_name, employee.emergency_contact_phone].filter(Boolean).join(' · ') || '—'}</dd>
    </dl></section>}
    {isHR && <section className="hr-drawer-section"><h3>{t('hr.drawer.payrollTitle')}</h3><p>{t('hr.drawer.payrollHint')}</p><button className="secondary-action" onClick={() => setShowPayrollSettings(true)}><Pencil size={14} />{t('hr.drawer.openPayroll')}</button></section>}
    {canSeeStats && <section className="hr-drawer-section"><EmployeeWorktimeStats employeeId={employee.id} employeeName={employee.name} /></section>}
    {isHR && <EmployeeRolesSection employee={employee} />}
  </aside></div>}{showPayrollSettings && <MonthlyPayrollProfileDrawer employee={{ id: employee.id, name: employee.name }} onClose={() => setShowPayrollSettings(false)} />}</>, document.body)
}

function DepartmentsPanel({ departments, employees }: { departments: HRDepartment[]; employees: HREmployee[] }) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState<HRDepartment | 'new' | null>(null)
  const [showArchived, setShowArchived] = useState(false)
  const update = useUpdateHRDepartment(); const remove = useDeleteHRDepartment()
  const names = useMemo(() => new Map(employees.map((item) => [item.id, item.name])), [employees])
  const rows = departments.filter((item) => showArchived || item.is_active)
  const setActive = async (item: HRDepartment, active: boolean) => { try { await update.mutateAsync({ id: item.id, is_active: active }); toast.success(active ? t('hr.dept.activated') : t('hr.dept.deactivated')) } catch (error) { toast.error(errorText(error)) } }
  const destroy = async (item: HRDepartment) => { if (!window.confirm(t('hr.dept.deleteConfirm', { name: item.name }))) return; try { await remove.mutateAsync(item.id); toast.success(t('hr.dept.deleted')) } catch (error) { toast.error(errorText(error)) } }
  return <Card className="hr-directory-card">
    <div className="view-toolbar"><div><span className="eyebrow">{t('hr.dept.eyebrow')}</span><h2>{t('hr.dept.title')}</h2><p>{t('hr.dept.hint')}</p></div><div className="hr-inline-actions"><label className="employee-archive-toggle"><input type="checkbox" checked={showArchived} onChange={(event) => setShowArchived(event.target.checked)} />{t('hr.inactive')}</label><CreateButton label={t('hr.dept.add')} onClick={() => setEditing('new')} /></div></div>
    <div className="hr-directory-table"><table><thead><tr><th>{t('hr.name')}</th><th>{t('hr.dept.code')}</th><th>{t('hr.dept.manager')}</th><th>{t('hr.dir.employee')}</th><th>{t('hr.status')}</th><th /></tr></thead><tbody>{rows.map((item) => <tr key={item.id} onClick={() => setEditing(item)}>
      <td><div className="hr-person"><span><Building2 size={14} /></span><div className="hr-department-name"><strong>{item.name}</strong>{item.description && <small>{item.description}</small>}</div></div></td>
      <td>{item.code}</td>
      <td>{item.manager_employee_id ? names.get(item.manager_employee_id) || `#${item.manager_employee_id}` : '—'}</td>
      <td>{item.employee_count}</td>
      <td><Badge color={item.is_active ? 'green' : 'muted'}>{item.is_active ? t('hr.active') : t('hr.inactive')}</Badge></td>
      <td onClick={(event) => event.stopPropagation()}><div className="hr-request-actions">
        <button onClick={() => setEditing(item)} aria-label={t('hr.dept.editItem', { name: item.name })}><Pencil size={14} /></button>
        <button onClick={() => void setActive(item, !item.is_active)} disabled={update.isPending} aria-label={item.is_active ? t('hr.dept.deactivateItem', { name: item.name }) : t('hr.dept.activateItem', { name: item.name })} title={item.is_active ? t('hr.workerActions.deactivate') : t('hr.workerActions.activate')}>{item.is_active ? <Archive size={14} /> : <ArchiveRestore size={14} />}</button>
        <button onClick={() => void destroy(item)} disabled={remove.isPending || item.employee_count > 0} aria-label={t('hr.dept.deleteItem', { name: item.name })} title={item.employee_count > 0 ? t('hr.dept.cannotDelete') : t('hr.delete')}><Trash2 size={14} /></button>
      </div></td>
    </tr>)}</tbody></table>{!rows.length && <div className="hr-empty">{t('hr.dept.empty')}</div>}</div>
    {editing && <DepartmentFormModal department={editing === 'new' ? null : editing} employees={employees} onClose={() => setEditing(null)} />}
  </Card>
}

function DepartmentFormModal({ department, employees, onClose }: { department: HRDepartment | null; employees: HREmployee[]; onClose: () => void }) {
  const { t } = useTranslation()
  const create = useCreateHRDepartment(); const update = useUpdateHRDepartment()
  const [form, setForm] = useState({ name: department?.name || '', code: department?.code || '', description: department?.description || '', manager_employee_id: department?.manager_employee_id ? String(department.manager_employee_id) : '' })
  const codeInvalid = form.code.trim() !== '' && !/^[A-Za-z0-9_-]+$/.test(form.code.trim())
  const submit = async () => {
    const payload = { name: form.name.trim(), description: form.description.trim() || null, manager_employee_id: form.manager_employee_id ? Number(form.manager_employee_id) : null }
    try {
      if (department) await update.mutateAsync({ id: department.id, ...payload, ...(form.code.trim() ? { code: form.code.trim() } : {}) })
      else await create.mutateAsync({ ...payload, code: form.code.trim() || null })
      toast.success(department ? t('hr.dept.updated') : t('hr.dept.added')); onClose()
    } catch (error) { toast.error(errorText(error)) }
  }
  return <Modal title={department ? t('hr.dept.editTitle') : t('hr.dept.add')} onClose={onClose}>
    <div className="hr-form-grid">
      <Input label={t('hr.name')} value={form.name} onChange={(value) => setForm({ ...form, name: value })} placeholder={t('hr.dept.namePlaceholder')} fullWidth />
      <div><Input label={department ? t('hr.dept.code') : t('hr.dept.codeHint')} value={form.code} onChange={(value) => setForm({ ...form, code: value })} placeholder={t('hr.dept.codePlaceholder')} fullWidth />{codeInvalid && <p className="hr-field-error">{t('hr.dept.codeRules')} '_'</p>}</div>
      <Select label={t('hr.dept.manager')} value={form.manager_employee_id} onChange={(value) => setForm({ ...form, manager_employee_id: value })} options={[{ value: '', label: t('hr.notSelected') }, ...employees.filter((item) => item.is_active && !item.is_archived).map((item) => ({ value: String(item.id), label: item.name }))]} fullWidth />
      <Input label={t('hr.description')} value={form.description} onChange={(value) => setForm({ ...form, description: value })} fullWidth />
    </div>
    <div className="hr-modal-actions"><Btn onClick={onClose}>{t('hr.cancelAlt')}</Btn><Btn variant="primary" onClick={submit} disabled={!form.name.trim() || codeInvalid || create.isPending || update.isPending}><Check size={14} />{t('hr.save')}</Btn></div>
  </Modal>
}

const payTypeLabel = (value?: string | null) => (value === 'unpaid' ? i18n.t('hr.leave.unpaidLeave') : i18n.t('hr.leave.paidLeave'))

function LeavePanel({ isHR, isManager, balances, requests, employees }: { isHR: boolean; isManager: boolean; balances: any[]; requests: any[]; employees: HREmployee[] }) {
  const { t } = useTranslation()
  const submit = useSubmitHRLeave(); const decide = useDecideHRLeave(); const update = useUpdateHRLeave(); const setBalance = useSetHRLeaveBalance(); const [form, setForm] = useState({ employee_id: '', leave_type: 'annual', pay_type: 'paid', starts_on: '', ends_on: '', reason: '' }); const [editing, setEditing] = useState<HRLeaveRequest | null>(null); const [editForm, setEditForm] = useState({ leave_type: 'annual' as HRLeaveRequest['leave_type'], pay_type: 'paid' as 'paid' | 'unpaid', starts_on: '', ends_on: '', reason: '', status: 'approved' as 'approved' | 'rejected' }); const [balanceForm, setBalanceForm] = useState({ employee_id: '', year: String(new Date().getFullYear()), leave_type: 'annual', entitled_days: '', carried_days: '0', adjustment_days: '0' })
  const balanceEmployeeId = Number(balanceForm.employee_id) || 0
  const ownBalances = balances.filter((item) => item.employee_id === (isHR ? balanceEmployeeId : balances[0]?.employee_id))
  const send = async () => { try { await submit.mutateAsync({ ...form, employee_id: form.employee_id ? Number(form.employee_id) : undefined }); toast.success(t('hr.leave.sent')); setForm({ employee_id: '', leave_type: 'annual', pay_type: 'paid', starts_on: '', ends_on: '', reason: '' }) } catch (error) { toast.error(errorText(error)) } }
  const startEdit = (item: HRLeaveRequest) => { setEditing(item); setEditForm({ leave_type: item.leave_type, pay_type: item.approved_pay_type || item.requested_pay_type, starts_on: item.starts_on, ends_on: item.ends_on, reason: item.reason || '', status: 'approved' }) }
  const saveEdit = async () => { if (!editing || !editForm.starts_on || !editForm.ends_on || !editForm.reason.trim()) return; try { const status = editing.status === 'approved' && isHR ? editForm.status : undefined; await update.mutateAsync({ id: editing.id, leave_type: editForm.leave_type, pay_type: editForm.pay_type, starts_on: editForm.starts_on, ends_on: editForm.ends_on, reason: editForm.reason, ...(status ? { status } : {}), version: editing.version }); toast.success(status === 'rejected' ? t('hr.leave.rejected') : t('hr.leave.updated')); setEditing(null) } catch (error) { toast.error(errorText(error)) } }
  const saveBalance = async () => { if (!balanceEmployeeId || !balanceForm.year || balanceForm.entitled_days === '') return; try { await setBalance.mutateAsync({ employeeId: balanceEmployeeId, year: Number(balanceForm.year), leave_type: balanceForm.leave_type as 'annual' | 'sick' | 'unpaid', entitled_days: balanceForm.entitled_days, carried_days: balanceForm.carried_days || '0', adjustment_days: balanceForm.adjustment_days || '0' }); toast.success(t('hr.leave.balanceSaved')) } catch (error) { toast.error(errorText(error)) } }
  return <div className="hr-panel-grid"><Card><div className="view-toolbar"><div><span className="eyebrow">{t('hr.leave.eyebrow')}</span><h2>{t('hr.leave.request')}</h2></div><CalendarDays size={19} /></div><div className="hr-balance-grid">{ownBalances.map((item) => <div key={item.leave_type}><small>{item.leave_type}</small><strong>{item.available_days}</strong><span>{t('hr.leave.availableDays')}</span></div>)}</div><div className="hr-form-grid">{isHR && <Select label={t('hr.dir.employee')} value={form.employee_id} onChange={(value) => setForm({ ...form, employee_id: value })} options={[{ value: '', label: t('hr.leave.ownName') }, ...employees.map((item) => ({ value: String(item.id), label: item.name }))]} fullWidth />}<Select label={t('hr.leave.type')} value={form.leave_type} onChange={(value) => setForm({ ...form, leave_type: value })} options={[{ value: 'annual', label: t('hr.leave.type.annual') }, { value: 'sick', label: t('hr.leave.type.sick') }, { value: 'unpaid', label: t('hr.leave.type.unpaid') }]} fullWidth /><Select label={t('hr.leave.pay')} value={form.pay_type} onChange={(value) => setForm({ ...form, pay_type: value })} options={[{ value: 'paid', label: t('hr.leave.paidLeave') }, { value: 'unpaid', label: t('hr.leave.unpaidLeave') }]} fullWidth /><Input label={t('hr.leave.from')} type="date" value={form.starts_on} onChange={(value) => setForm({ ...form, starts_on: value })} fullWidth /><Input label={t('hr.leave.to')} type="date" value={form.ends_on} onChange={(value) => setForm({ ...form, ends_on: value })} fullWidth /><Input label={t('hr.leave.reason')} value={form.reason} onChange={(value) => setForm({ ...form, reason: value })} fullWidth /></div><Btn variant="primary" onClick={send} disabled={!form.starts_on || !form.ends_on || !form.reason || submit.isPending}><Check size={14} />{t('hr.leave.send')}</Btn></Card><Card><div className="view-toolbar"><div><span className="eyebrow">{t('hr.leave.requestsEyebrow')}</span><h2>{isManager ? t('hr.leave.queue') : t('hr.leave.mine')}</h2></div><Users size={19} /></div><div className="hr-request-list">{requests.map((item: HRLeaveRequest) => <article key={item.id}><div><strong>{item.employee_name}</strong><span>{item.leave_type} · {payTypeLabel(item.approved_pay_type || item.requested_pay_type)}{item.status === 'pending' && item.requested_pay_type ? t('hr.leave.requestedSuffix') : ''} · {item.starts_on} – {item.ends_on} · {item.reason}</span></div><div className="hr-request-actions"><Badge color={item.status === 'approved' ? 'green' : item.status === 'rejected' ? 'red' : 'yellow'}>{item.status}</Badge>{(item.status === 'pending' || (isHR && item.status === 'approved')) && <button onClick={() => startEdit(item)} aria-label={t('hr.leave.edit')}><Pencil size={15} /></button>}{isManager && item.status === 'pending' && <>{isHR ? <><button onClick={() => decide.mutate({ id: item.id, approve: true, pay_type: 'paid', version: item.version })} aria-label={t('hr.leave.approvePaid')} title={t('hr.leave.approvePaid')}><Check size={15} /><small>{t('hr.leave.paid')}</small></button><button onClick={() => decide.mutate({ id: item.id, approve: true, pay_type: 'unpaid', version: item.version })} aria-label={t('hr.leave.approveUnpaid')} title={t('hr.leave.approveUnpaid')}><Check size={15} /><small>{t('hr.leave.type.unpaid')}</small></button></> : <button onClick={() => decide.mutate({ id: item.id, approve: true, version: item.version })} aria-label={t('hr.leave.approve')}><Check size={15} /></button>}<button onClick={() => { const feedback = window.prompt(t('hr.leave.rejectReason')); if (feedback) decide.mutate({ id: item.id, approve: false, feedback, version: item.version }) }} aria-label={t('hr.leave.reject')}><X size={15} /></button></>}</div></article>)}</div></Card>{isHR && <Card><div className="view-toolbar"><div><span className="eyebrow">{t('hr.leave.balanceEyebrow')}</span><h2>{t('hr.leave.balanceTitle')}</h2><p>{t('hr.leave.balanceHint')}</p></div><CalendarDays size={19} /></div><div className="hr-form-grid"><Select label={t('hr.dir.employee')} value={balanceForm.employee_id} onChange={(value) => setBalanceForm({ ...balanceForm, employee_id: value })} options={[{ value: '', label: t('hr.leave.pickEmployee') }, ...employees.map((item) => ({ value: String(item.id), label: item.name }))]} fullWidth /><Input label={t('hr.leave.year')} type="number" min="2000" max="2200" value={balanceForm.year} onChange={(value) => setBalanceForm({ ...balanceForm, year: value })} fullWidth /><Select label={t('hr.leave.type')} value={balanceForm.leave_type} onChange={(value) => setBalanceForm({ ...balanceForm, leave_type: value })} options={[{ value: 'annual', label: t('hr.leave.type.annual') }, { value: 'sick', label: t('hr.leave.type.sick') }, { value: 'unpaid', label: t('hr.leave.type.unpaid') }]} fullWidth /><Input label={t('hr.leave.entitlement')} type="number" min="0" max="366" value={balanceForm.entitled_days} onChange={(value) => setBalanceForm({ ...balanceForm, entitled_days: value })} placeholder="15" fullWidth /><Input label={t('hr.leave.carried')} type="number" min="0" max="366" value={balanceForm.carried_days} onChange={(value) => setBalanceForm({ ...balanceForm, carried_days: value })} fullWidth /><Input label={t('hr.leave.adjustment')} type="number" min="-366" max="366" value={balanceForm.adjustment_days} onChange={(value) => setBalanceForm({ ...balanceForm, adjustment_days: value })} fullWidth /></div><Btn variant="primary" onClick={saveBalance} disabled={!balanceEmployeeId || balanceForm.entitled_days === '' || setBalance.isPending}><Check size={14} />{t('hr.leave.balanceSave')}</Btn></Card>}{editing && <Modal title={t('hr.leave.edit')} onClose={() => setEditing(null)}><div className="hr-form-grid">{isHR && editing.status === 'approved' && <Select label={t('hr.status')} value={editForm.status} onChange={(value) => setEditForm({ ...editForm, status: value as 'approved' | 'rejected' })} options={[{ value: 'approved', label: t('reports.detail.status.approved') }, { value: 'rejected', label: t('hr.leave.status.rejected') }]} fullWidth />}<Select label={t('hr.leave.type')} value={editForm.leave_type} onChange={(value) => setEditForm({ ...editForm, leave_type: value as HRLeaveRequest['leave_type'] })} options={[{ value: 'annual', label: t('hr.leave.type.annual') }, { value: 'sick', label: t('hr.leave.type.sick') }, { value: 'unpaid', label: t('hr.leave.type.unpaid') }]} fullWidth /><Select label={t('hr.leave.pay')} value={editForm.pay_type} onChange={(value) => setEditForm({ ...editForm, pay_type: value as 'paid' | 'unpaid' })} options={[{ value: 'paid', label: t('hr.leave.paidLeave') }, { value: 'unpaid', label: t('hr.leave.unpaidLeave') }]} fullWidth /><Input label={t('hr.leave.from')} type="date" value={editForm.starts_on} onChange={(value) => setEditForm({ ...editForm, starts_on: value })} fullWidth /><Input label={t('hr.leave.to')} type="date" value={editForm.ends_on} onChange={(value) => setEditForm({ ...editForm, ends_on: value })} fullWidth /><Input label={t('hr.leave.reason')} value={editForm.reason} onChange={(value) => setEditForm({ ...editForm, reason: value })} fullWidth /></div><div className="hr-modal-actions"><Btn onClick={() => setEditing(null)}>{t('hr.cancelAlt')}</Btn><Btn variant="primary" onClick={saveEdit} disabled={!editForm.starts_on || !editForm.ends_on || !editForm.reason.trim() || update.isPending}><Check size={14} />{t('hr.save')}</Btn></div></Modal>}</div>
}

function PayrollPanel({ onGoEmployees }: { onGoEmployees: () => void }) {
  const { t } = useTranslation()
  return <div className="hr-panel-grid"><Card><div className="view-toolbar"><div><span className="eyebrow">{t('hr.payroll.eyebrow')}</span><h2>{t('hr.payroll.title')}</h2><p>{t('hr.payroll.hint')}</p></div></div><Link className="primary-action" to="/erp/payroll"><Plus size={14} />{t('hr.payroll.open')}</Link></Card><Card><div className="view-toolbar"><div><span className="eyebrow">{t('hr.payroll.setupEyebrow')}</span><h2>{t('hr.payroll.editTitle')}</h2><p>{t('hr.payroll.editHint')}</p></div></div><button className="secondary-action" onClick={onGoEmployees}>{t('hr.payroll.toDirectory')}</button></Card></div>
}

export default HRWorkspacePage
