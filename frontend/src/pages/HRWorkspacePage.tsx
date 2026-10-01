import { useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import toast from 'react-hot-toast'
import { Archive, ArchiveRestore, Building2, CalendarDays, Check, Copy, Link2, Pencil, Plus, Search, Trash2, UserPlus, Users, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useHREmployeeRoles, useSetHREmployeeRoles, useActor, useArchiveHREmployee, useCreateHRDepartment, useCreateHREmployee, useDecideHRLeave, useDeleteHRDepartment, useDeleteHREmployeePermanently, useHRDepartments, useHREmployees, useHRLeaveBalances, useHRLeaveRequests, useSetHRLeaveBalance, useSubmitHRLeave, useUpdateHRDepartment, useUpdateHREmployee, useUpdateHRLeave } from '../api/enterprise'
import type { HRDepartment, HREmployee, HREmploymentStatus, HREmploymentType, HRLeaveRequest } from '../api/enterprise'
import { Badge, Btn, Card, Input, Modal, Select } from '../components/ui'
import { WorkerActionsMenu } from '../components/WorkerActionsMenu'
import { SeatLimitNotice } from '../components/SeatLimitNotice'
import { MonthlyPayrollProfileDrawer } from '../components/MonthlyPayrollProfileDrawer'
import { EmployeeWorktimeStats } from '../components/EmployeeWorktimeStats'
import { AttendanceGrid } from '../components/attendance/AttendanceGrid'
import { normalizeRegistrationNumber, parseRegistrationNumber } from '../utils/registrationNumber'
import { TELEGRAM_BOT_REQUIRED_HINT, useTenantContext } from '../api/tenancy'
import { CreateButton } from '../components/CreateButton'

type Tab = 'directory' | 'departments' | 'leave' | 'attendance' | 'payroll'
const errorText = (error: any) => {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((item) => String(item?.msg || '').replace(/^Value error, /, '')).filter(Boolean).join('; ') || 'Мэдээлэл буруу байна'
  if (detail && typeof detail === 'object') {
    if (typeof detail.message === 'string') return detail.message
    if (detail.code === 'leave_balance_insufficient') return `Үлдэгдэл хүрэлцэхгүй байна. Боломжит өдөр: ${detail.available_days ?? 0}`
  }
  return 'Үйлдэл амжилтгүй боллоо'
}

export const EMPLOYMENT_STATUS_LABELS: Record<HREmploymentStatus, string> = { active: 'Идэвхтэй', probation: 'Туршилтын хугацаа', on_leave: 'Урт хугацааны чөлөө', suspended: 'Түдгэлзүүлсэн', inactive: 'Идэвхгүй', terminated: 'Ажлаас гарсан' }
const STATUS_COLORS: Record<HREmploymentStatus, 'green' | 'blue' | 'purple' | 'yellow' | 'muted' | 'red'> = { active: 'green', probation: 'blue', on_leave: 'purple', suspended: 'yellow', inactive: 'muted', terminated: 'red' }
const EMPLOYMENT_TYPE_LABELS: Record<HREmploymentType, string> = { full_time: 'Үндсэн (бүтэн цаг)', part_time: 'Хагас цаг', contract: 'Гэрээт', intern: 'Дадлагажигч' }
const GENDER_LABELS = { male: 'Эрэгтэй', female: 'Эмэгтэй' } as const
const WORKING_STATUSES: HREmploymentStatus[] = ['active', 'probation']
const statusOptions = (statuses: HREmploymentStatus[]) => statuses.map((value) => ({ value, label: EMPLOYMENT_STATUS_LABELS[value] }))

function StatusBadge({ employee }: { employee: HREmployee }) {
  if (employee.is_archived) return <Badge color="muted">Архивласан</Badge>
  const status = employee.employment_status in EMPLOYMENT_STATUS_LABELS ? employee.employment_status : employee.is_active ? 'active' : 'inactive'
  return <Badge color={STATUS_COLORS[status]}>{EMPLOYMENT_STATUS_LABELS[status]}</Badge>
}

export function HRWorkspacePage() {
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
  const navLabels: Record<Tab, string> = { directory: 'Ажилтны лавлах', departments: 'Хэлтэс', leave: 'Чөлөө', attendance: 'Ирц', payroll: 'Цалин' }
  return <div className="hr-workspace">
    <div className="page-tabs">
      <nav className="page-tabs-list" aria-label="HR sections">{visibleTabs.map((item) => <button key={item} className={tab === item ? 'active' : ''} onClick={() => setTab(item)}>{navLabels[item]}</button>)}</nav>
      {isHR && <div className="page-tabs-actions"><CreateButton label="Ажилтан нэмэх" icon={<UserPlus size={16} />} onClick={() => setEditing('new')} /></div>}
    </div>
    {tab === 'directory' && <Directory employees={employees.data?.items || []} departments={departments.data || []} search={search} setSearch={setSearch} department={department} setDepartment={setDepartment} statusFilter={statusFilter} setStatusFilter={setStatusFilter} includeArchived={includeArchived} setIncludeArchived={setIncludeArchived} canEdit={isHR} onSelect={setSelected} onEdit={setEditing} />}
    {tab === 'departments' && isHR && <DepartmentsPanel departments={departments.data || []} employees={allEmployees.data?.items || []} />}
    {tab === 'leave' && <LeavePanel isHR={isHR} isManager={isManager} balances={balances.data || []} requests={leave.data || []} employees={employees.data?.items || []} />}
    {tab === 'attendance' && <Card className="hr-attendance-card"><AttendanceGrid canEdit={isManager} onOpenLeave={() => setTab('leave')} /></Card>}
    {tab === 'payroll' && isHR && <PayrollPanel onGoEmployees={() => setTab('directory')} />}
    {selected && <EmployeeDrawer employee={selected} isHR={isHR} canSeeStats={isManager} onClose={() => setSelected(null)} onEdit={() => { setEditing(selected); setSelected(null) }} />}
    {editing && <WorkerFormModal employee={editing === 'new' ? null : editing} departments={departments.data || []} employees={allEmployees.data?.items || []} onClose={() => setEditing(null)} onCreated={(url) => { setEditing(null); if (url) setInvite(url); else toast.success('Ажилтан нэмэгдлээ') }} />}
    {invite && <Modal title="Telegram урилга бэлэн" onClose={() => setInvite(null)}><div className="hr-invite-result"><p>Энэ холбоосыг ажилтанд илгээнэ үү. Нэг удаа ашиглагдана.</p><code>{invite}</code><div><Btn variant="primary" onClick={() => { void navigator.clipboard?.writeText(invite); toast.success('Хууллаа') }}><Copy size={14} />Хуулах</Btn><a className="secondary-action" href={invite} target="_blank" rel="noreferrer"><Link2 size={14} />Нээх</a></div></div></Modal>}
  </div>
}

function Directory({ employees, departments, search, setSearch, department, setDepartment, statusFilter, setStatusFilter, includeArchived, setIncludeArchived, canEdit, onSelect, onEdit }: { employees: HREmployee[]; departments: HRDepartment[]; search: string; setSearch: (value: string) => void; department: string; setDepartment: (value: string) => void; statusFilter: string; setStatusFilter: (value: string) => void; includeArchived: boolean; setIncludeArchived: (value: boolean) => void; canEdit: boolean; onSelect: (employee: HREmployee) => void; onEdit: (employee: HREmployee) => void }) {
  const [openMenuId, setOpenMenuId] = useState<number | null>(null)
  const update = useUpdateHREmployee()
  const archive = useArchiveHREmployee()
  const removeForever = useDeleteHREmployeePermanently()
  const run = (promise: Promise<unknown>, message: string) => promise.then(() => toast.success(message)).catch((error) => toast.error(errorText(error)))
  // "active"/"inactive" are server-side groups (working vs. not); the rest match one status.
  const statusFilterOptions = [{ value: '', label: 'Бүх төлөв' }, { value: 'active', label: 'Ажиллаж буй (бүгд)' }, { value: 'inactive', label: 'Ажиллахгүй буй (бүгд)' }, ...statusOptions(['probation', 'on_leave', 'suspended', 'terminated'])]
  return <Card className="hr-directory-card">
    <div className="hr-toolbar hr-directory-toolbar">
      <label className="hr-search"><Search size={15} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={canEdit ? 'Нэр, РД, утас, албан тушаалаар хайх…' : 'Нэр, username, албан тушаалаар хайх…'} /></label>
      <Select value={department} onChange={setDepartment} options={[{ value: '', label: 'Бүх хэлтэс' }, ...departments.map((item) => ({ value: String(item.id), label: item.is_active ? item.name : `${item.name} (идэвхгүй)` }))]} />
      <Select value={statusFilter} onChange={setStatusFilter} options={statusFilterOptions} />
      {canEdit && <label className="employee-archive-toggle"><input type="checkbox" checked={includeArchived} onChange={(event) => setIncludeArchived(event.target.checked)} />Архивласан</label>}
    </div>
    <div className="hr-directory-table"><table><thead><tr><th>Ажилтан</th><th>Албан тушаал</th><th>Хэлтэс</th><th>Telegram</th><th>Төлөв</th>{canEdit && <th />}</tr></thead><tbody>{employees.map((employee) => <tr key={employee.id} onClick={() => onSelect(employee)}>
      <td><div className="hr-person"><span>{(employee.first_name || employee.name || '?')[0]}</span><strong>{employee.name}</strong></div></td>
      <td>{employee.job_title || employee.employment_role || '—'}</td>
      <td>{employee.department_name || 'Тодорхойгүй'}</td>
      <td>{employee.telegram_status === 'connected' ? <Badge color="green">Connected</Badge> : employee.telegram_status === 'pending_invite' ? <Badge color="yellow">Pending invite</Badge> : <Badge color="muted">Not invited</Badge>}</td>
      <td><StatusBadge employee={employee} /></td>
      {canEdit && <td onClick={(event) => event.stopPropagation()}><WorkerActionsMenu
        worker={{ ...employee, deleted_at: employee.is_archived ? 'archived' : null }}
        open={openMenuId === employee.id}
        onOpen={() => setOpenMenuId(openMenuId === employee.id ? null : employee.id)}
        onEdit={() => { setOpenMenuId(null); onEdit(employee) }}
        onDelete={() => { setOpenMenuId(null); if (window.confirm(`${employee.name}-ийг архивлах уу? Нэвтрэх эрх нь хаагдана, түүх хадгалагдана.`)) void run(archive.mutateAsync(employee.id), 'Архивлалаа') }}
        onSetActive={(active) => { setOpenMenuId(null); void run(update.mutateAsync({ id: employee.id, is_active: active, restore: active && employee.is_archived }), active ? 'Идэвхжүүллээ' : 'Идэвхгүй болголоо') }}
        onPermanentDelete={() => { setOpenMenuId(null); if (window.confirm(`${employee.name}-ийг бүр мөсөн устгах уу? Энэ үйлдлийг буцаах боломжгүй. Ажлын түүхтэй ажилтныг устгах боломжгүй.`)) void run(removeForever.mutateAsync(employee.id), 'Бүр мөсөн устгалаа') }}
      /></td>}
    </tr>)}</tbody></table>{!employees.length && <div className="hr-empty">Ажилтан олдсонгүй</div>}</div>
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
  const departmentOptions = [{ value: '', label: 'Сонгоогүй' }, ...departments.filter((item) => item.is_active || String(item.id) === form.department_id).map((item) => ({ value: String(item.id), label: item.name }))]
  const managerOptions = [{ value: '', label: 'Сонгоогүй' }, ...employees.filter((item) => item.id !== employee?.id && item.is_active && !item.is_archived).map((item) => ({ value: String(item.id), label: item.name }))]
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
        toast.success('Ажилтны мэдээлэл хадгалагдлаа'); onClose()
      } else {
        const result = await create.mutateAsync({ ...values, telegram_id: botConnected ? form.telegram_id.trim() || null : null, annual_leave_days: form.annual_leave_days ? Number(form.annual_leave_days) : null })
        if (result.seat_warning) toast(result.seat_warning, { icon: '⚠️', duration: 8000 })
        onCreated(result.invite?.deep_link ?? null)
      }
    } catch (error) { toast.error(errorText(error)) }
  }
  return <Modal title={employee ? `${employee.name} — засах` : 'Ажилтан нэмэх'} onClose={onClose} className="hr-worker-modal">
    {!employee && <SeatLimitNotice />}
    <h4 className="hr-form-section">Хувийн мэдээлэл</h4>
    <div className="hr-form-grid">
      <Input label="Овог" value={form.last_name} onChange={set('last_name')} fullWidth />
      <Input label="Нэр" value={form.first_name} onChange={set('first_name')} fullWidth />
      <Input label={employee ? 'Харагдах нэр' : 'Харагдах нэр (хоосон бол Нэр Овог)'} value={form.name} onChange={set('name')} fullWidth />
      <div><Input label="Регистрын дугаар" value={form.registration_number} onChange={setRegistration} placeholder="УБ99011512" fullWidth />{registrationInvalid && <p className="hr-field-error">2 кирилл үсэг + 8 оронтой тоо, зөв төрсөн огноотой байх ёстой</p>}</div>
      <Input label="Төрсөн огноо" type="date" value={form.birthday} onChange={set('birthday')} fullWidth />
      <Select label="Хүйс" value={form.gender} onChange={set('gender')} options={[{ value: '', label: 'Сонгоогүй' }, { value: 'male', label: GENDER_LABELS.male }, { value: 'female', label: GENDER_LABELS.female }]} fullWidth />
      <Input label="Утас" type="tel" value={form.phone_number} onChange={set('phone_number')} placeholder="9911 2233" fullWidth />
      <Input label="Имэйл" type="email" value={form.email} onChange={set('email')} fullWidth />
      <div className="hr-form-wide"><Input label="Гэрийн хаяг" value={form.address} onChange={set('address')} fullWidth /></div>
    </div>
    <h4 className="hr-form-section">Ажил эрхлэлт</h4>
    <div className="hr-form-grid">
      <Select label="Хэлтэс" value={form.department_id} onChange={set('department_id')} options={departmentOptions} fullWidth />
      <Select label="Шууд удирдлага" value={form.manager_id} onChange={set('manager_id')} options={managerOptions} fullWidth />
      <Input label="Албан тушаал" value={form.job_title} onChange={set('job_title')} fullWidth />
      <Input label="Ажлын үүрэг / role" value={form.employment_role} onChange={set('employment_role')} fullWidth />
      <Select label="Хөдөлмөрийн төрөл" value={form.employment_type} onChange={set('employment_type')} options={Object.entries(EMPLOYMENT_TYPE_LABELS).map(([value, label]) => ({ value, label }))} fullWidth />
      <Select label="Төлөв" value={form.employment_status} onChange={set('employment_status')} options={statusOptions(employee ? ['active', 'probation', 'on_leave', 'suspended', 'inactive', 'terminated'] : WORKING_STATUSES)} fullWidth />
      <Input label="Ажилд орсон огноо" type="date" value={form.start_date} onChange={set('start_date')} fullWidth />
      {(status === 'probation' || form.probation_end_date) && <Input label="Туршилтын хугацаа дуусах" type="date" value={form.probation_end_date} onChange={set('probation_end_date')} fullWidth />}
      {status === 'terminated' && <><Input label="Ажлаас гарсан огноо (хоосон бол өнөөдөр)" type="date" value={form.end_date} onChange={set('end_date')} fullWidth /><Input label="Гарсан шалтгаан" value={form.termination_reason} onChange={set('termination_reason')} fullWidth /></>}
      {!employee && <><Input label="Жилийн ээлжийн амралт (өдөр)" type="number" min="0" max="366" value={form.annual_leave_days} onChange={set('annual_leave_days')} placeholder="15" fullWidth /><Input label="Telegram ID (заавал биш)" value={botConnected ? form.telegram_id : ''} onChange={set('telegram_id')} placeholder="123456789" fullWidth disabled={!botConnected} hint={botConnected ? undefined : TELEGRAM_BOT_REQUIRED_HINT} /></>}
    </div>
    {employee && !WORKING_STATUSES.includes(status) && WORKING_STATUSES.includes(employee.employment_status) && <p className="hr-form-note">Энэ төлөвт ажилтны нэвтрэх эрх хаагдаж, цалин болон өдөр тутмын асуулгад хамрагдахаа болино.</p>}
    <h4 className="hr-form-section">Яаралтай үед холбоо барих</h4>
    <div className="hr-form-grid">
      <Input label="Холбоо барих хүн" value={form.emergency_contact_name} onChange={set('emergency_contact_name')} placeholder="Нэр, хамаарал" fullWidth />
      <Input label="Утас" type="tel" value={form.emergency_contact_phone} onChange={set('emergency_contact_phone')} fullWidth />
    </div>
    <div className="hr-modal-actions"><Btn onClick={onClose}>Цуцлах</Btn><Btn variant="primary" onClick={submit} disabled={nameMissing || registrationInvalid || pending}>{employee ? <><Check size={14} />Хадгалах</> : <><Plus size={14} />{botConnected ? 'Урилгатай үүсгэх' : 'Үүсгэх'}</>}</Btn></div>
  </Modal>
}

const ROLE_LABELS: Record<string, string> = { member: 'Member', manager: 'Supervisor', team_lead: 'Team lead', hr: 'HR', contractor: 'Contractor', client_auditor: 'Client auditor', legal_counsel: 'Хуульч', admin: 'Admin' }

function EmployeeRolesSection({ employee }: { employee: HREmployee }) {
  const rolesQuery = useHREmployeeRoles(employee.account_id ? employee.id : undefined); const setRoles = useSetHREmployeeRoles()
  const data = rolesQuery.data
  const toggle = async (role: string) => {
    if (!data) return
    const next = data.roles.includes(role) ? data.roles.filter((item) => item !== role) : [...data.roles, role]
    if (!next.length) { toast.error('Хэрэглэгч дор хаяж нэг эрхтэй байна'); return }
    try { await setRoles.mutateAsync({ employeeId: employee.id, roles: next }); toast.success('Эрх шинэчлэгдлээ') } catch (error) { toast.error(errorText(error)) }
  }
  return <section className="hr-drawer-section"><h3>Платформын эрх</h3>{!employee.account_id ? <p>Энэ ажилтанд платформын хэрэглэгч үүсээгүй байна. Эхлээд Administration → Хэрэглэгч хэсгээс акаунт үүсгэнэ.</p> : !data ? <p>Ачаалж байна…</p> : <><fieldset className="role-editor" disabled={data.locked || setRoles.isPending}><legend>Access roles</legend>{data.assignable_roles.map((role) => <label key={role}><input type="checkbox" checked={data.roles.includes(role)} onChange={() => toggle(role)} /><span>{ROLE_LABELS[role] || role}</span></label>)}</fieldset>{data.locked && <p>Admin эрхтэй хэрэглэгчийн эрхийг зөвхөн Administration хэсгээс өөрчилнө.</p>}</>}</section>
}

function EmployeeDrawer({ employee, isHR, canSeeStats, onClose, onEdit }: { employee: HREmployee; isHR: boolean; canSeeStats: boolean; onClose: () => void; onEdit: () => void }) {
  const [showPayrollSettings, setShowPayrollSettings] = useState(false);
  const hasPrivate = isHR || Boolean(employee.registration_number || employee.phone_number || employee.email || employee.birthday)
  // Portaled: the route enter animation leaves a stacking context on the page,
  // which would otherwise trap the fixed drawer under the sticky top navbar.
  return createPortal(<>{!showPayrollSettings && <div className="hr-drawer-backdrop" onClick={onClose}><aside className="hr-drawer" role="dialog" aria-label={`${employee.name} profile`} onClick={(event) => event.stopPropagation()}>
    <header><div><span className="eyebrow">EMPLOYEE PROFILE</span><h2>{employee.name}</h2><p>{employee.telegram_username ? `@${employee.telegram_username.replace(/^@/, '')}` : 'Telegram холбогдоогүй'}</p><div className="hr-drawer-badges"><StatusBadge employee={employee} /></div></div><div className="hr-drawer-header-actions">{isHR && <button onClick={onEdit} aria-label="Засах"><Pencil size={16} /></button>}<button onClick={onClose} aria-label="Хаах"><X size={18} /></button></div></header>
    <section className="hr-drawer-section"><h3>Ажил эрхлэлт</h3><dl>
      <dt>Хэлтэс</dt><dd>{employee.department_name || '—'}</dd>
      <dt>Албан тушаал</dt><dd>{employee.job_title || '—'}</dd>
      <dt>Шууд удирдлага</dt><dd>{employee.manager_name || '—'}</dd>
      <dt>Хөдөлмөрийн төрөл</dt><dd>{EMPLOYMENT_TYPE_LABELS[employee.employment_type] || '—'}</dd>
      <dt>Ажилд орсон</dt><dd>{employee.start_date || '—'}</dd>
      {employee.probation_end_date && <><dt>Туршилт дуусах</dt><dd>{employee.probation_end_date}</dd></>}
      {employee.end_date && <><dt>Ажлаас гарсан</dt><dd>{employee.end_date}</dd></>}
      {employee.termination_reason && <><dt>Гарсан шалтгаан</dt><dd>{employee.termination_reason}</dd></>}
      <dt>Telegram</dt><dd>{employee.telegram_status}</dd>
    </dl></section>
    {hasPrivate && <section className="hr-drawer-section"><h3>Хувийн мэдээлэл</h3><dl>
      <dt>Регистрын дугаар</dt><dd>{employee.registration_number || '—'}</dd>
      <dt>Төрсөн огноо</dt><dd>{employee.birthday || '—'}</dd>
      <dt>Хүйс</dt><dd>{employee.gender ? GENDER_LABELS[employee.gender] : '—'}</dd>
      <dt>Утас</dt><dd>{employee.phone_number || '—'}</dd>
      <dt>Имэйл</dt><dd>{employee.email || '—'}</dd>
      <dt>Хаяг</dt><dd>{employee.address || '—'}</dd>
      <dt>Яаралтай үед</dt><dd>{[employee.emergency_contact_name, employee.emergency_contact_phone].filter(Boolean).join(' · ') || '—'}</dd>
    </dl></section>}
    {isHR && <section className="hr-drawer-section"><h3>Цалингийн тохиргоо</h3><p>Үндсэн цалин, төлбөрийн өдөр болон урьдчилгааны нөхцөлийг тохируулна.</p><button className="secondary-action" onClick={() => setShowPayrollSettings(true)}><Pencil size={14} />Цалингийн тохиргоо нээх</button></section>}
    {canSeeStats && <section className="hr-drawer-section"><EmployeeWorktimeStats employeeId={employee.id} employeeName={employee.name} /></section>}
    {isHR && <EmployeeRolesSection employee={employee} />}
  </aside></div>}{showPayrollSettings && <MonthlyPayrollProfileDrawer employee={{ id: employee.id, name: employee.name }} onClose={() => setShowPayrollSettings(false)} />}</>, document.body)
}

function DepartmentsPanel({ departments, employees }: { departments: HRDepartment[]; employees: HREmployee[] }) {
  const [editing, setEditing] = useState<HRDepartment | 'new' | null>(null)
  const [showArchived, setShowArchived] = useState(false)
  const update = useUpdateHRDepartment(); const remove = useDeleteHRDepartment()
  const names = useMemo(() => new Map(employees.map((item) => [item.id, item.name])), [employees])
  const rows = departments.filter((item) => showArchived || item.is_active)
  const setActive = async (item: HRDepartment, active: boolean) => { try { await update.mutateAsync({ id: item.id, is_active: active }); toast.success(active ? 'Хэлтсийг идэвхжүүллээ' : 'Хэлтсийг идэвхгүй болголоо') } catch (error) { toast.error(errorText(error)) } }
  const destroy = async (item: HRDepartment) => { if (!window.confirm(`"${item.name}" хэлтсийг бүр мөсөн устгах уу?`)) return; try { await remove.mutateAsync(item.id); toast.success('Хэлтэс устгагдлаа') } catch (error) { toast.error(errorText(error)) } }
  return <Card className="hr-directory-card">
    <div className="view-toolbar"><div><span className="eyebrow">DEPARTMENTS</span><h2>Хэлтэс, нэгж</h2><p>Хэлтэс нэмэх, засах, удирдагч оноох. Ажилтантай хэлтсийг устгахын оронд идэвхгүй болгоно.</p></div><div className="hr-inline-actions"><label className="employee-archive-toggle"><input type="checkbox" checked={showArchived} onChange={(event) => setShowArchived(event.target.checked)} />Идэвхгүй</label><CreateButton label="Хэлтэс нэмэх" onClick={() => setEditing('new')} /></div></div>
    <div className="hr-directory-table"><table><thead><tr><th>Нэр</th><th>Код</th><th>Удирдагч</th><th>Ажилтан</th><th>Төлөв</th><th /></tr></thead><tbody>{rows.map((item) => <tr key={item.id} onClick={() => setEditing(item)}>
      <td><div className="hr-person"><span><Building2 size={14} /></span><div className="hr-department-name"><strong>{item.name}</strong>{item.description && <small>{item.description}</small>}</div></div></td>
      <td>{item.code}</td>
      <td>{item.manager_employee_id ? names.get(item.manager_employee_id) || `#${item.manager_employee_id}` : '—'}</td>
      <td>{item.employee_count}</td>
      <td><Badge color={item.is_active ? 'green' : 'muted'}>{item.is_active ? 'Идэвхтэй' : 'Идэвхгүй'}</Badge></td>
      <td onClick={(event) => event.stopPropagation()}><div className="hr-request-actions">
        <button onClick={() => setEditing(item)} aria-label={`${item.name} засах`}><Pencil size={14} /></button>
        <button onClick={() => void setActive(item, !item.is_active)} disabled={update.isPending} aria-label={item.is_active ? `${item.name} идэвхгүй болгох` : `${item.name} идэвхжүүлэх`} title={item.is_active ? 'Идэвхгүй болгох' : 'Идэвхжүүлэх'}>{item.is_active ? <Archive size={14} /> : <ArchiveRestore size={14} />}</button>
        <button onClick={() => void destroy(item)} disabled={remove.isPending || item.employee_count > 0} aria-label={`${item.name} устгах`} title={item.employee_count > 0 ? 'Ажилтантай хэлтсийг устгах боломжгүй' : 'Устгах'}><Trash2 size={14} /></button>
      </div></td>
    </tr>)}</tbody></table>{!rows.length && <div className="hr-empty">Хэлтэс бүртгэгдээгүй байна</div>}</div>
    {editing && <DepartmentFormModal department={editing === 'new' ? null : editing} employees={employees} onClose={() => setEditing(null)} />}
  </Card>
}

function DepartmentFormModal({ department, employees, onClose }: { department: HRDepartment | null; employees: HREmployee[]; onClose: () => void }) {
  const create = useCreateHRDepartment(); const update = useUpdateHRDepartment()
  const [form, setForm] = useState({ name: department?.name || '', code: department?.code || '', description: department?.description || '', manager_employee_id: department?.manager_employee_id ? String(department.manager_employee_id) : '' })
  const codeInvalid = form.code.trim() !== '' && !/^[A-Za-z0-9_-]+$/.test(form.code.trim())
  const submit = async () => {
    const payload = { name: form.name.trim(), description: form.description.trim() || null, manager_employee_id: form.manager_employee_id ? Number(form.manager_employee_id) : null }
    try {
      if (department) await update.mutateAsync({ id: department.id, ...payload, ...(form.code.trim() ? { code: form.code.trim() } : {}) })
      else await create.mutateAsync({ ...payload, code: form.code.trim() || null })
      toast.success(department ? 'Хэлтэс шинэчлэгдлээ' : 'Хэлтэс нэмэгдлээ'); onClose()
    } catch (error) { toast.error(errorText(error)) }
  }
  return <Modal title={department ? 'Хэлтэс засах' : 'Хэлтэс нэмэх'} onClose={onClose}>
    <div className="hr-form-grid">
      <Input label="Нэр" value={form.name} onChange={(value) => setForm({ ...form, name: value })} placeholder="Санхүүгийн хэлтэс" fullWidth />
      <div><Input label={department ? 'Код' : 'Код (хоосон бол автоматаар)'} value={form.code} onChange={(value) => setForm({ ...form, code: value })} placeholder="FIN" fullWidth />{codeInvalid && <p className="hr-field-error">Зөвхөн латин үсэг, тоо, '-' болон '_'</p>}</div>
      <Select label="Удирдагч" value={form.manager_employee_id} onChange={(value) => setForm({ ...form, manager_employee_id: value })} options={[{ value: '', label: 'Сонгоогүй' }, ...employees.filter((item) => item.is_active && !item.is_archived).map((item) => ({ value: String(item.id), label: item.name }))]} fullWidth />
      <Input label="Тайлбар" value={form.description} onChange={(value) => setForm({ ...form, description: value })} fullWidth />
    </div>
    <div className="hr-modal-actions"><Btn onClick={onClose}>Цуцлах</Btn><Btn variant="primary" onClick={submit} disabled={!form.name.trim() || codeInvalid || create.isPending || update.isPending}><Check size={14} />Хадгалах</Btn></div>
  </Modal>
}

const payTypeLabel = (value?: string | null) => (value === 'unpaid' ? 'Цалингүй чөлөө' : 'Цалинтай чөлөө')

function LeavePanel({ isHR, isManager, balances, requests, employees }: { isHR: boolean; isManager: boolean; balances: any[]; requests: any[]; employees: HREmployee[] }) {
  const submit = useSubmitHRLeave(); const decide = useDecideHRLeave(); const update = useUpdateHRLeave(); const setBalance = useSetHRLeaveBalance(); const [form, setForm] = useState({ employee_id: '', leave_type: 'annual', pay_type: 'paid', starts_on: '', ends_on: '', reason: '' }); const [editing, setEditing] = useState<HRLeaveRequest | null>(null); const [editForm, setEditForm] = useState({ leave_type: 'annual' as HRLeaveRequest['leave_type'], pay_type: 'paid' as 'paid' | 'unpaid', starts_on: '', ends_on: '', reason: '', status: 'approved' as 'approved' | 'rejected' }); const [balanceForm, setBalanceForm] = useState({ employee_id: '', year: String(new Date().getFullYear()), leave_type: 'annual', entitled_days: '', carried_days: '0', adjustment_days: '0' })
  const balanceEmployeeId = Number(balanceForm.employee_id) || 0
  const ownBalances = balances.filter((item) => item.employee_id === (isHR ? balanceEmployeeId : balances[0]?.employee_id))
  const send = async () => { try { await submit.mutateAsync({ ...form, employee_id: form.employee_id ? Number(form.employee_id) : undefined }); toast.success('Чөлөөний хүсэлт илгээгдлээ'); setForm({ employee_id: '', leave_type: 'annual', pay_type: 'paid', starts_on: '', ends_on: '', reason: '' }) } catch (error) { toast.error(errorText(error)) } }
  const startEdit = (item: HRLeaveRequest) => { setEditing(item); setEditForm({ leave_type: item.leave_type, pay_type: item.approved_pay_type || item.requested_pay_type, starts_on: item.starts_on, ends_on: item.ends_on, reason: item.reason || '', status: 'approved' }) }
  const saveEdit = async () => { if (!editing || !editForm.starts_on || !editForm.ends_on || !editForm.reason.trim()) return; try { const status = editing.status === 'approved' && isHR ? editForm.status : undefined; await update.mutateAsync({ id: editing.id, leave_type: editForm.leave_type, pay_type: editForm.pay_type, starts_on: editForm.starts_on, ends_on: editForm.ends_on, reason: editForm.reason, ...(status ? { status } : {}), version: editing.version }); toast.success(status === 'rejected' ? 'Чөлөөний хүсэлт татгалзагдлаа' : 'Чөлөөний хүсэлт шинэчлэгдлээ'); setEditing(null) } catch (error) { toast.error(errorText(error)) } }
  const saveBalance = async () => { if (!balanceEmployeeId || !balanceForm.year || balanceForm.entitled_days === '') return; try { await setBalance.mutateAsync({ employeeId: balanceEmployeeId, year: Number(balanceForm.year), leave_type: balanceForm.leave_type as 'annual' | 'sick' | 'unpaid', entitled_days: balanceForm.entitled_days, carried_days: balanceForm.carried_days || '0', adjustment_days: balanceForm.adjustment_days || '0' }); toast.success('Чөлөөний баланс хадгалагдлаа') } catch (error) { toast.error(errorText(error)) } }
  return <div className="hr-panel-grid"><Card><div className="view-toolbar"><div><span className="eyebrow">TIME OFF</span><h2>Чөлөө хүсэх</h2></div><CalendarDays size={19} /></div><div className="hr-balance-grid">{ownBalances.map((item) => <div key={item.leave_type}><small>{item.leave_type}</small><strong>{item.available_days}</strong><span>боломжтой өдөр</span></div>)}</div><div className="hr-form-grid">{isHR && <Select label="Ажилтан" value={form.employee_id} onChange={(value) => setForm({ ...form, employee_id: value })} options={[{ value: '', label: 'Өөрийн нэр' }, ...employees.map((item) => ({ value: String(item.id), label: item.name }))]} fullWidth />}<Select label="Төрөл" value={form.leave_type} onChange={(value) => setForm({ ...form, leave_type: value })} options={[{ value: 'annual', label: 'Ээлжийн' }, { value: 'sick', label: 'Өвчтэй' }, { value: 'unpaid', label: 'Цалингүй' }]} fullWidth /><Select label="Цалин" value={form.pay_type} onChange={(value) => setForm({ ...form, pay_type: value })} options={[{ value: 'paid', label: 'Цалинтай чөлөө' }, { value: 'unpaid', label: 'Цалингүй чөлөө' }]} fullWidth /><Input label="Эхлэх" type="date" value={form.starts_on} onChange={(value) => setForm({ ...form, starts_on: value })} fullWidth /><Input label="Дуусах" type="date" value={form.ends_on} onChange={(value) => setForm({ ...form, ends_on: value })} fullWidth /><Input label="Шалтгаан" value={form.reason} onChange={(value) => setForm({ ...form, reason: value })} fullWidth /></div><Btn variant="primary" onClick={send} disabled={!form.starts_on || !form.ends_on || !form.reason || submit.isPending}><Check size={14} />Илгээх</Btn></Card><Card><div className="view-toolbar"><div><span className="eyebrow">REQUESTS</span><h2>{isManager ? 'Хүсэлтийн дараалал' : 'Миний хүсэлтүүд'}</h2></div><Users size={19} /></div><div className="hr-request-list">{requests.map((item: HRLeaveRequest) => <article key={item.id}><div><strong>{item.employee_name}</strong><span>{item.leave_type} · {payTypeLabel(item.approved_pay_type || item.requested_pay_type)}{item.status === 'pending' && item.requested_pay_type ? ' (хүссэн)' : ''} · {item.starts_on} – {item.ends_on} · {item.reason}</span></div><div className="hr-request-actions"><Badge color={item.status === 'approved' ? 'green' : item.status === 'rejected' ? 'red' : 'yellow'}>{item.status}</Badge>{(item.status === 'pending' || (isHR && item.status === 'approved')) && <button onClick={() => startEdit(item)} aria-label="Edit leave request"><Pencil size={15} /></button>}{isManager && item.status === 'pending' && <>{isHR ? <><button onClick={() => decide.mutate({ id: item.id, approve: true, pay_type: 'paid', version: item.version })} aria-label="Approve with salary" title="Цалинтай батлах"><Check size={15} /><small>Цалинтай</small></button><button onClick={() => decide.mutate({ id: item.id, approve: true, pay_type: 'unpaid', version: item.version })} aria-label="Approve without salary" title="Цалингүй батлах"><Check size={15} /><small>Цалингүй</small></button></> : <button onClick={() => decide.mutate({ id: item.id, approve: true, version: item.version })} aria-label="Approve"><Check size={15} /></button>}<button onClick={() => { const feedback = window.prompt('Татгалзсан шалтгаан'); if (feedback) decide.mutate({ id: item.id, approve: false, feedback, version: item.version }) }} aria-label="Reject"><X size={15} /></button></>}</div></article>)}</div></Card>{isHR && <Card><div className="view-toolbar"><div><span className="eyebrow">LEAVE BALANCE</span><h2>Баланс тохируулах</h2><p>Ажилтны жилийн ээлжийн амралтын өдрийг нэмнэ.</p></div><CalendarDays size={19} /></div><div className="hr-form-grid"><Select label="Ажилтан" value={balanceForm.employee_id} onChange={(value) => setBalanceForm({ ...balanceForm, employee_id: value })} options={[{ value: '', label: 'Ажилтан сонгох' }, ...employees.map((item) => ({ value: String(item.id), label: item.name }))]} fullWidth /><Input label="Он" type="number" min="2000" max="2200" value={balanceForm.year} onChange={(value) => setBalanceForm({ ...balanceForm, year: value })} fullWidth /><Select label="Төрөл" value={balanceForm.leave_type} onChange={(value) => setBalanceForm({ ...balanceForm, leave_type: value })} options={[{ value: 'annual', label: 'Ээлжийн' }, { value: 'sick', label: 'Өвчтэй' }, { value: 'unpaid', label: 'Цалингүй' }]} fullWidth /><Input label="Эрх (өдөр)" type="number" min="0" max="366" value={balanceForm.entitled_days} onChange={(value) => setBalanceForm({ ...balanceForm, entitled_days: value })} placeholder="15" fullWidth /><Input label="Өмнөх оноос шилжсэн" type="number" min="0" max="366" value={balanceForm.carried_days} onChange={(value) => setBalanceForm({ ...balanceForm, carried_days: value })} fullWidth /><Input label="Засвар (+/- өдөр)" type="number" min="-366" max="366" value={balanceForm.adjustment_days} onChange={(value) => setBalanceForm({ ...balanceForm, adjustment_days: value })} fullWidth /></div><Btn variant="primary" onClick={saveBalance} disabled={!balanceEmployeeId || balanceForm.entitled_days === '' || setBalance.isPending}><Check size={14} />Баланс хадгалах</Btn></Card>}{editing && <Modal title="Чөлөөний хүсэлт засах" onClose={() => setEditing(null)}><div className="hr-form-grid">{isHR && editing.status === 'approved' && <Select label="Төлөв" value={editForm.status} onChange={(value) => setEditForm({ ...editForm, status: value as 'approved' | 'rejected' })} options={[{ value: 'approved', label: 'Батлагдсан' }, { value: 'rejected', label: 'Татгалзсан' }]} fullWidth />}<Select label="Төрөл" value={editForm.leave_type} onChange={(value) => setEditForm({ ...editForm, leave_type: value as HRLeaveRequest['leave_type'] })} options={[{ value: 'annual', label: 'Ээлжийн' }, { value: 'sick', label: 'Өвчтэй' }, { value: 'unpaid', label: 'Цалингүй' }]} fullWidth /><Select label="Цалин" value={editForm.pay_type} onChange={(value) => setEditForm({ ...editForm, pay_type: value as 'paid' | 'unpaid' })} options={[{ value: 'paid', label: 'Цалинтай чөлөө' }, { value: 'unpaid', label: 'Цалингүй чөлөө' }]} fullWidth /><Input label="Эхлэх" type="date" value={editForm.starts_on} onChange={(value) => setEditForm({ ...editForm, starts_on: value })} fullWidth /><Input label="Дуусах" type="date" value={editForm.ends_on} onChange={(value) => setEditForm({ ...editForm, ends_on: value })} fullWidth /><Input label="Шалтгаан" value={editForm.reason} onChange={(value) => setEditForm({ ...editForm, reason: value })} fullWidth /></div><div className="hr-modal-actions"><Btn onClick={() => setEditing(null)}>Цуцлах</Btn><Btn variant="primary" onClick={saveEdit} disabled={!editForm.starts_on || !editForm.ends_on || !editForm.reason.trim() || update.isPending}><Check size={14} />Хадгалах</Btn></div></Modal>}</div>
}

function PayrollPanel({ onGoEmployees }: { onGoEmployees: () => void }) {
  return <div className="hr-panel-grid"><Card><div className="view-toolbar"><div><span className="eyebrow">САРЫН ЦАЛИН</span><h2>Сарын бодолтын самбар</h2><p>Урьдчилгаа болон сүүл цалинг HR-ийн цалингийн тохиргоо, баталгаажсан цагийн мэдээллээр бодно.</p></div></div><Link className="primary-action" to="/erp/payroll"><Plus size={14} />Цалингийн тойм нээх</Link></Card><Card><div className="view-toolbar"><div><span className="eyebrow">АЖИЛТНЫ ТОХИРГОО</span><h2>Цалингийн мэдээлэл засах</h2><p>Ажилтны профайлаас үндсэн цалин, төлбөрийн хуваарь, НДШ болон банкны дансыг удирдана.</p></div></div><button className="secondary-action" onClick={onGoEmployees}>Ажилтны лавлах руу очих</button></Card></div>
}

export default HRWorkspacePage
