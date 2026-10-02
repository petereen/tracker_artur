import { intlLocale } from '../utils/locale'
import i18n from '../i18n'
import { useTranslation } from 'react-i18next'
import { useState } from 'react'
import { createPortal } from 'react-dom'
import toast from 'react-hot-toast'
import { KeyRound, MoreVertical, Trash2, UserCheck, UserRoundX } from 'lucide-react'
import { Badge, Btn, Card, Input, Modal, PageHeader, Select } from '../components/ui'
import { useEmployees, useCreateEmployee, useDeleteEmployee, useEmployeePerformance, useUpdateEmployee } from '../api/hooks'
import { useAssignERPAccountRole, useERPAccessRoles, useUnassignERPAccountRole } from '../api/enterprise'
import { useCreateManagedAccount, useManagedAccounts, useUpdateManagedAccount } from '../api/enterprise'
import { telegramBotRequiredHint, tenancyErrorMessage, useTenantContext } from '../api/tenancy'
import { ReportDetailModal } from '../components/ReportDetailModal'
import { WorkerActionsMenu } from '../components/WorkerActionsMenu'
import { seatFullWorkerMessage, SeatLimitNotice, useWorkerSeats } from '../components/SeatLimitNotice'

const TZ_OPTIONS = [
  { value: 'Asia/Ulaanbaatar', get label() { return i18n.t('hr.tz.ulaanbaatar') } },
  { value: 'Asia/Hovd', get label() { return i18n.t('hr.tz.hovd') } },
  { value: 'Asia/Choibalsan', get label() { return i18n.t('hr.tz.choibalsan') } },
  { value: 'Asia/Almaty', get label() { return i18n.t('hr.tz.almaty') } },
  { value: 'Europe/Moscow', get label() { return i18n.t('hr.tz.moscow') } },
]

const STATUS_OPTIONS = [
  { value: 'active', get label() { return i18n.t('hr.active') } },
  { value: 'inactive', get label() { return i18n.t('hr.inactive') } },
]

const EMPTY_FORM = { name: '', telegram_id: '', telegram_username: '', timezone: 'Asia/Ulaanbaatar', is_active: true }

const REPORT_TYPE_KEYS = ['daily', 'monthly', 'next_month_plan']
const reportTypeLabel = (type: string) => REPORT_TYPE_KEYS.includes(type) ? i18n.t(`reports.detail.type.${type}`) : type

const accessRoles = () => [
  ['member', 'Member'], ['manager', 'Manager'], ['team_lead', 'Team lead'], ['hr', 'HR'],
  ['contractor', 'Contractor'], ['client_auditor', 'Client auditor'], ['legal_counsel', i18n.t('hr.role.legalCounsel')], ['admin', 'Admin'],
] as const

function formatMinutes(minutes: number) {
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return hours ? `${hours}${i18n.t('worktime.unit.hour')} ${rest}${i18n.t('worktime.unit.minute')}` : `${rest}${i18n.t('worktime.unit.minute')}`
}

function formatTime(value: string | null) {
  return value ? new Date(value).toLocaleTimeString(intlLocale(), { hour: '2-digit', minute: '2-digit' }) : '—'
}

function localDate(value = new Date()) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`
}

export function EmployeesPage() {
  const { t } = useTranslation()
  const tenant = useTenantContext()
  // Telegram IDs only make sense once the tenant's own bot is connected.
  const botConnected = tenant.data?.telegram_bot_connected !== false
  const [includeArchived, setIncludeArchived] = useState(false)
  const { data: employees = [] } = useEmployees(includeArchived)
  const create = useCreateEmployee()
  const deleteEmployee = useDeleteEmployee()
  const update = useUpdateEmployee()
  const accounts = useManagedAccounts()
  const createAccount = useCreateManagedAccount()
  const updateAccount = useUpdateManagedAccount()
    const { full: seatLimitReached } = useWorkerSeats()
  const customRolesQuery = useERPAccessRoles()
  const customRoles = (customRolesQuery.data || []).filter((role) => role.is_active)
  const assignCustomRole = useAssignERPAccountRole()
  const unassignCustomRole = useUnassignERPAccountRole()

  const [search, setSearch] = useState('')
  // null = закрыто, { id: null } = создание, { id: number } = редактирование
  const [editing, setEditing] = useState<{ id: number | null } | null>(null)
  const [selectedEmployeeId, setSelectedEmployeeId] = useState<number | null>(null)
  const [employeeView, setEmployeeView] = useState<'settings' | 'stats'>('settings')
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [openMenuId, setOpenMenuId] = useState<number | null>(null)
  const [performanceId, setPerformanceId] = useState<number | null>(null)
  const [performanceRange, setPerformanceRange] = useState<'day' | 'week' | 'month' | 'all' | 'custom'>('month')
  const [performanceFrom, setPerformanceFrom] = useState('')
  const [performanceTo, setPerformanceTo] = useState('')
  const [form, setForm] = useState(EMPTY_FORM)
  const [reportDetailId, setReportDetailId] = useState<number | null>(null)
  const performanceFilters = performanceRange === 'all'
    ? { all_time: true }
    : { period: 30, date_from: performanceFrom || undefined, date_to: performanceTo || undefined }
  const performance = useEmployeePerformance(performanceId, performanceFilters)

  const isEdit = editing?.id != null

  const filtered = employees.filter((e: any) =>
    e.name.toLowerCase().includes(search.toLowerCase()) ||
    (e.telegram_username || '').includes(search)
  )

  const visibleSelected = filtered.filter((e: any) => selectedIds.has(e.id))
  const allSelected = filtered.length > 0 && visibleSelected.length === filtered.length
  const toggleSelected = (id: number) => setSelectedIds((prev) => { const next = new Set(prev); if (next.has(id)) next.delete(id); else next.add(id); return next })
  const toggleAll = () => setSelectedIds(allSelected ? new Set() : new Set(filtered.map((e: any) => e.id)))

  const runBatch = async (action: 'activate' | 'deactivate' | 'delete') => {
    const targets = visibleSelected.filter((e: any) => action === 'delete' ? !e.deleted_at : action === 'activate' ? !e.is_active || e.deleted_at : e.is_active)
    if (!targets.length) { toast(t('hr.emp.noChanges')); return }
    if (action === 'delete' && !window.confirm(t('hr.emp.bulkDeleteConfirm', { n: targets.length }))) return
    const results = await Promise.allSettled(targets.map((e: any) => action === 'delete' ? deleteEmployee.mutateAsync(e.id) : update.mutateAsync({ id: e.id, is_active: action === 'activate' })))
    const failed = results.filter((r) => r.status === 'rejected').length
    if (failed) toast.error(t('hr.emp.bulkPartial', { ok: targets.length - failed, failed }))
    else toast.success(t('hr.emp.bulkDone', { n: targets.length }))
    setSelectedIds(new Set())
  }

  const openCreate = () => {
    setForm(EMPTY_FORM)
    setEditing({ id: null })
  }

  // One editor for a worker: the detail modal (settings tab holds the editable fields).
  const openEdit = (emp: any) => {
    setPerformanceId(null)
    setEmployeeView('settings')
    setSelectedEmployeeId(emp.id)
    setForm({
      name: emp.name || '',
      telegram_id: emp.telegram_id || '',
      telegram_username: emp.telegram_username || '',
      timezone: emp.timezone || 'Asia/Ulaanbaatar',
      is_active: emp.is_active,
    })
  }

  const saveEdit = async (emp: any) => {
    try {
      await update.mutateAsync({ id: emp.id, name: form.name, telegram_username: form.telegram_username, timezone: form.timezone, is_active: form.is_active })
      toast.success(t('hr.emp.saved'))
    } catch (error: any) {
      toast.error(tenancyErrorMessage(error, t('hr.emp.notSaved')))
    }
  }

  const close = () => setEditing(null)

  const submit = async () => {
    if (isEdit) {
      await update.mutateAsync({
        id: editing!.id,
        name: form.name,
        telegram_username: form.telegram_username,
        timezone: form.timezone,
        is_active: form.is_active,
      })
    } else {
      await create.mutateAsync({
        name: form.name,
        telegram_id: botConnected ? form.telegram_id.trim() || null : null,
        telegram_username: form.telegram_username,
        timezone: form.timezone,
      })
      if (seatLimitReached) toast(seatFullWorkerMessage(), { icon: '⚠️', duration: 7000 })
    }
    close()
  }

  const accountFor = (emp: any) => accounts.data?.find((account) => account.telegram_id === emp.telegram_id)
    || accounts.data?.find((account) => account.employee_id === emp.id)
  const toggleAccessRole = async (emp: any, role: string) => {
    const account = accountFor(emp)
    if (!account) return
    const roles = account.roles.includes(role) ? account.roles.filter((item) => item !== role) : [...account.roles, role]
    if (!roles.length) { toast.error(t('hr.emp.minOneRole')); return }
    try {
      await updateAccount.mutateAsync({ id: account.id, roles })
      toast.success(t('hr.emp.accessUpdated'))
    } catch (error: any) {
      toast.error(tenancyErrorMessage(error, t('hr.emp.accessNotUpdated')))
    }
  }
  const toggleCustomRole = async (accountId: number, roleId: number, assignmentId?: number) => {
    try {
      if (assignmentId) await unassignCustomRole.mutateAsync({ roleId, assignmentId })
      else await assignCustomRole.mutateAsync({ roleId, account_id: accountId })
      toast.success(t('hr.emp.accessUpdated'))
    } catch (error: any) {
      toast.error(tenancyErrorMessage(error, t('hr.emp.accessNotUpdated')))
    }
  }
  const linkAccess = async (emp: any) => {
    if (seatLimitReached) { toast.error(t('hr.emp.seatLimit')); return }
    const password = window.prompt(t('hr.emp.newPasswordPrompt', { name: emp.name }))
    if (!password) return
    if (password.length < 10) { toast.error(t('hr.emp.passwordMin')); return }
    try {
      await createAccount.mutateAsync({ email: `telegram-${emp.telegram_id}`, password, employee_id: emp.id, roles: ['member'], locale: 'mn' })
      toast.success(t('hr.emp.accessLinked'))
    } catch (error: any) {
      toast.error(tenancyErrorMessage(error, t('hr.emp.accessNotLinked')))
    }
  }
  const changeAccessPassword = async (emp: any) => {
    const account = accountFor(emp)
    if (!account) return
    const password = window.prompt(t('hr.emp.newPasswordPrompt', { name: emp.name }))
    if (!password) return
    if (password.length < 10) { toast.error(t('hr.emp.passwordMin')); return }
    try {
      await updateAccount.mutateAsync({ id: account.id, password })
      toast.success(t('hr.emp.passwordUpdated'))
    } catch (error: any) { toast.error(tenancyErrorMessage(error, t('hr.emp.passwordNotUpdated'))) }
  }
  const toggleAccountStatus = (emp: any) => {
    const account = accountFor(emp)
    if (account) updateAccount.mutate({ id: account.id, status: account.status === 'disabled' ? 'active' : 'disabled' })
  }
  const removeEmployee = (emp: any) => {
    if (!window.confirm(t('hr.emp.deleteConfirm', { name: emp.name }))) return
    deleteEmployee.mutate(emp.id, {
      onSuccess: () => {
        if (performanceId === emp.id) setPerformanceId(null)
      },
    })
  }
  const setPerformanceQuickRange = (days: number, key: 'day' | 'week' | 'month') => {
    const start = new Date()
    start.setDate(start.getDate() - days + 1)
    setPerformanceRange(key); setPerformanceFrom(localDate(start)); setPerformanceTo(localDate())
  }

  return (
    <div>
      <PageHeader title={t('hr.emp.listLabel')}>
        <label className="employee-archive-toggle"><input type="checkbox" checked={includeArchived} onChange={(event) => setIncludeArchived(event.target.checked)} />{t('hr.archived')}</label>
        <Btn variant="primary" onClick={openCreate}>{t('hr.emp.addPlus')}</Btn>
      </PageHeader>

      <Card className="admin-table-card employee-list-card p-0 overflow-hidden">
        <div className="px-5 py-4 border-b border-border">
          <input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder={t('hr.emp.searchPlaceholder')}
            className="w-full bg-surface2 border border-border rounded-lg px-3 py-[7px] text-text text-[13px] outline-none focus:border-accent" />
        </div>
        {visibleSelected.length > 0 && <div className="flex items-center gap-2 flex-wrap px-5 py-2.5 border-b border-border bg-surface2" role="toolbar" aria-label={t('hr.emp.bulkActions')}>
          <strong className="text-[13px] mr-2">{t('hr.emp.selectedCount', { n: visibleSelected.length })}</strong>
          <Btn onClick={() => runBatch('activate')}>{t('hr.workerActions.activate')}</Btn>
          <Btn onClick={() => runBatch('deactivate')}>{t('hr.workerActions.deactivate')}</Btn>
          <Btn onClick={() => runBatch('delete')}>{t('hr.delete')}</Btn>
          <Btn onClick={() => setSelectedIds(new Set())}>{t('hr.cancel')}</Btn>
        </div>}
        <table className="w-full border-collapse">
          <thead>
            <tr className="bg-surface2">
              <th className="px-4 py-2.5 w-8 border-b border-border"><input type="checkbox" aria-label={t('hr.emp.selectAll')} checked={allSelected} onChange={toggleAll} /></th>
              {[t('hr.name'), 'Telegram', 'Telegram ID', t('hr.emp.activeRoles'), t('hr.status'), ''].map((h) => (
                <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-muted border-b border-border whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((e: any, i: number) => (
              <tr key={e.id} onClick={() => { openEdit(e); setOpenMenuId(null) }}
                className={`cursor-pointer transition-colors hover:bg-surface2 ${i < filtered.length - 1 ? 'border-b border-border2' : ''}`}>
                <td className="px-4 py-2.5 w-8" onClick={(event) => event.stopPropagation()}><input type="checkbox" aria-label={t('hr.emp.selectOne', { name: e.name })} checked={selectedIds.has(e.id)} onChange={() => toggleSelected(e.id)} /></td>
                <td className="px-4 py-2.5 font-medium">{e.name}</td>
                <td className="px-4 py-2.5 text-muted font-mono text-xs">{e.telegram_username || '—'}</td>
                <td className="px-4 py-2.5 text-muted2 font-mono text-[11px]">{e.telegram_id}</td>
                <td className="px-4 py-2.5">
                  {(() => { const account = accountFor(e)
                    const custom = account ? customRoles.filter((role) => role.account_assignments.some((a) => a.account_id === account.id)) : []
                    return account?.roles.length || custom.length
                    ? <div className="employee-role-chips">{accessRoles().filter(([value]) => account?.roles.includes(value)).map(([, label]) => <span key={label}>{label}</span>)}{custom.map((role) => <span key={`c${role.id}`}>{role.name}</span>)}</div>
                    : <span className="text-xs text-muted">{t('hr.emp.noRoles')}</span> })()}
                </td>
                <td className="px-4 py-3"><Badge color={e.deleted_at ? 'muted' : e.is_active ? 'green' : 'muted'}>{e.deleted_at ? t('hr.archived') : e.is_active ? t('hr.active') : t('hr.inactive')}</Badge></td>
                <td className="px-3 py-1.5" onClick={(event) => event.stopPropagation()}>
                  <WorkerActionsMenu worker={e} open={openMenuId === e.id} onOpen={() => setOpenMenuId(openMenuId === e.id ? null : e.id)} onEdit={() => { openEdit(e); setOpenMenuId(null) }} onDelete={() => { removeEmployee(e); setOpenMenuId(null) }} onSetActive={(active) => { if (active && e.deleted_at) update.mutate({ id: e.id, is_active: true }); else update.mutate({ id: e.id, is_active: active }); setOpenMenuId(null) }} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && <div className="px-5 py-8 text-center text-muted">{t('hr.emp.notFound')}</div>}
      </Card>

      {editing && createPortal(
        <Modal title={isEdit ? t('hr.emp.editTitle') : t('hr.emp.newTitle')} onClose={close}>
          <div className="flex flex-col gap-3.5">
            {!isEdit && <SeatLimitNotice />}
            <Input label={t('hr.emp.fullName')} value={form.name} onChange={(v) => setForm((f) => ({ ...f, name: v }))} placeholder={t('hr.emp.namePlaceholder')} fullWidth />
            {isEdit ? (
              <div className="flex flex-col gap-1.5">
                <label className="text-xs text-muted font-medium">Telegram ID</label>
                <div className="bg-surface2 border border-border rounded-lg px-3 py-2 text-muted font-mono text-[13px]">{form.telegram_id}</div>
              </div>
            ) : (
              <Input label="Telegram ID" value={botConnected ? form.telegram_id : ''} onChange={(v) => setForm((f) => ({ ...f, telegram_id: v }))} placeholder="123456789" fullWidth
                disabled={!botConnected} hint={botConnected ? undefined : telegramBotRequiredHint()} />
            )}
            <Input label="Telegram username" value={form.telegram_username} onChange={(v) => setForm((f) => ({ ...f, telegram_username: v }))} placeholder="@username" fullWidth />
            <Select label={t('hr.emp.timezone')} value={form.timezone} onChange={(v) => setForm((f) => ({ ...f, timezone: v }))} options={TZ_OPTIONS} fullWidth />
            {isEdit && (
              <Select label={t('hr.status')} value={form.is_active ? 'active' : 'inactive'}
                onChange={(v) => setForm((f) => ({ ...f, is_active: v === 'active' }))} options={STATUS_OPTIONS} fullWidth />
            )}
            <div className="flex gap-2.5 justify-end pt-1">
              <Btn onClick={close}>{t('hr.cancelAlt')}</Btn>
              <Btn variant="primary" onClick={submit} disabled={create.isPending || update.isPending}>{isEdit ? t('hr.save') : t('hr.add')}</Btn>
            </div>
          </div>
        </Modal>, document.body
      )}

      {selectedEmployeeId !== null && (() => {
        const employee = employees.find((item: any) => item.id === selectedEmployeeId)
        if (!employee) return null
        const account = accountFor(employee)
        return createPortal(<Modal title={t('hr.emp.detailLabel')} onClose={() => { setSelectedEmployeeId(null); setPerformanceId(null) }} className="employee-detail-modal">
          <div className="employee-detail-heading">
            <div><div className="employee-detail-name">{employee.name}</div><div className="employee-detail-meta">{employee.telegram_username || t('hr.emp.noUsername')} <span>·</span> ID {employee.telegram_id}</div></div>
            <Badge color={employee.is_active ? 'green' : 'muted'}>{employee.is_active ? t('hr.active') : t('hr.inactive')}</Badge>
          </div>
          <div className="employee-view-switch" role="radiogroup" aria-label={t('hr.emp.viewLabel')}>
            {([['settings', t('hr.emp.tab.settings')], ['stats', t('hr.emp.tab.stats')]] as const).map(([view, label]) => <button key={view} type="button" role="radio" aria-checked={employeeView === view} className={employeeView === view ? 'active' : ''} onClick={() => { setEmployeeView(view); if (view === 'stats') { setPerformanceId(employee.id); setPerformanceRange('month'); setPerformanceFrom(''); setPerformanceTo('') } }}><span className="employee-radio-dot" />{label}</button>)}
          </div>
          {employeeView === 'settings' ? <section className="employee-settings-view">
            <div className="flex flex-col gap-3.5">
              <Input label={t('hr.emp.fullName')} value={form.name} onChange={(v) => setForm((f) => ({ ...f, name: v }))} fullWidth />
              <Input label="Telegram username" value={form.telegram_username} onChange={(v) => setForm((f) => ({ ...f, telegram_username: v }))} placeholder="@username" fullWidth />
              <Select label={t('hr.emp.timezone')} value={form.timezone} onChange={(v) => setForm((f) => ({ ...f, timezone: v }))} options={TZ_OPTIONS} fullWidth />
              <Select label={t('hr.status')} value={form.is_active ? 'active' : 'inactive'} onChange={(v) => setForm((f) => ({ ...f, is_active: v === 'active' }))} options={STATUS_OPTIONS} fullWidth />
              <div className="flex justify-end"><Btn variant="primary" onClick={() => saveEdit(employee)} disabled={update.isPending || !form.name.trim()}>{t('hr.save')}</Btn></div>
            </div>
            <div className="employee-access-header"><div><strong>{t('hr.emp.access')}</strong><span>{t('hr.emp.accessHint')}</span></div>
              {!account && <Btn variant="primary" onClick={() => linkAccess(employee)} disabled={createAccount.isPending || seatLimitReached}>{t('hr.emp.linkAccess')}</Btn>}
            </div>
            {!account && <SeatLimitNotice context="account" />}
            {account ? <fieldset className="employee-role-editor"><legend>{t('hr.emp.accessList')}</legend>{accessRoles().map(([value, label]) => <label key={value}><input type="checkbox" checked={account.roles.includes(value)} onChange={() => toggleAccessRole(employee, value)} disabled={updateAccount.isPending} /><span>{label}</span></label>)}{customRoles.map((role) => { const assignment = role.account_assignments.find((a) => a.account_id === account.id); return <label key={`c${role.id}`} title={role.description || undefined}><input type="checkbox" checked={Boolean(assignment)} onChange={() => toggleCustomRole(account.id, role.id, assignment?.id)} disabled={assignCustomRole.isPending || unassignCustomRole.isPending} /><span>{role.name}</span></label> })}</fieldset> : <p className="employee-no-access">{t('hr.emp.notLinked')}</p>}
            <div className="employee-settings-footer"><span>{account ? t('hr.emp.accountStatus', { status: account.status === 'active' ? t('hr.active') : t('hr.inactive') }) : t('hr.emp.noAccount')}</span><div className="employee-detail-menu-wrap">
              <button className="employee-detail-more" type="button" aria-label={t('hr.emp.moreActions')} aria-expanded={openMenuId === -1} onClick={() => setOpenMenuId(openMenuId === -1 ? null : -1)}><MoreVertical size={18} />{t('hr.actions')}</button>
              {openMenuId === -1 && <div className="employee-action-menu employee-detail-action-menu" role="menu">
                {account ? <><button role="menuitem" onClick={() => changeAccessPassword(employee)}><KeyRound size={15} />{t('hr.emp.changePassword')}</button><button role="menuitem" onClick={() => toggleAccountStatus(employee)}>{account.status === 'disabled' ? <UserCheck size={15} /> : <UserRoundX size={15} />}{account.status === 'disabled' ? t('hr.emp.openLogin') : t('hr.emp.closeLogin')}</button></> : null}
                <button role="menuitem" onClick={() => { update.mutate({ id: employee.id, is_active: !employee.is_active }); setForm((f) => ({ ...f, is_active: !employee.is_active })); setOpenMenuId(null) }}>{employee.is_active ? <UserRoundX size={15} /> : <UserCheck size={15} />}{employee.is_active ? t('hr.emp.deactivate') : t('hr.emp.activate')}</button>
                <button role="menuitem" className="danger" onClick={() => removeEmployee(employee)}><Trash2 size={15} />{t('hr.emp.delete')}</button>
              </div>}
            </div></div>
          </section> : <section className="employee-stats-view">
          {performance.isLoading && <div className="py-12 text-center text-muted">{t('hr.emp.statsLoading')}</div>}
          {performance.isError && <div className="py-12 text-center text-red">{t('hr.emp.statsError')}</div>}
          {performance.data && (() => {
            const data = performance.data
            const checkins = data.checkins
            const workTime = data.work_time
            const reports = data.reports
            return <div>
              <div className="flex items-start justify-between gap-4 mb-5">
                <div>
                  <div className="text-lg font-semibold">{data.employee.name}</div>
                  <div className="text-xs text-muted mt-0.5">{data.employee.telegram_username || t('hr.emp.noUsername')} · {data.employee.timezone}</div>
                </div>
                <Badge color={data.employee.is_active ? 'green' : 'muted'}>{data.employee.is_active ? t('hr.active') : t('hr.inactive')}</Badge>
              </div>

              <div className="flex gap-1 bg-surface2 rounded-lg p-1 flex-wrap mb-4">
                {[['day', t('hr.emp.range.today')], ['week', t('hr.emp.range.week')], ['month', t('hr.emp.range.month')], ['all', t('hr.emp.range.all')]].map(([key, label]) => (
                  <button key={key} onClick={() => key === 'day' ? setPerformanceQuickRange(1, 'day') : key === 'week' ? setPerformanceQuickRange(7, 'week') : key === 'month' ? setPerformanceQuickRange(30, 'month') : setPerformanceRange('all')}
                    className={`px-2.5 py-1.5 rounded text-xs cursor-pointer border-none ${performanceRange === key ? 'bg-accent text-white' : 'bg-transparent text-muted'}`}>{label}</button>
                ))}
                <input type="date" value={performanceFrom} onChange={(e) => { setPerformanceRange('custom'); setPerformanceFrom(e.target.value) }} className="ml-1 bg-surface border border-border rounded px-2 text-xs text-text outline-none" />
                <input type="date" value={performanceTo} onChange={(e) => { setPerformanceRange('custom'); setPerformanceTo(e.target.value) }} className="bg-surface border border-border rounded px-2 text-xs text-text outline-none" />
              </div>
              <div className="text-xs text-muted mb-2">{data.date_from ? `${data.date_from} – ${data.date_to}` : t('hr.emp.allTimeUntil', { date: data.date_to })}</div>
              <div className="grid grid-cols-3 gap-3 mb-5">
                <Card className="!p-4">
                  <div className="text-xs text-muted">{t('hr.emp.totalHours')}</div>
                  <div className="text-2xl font-semibold text-green mt-1">{formatMinutes(workTime.total_minutes)}</div>
                  <div className="text-xs text-muted mt-1">{t('hr.emp.completeEntries', { n: workTime.complete_entries })}</div>
                </Card>
                <Card className="!p-4">
                  <div className="text-xs text-muted">{t('hr.emp.checkinRate')}</div>
                  <div className="text-2xl font-semibold text-accent mt-1">{checkins.completion_rate}%</div>
                  <div className="text-xs text-muted mt-1">{t('hr.emp.submittedOf', { submitted: checkins.submitted, total: checkins.total })}</div>
                </Card>
                <Card className="!p-4">
                  <div className="text-xs text-muted">{t('hr.emp.approvedDaily')}</div>
                  <div className="text-2xl font-semibold text-purple mt-1">{reports.daily.approved}</div>
                  <div className="text-xs text-muted mt-1">{t('hr.emp.reportsTotal', { n: reports.daily.total })}</div>
                </Card>
              </div>

              <div className="grid grid-cols-2 gap-4 mb-5">
                <div className="bg-surface2 border border-border rounded-xl p-4">
                  <div className="font-medium mb-3">{t('hr.emp.checkinStats')}</div>
                  <div className="grid grid-cols-2 gap-y-2 text-[13px]">
                    <span className="text-muted">{t('hr.emp.filledFull')}</span><span className="text-right text-green font-medium">{checkins.completed}</span>
                    <span className="text-muted">{t('hr.emp.filledPartial')}</span><span className="text-right text-yellow font-medium">{checkins.partial}</span>
                    <span className="text-muted">{t('hr.emp.skipped')}</span><span className="text-right text-red font-medium">{checkins.missed}</span>
                    <span className="text-muted">{t('hr.emp.pending')}</span><span className="text-right text-muted font-medium">{checkins.pending}</span>
                  </div>
                </div>
                <div className="bg-surface2 border border-border rounded-xl p-4">
                  <div className="font-medium mb-3">{t('hr.emp.workTime')}</div>
                  <div className="grid grid-cols-2 gap-y-2 text-[13px]">
                    <span className="text-muted">{t('worktime.office')}</span><span className="text-right font-medium">{formatMinutes(workTime.in_person_minutes)}</span>
                    <span className="text-muted">{t('worktime.remote')}</span><span className="text-right font-medium">{formatMinutes(workTime.remote_minutes)}</span>
                    <span className="text-muted">{t('hr.emp.dailyAvg')}</span><span className="text-right font-medium">{formatMinutes(workTime.average_minutes)}</span>
                    <span className="text-muted">{t('hr.emp.fullIntervals')}</span><span className="text-right font-medium">{workTime.complete_entries}</span>
                    <span className="text-muted">{t('hr.emp.incomplete')}</span><span className="text-right text-yellow font-medium">{workTime.incomplete_entries}</span>
                  </div>
                </div>
              </div>

              <div className="font-medium mb-2">{t('hr.emp.dayDetails')}</div>
              <div className="border border-border rounded-lg overflow-hidden max-h-56 overflow-y-auto mb-5">
                {(workTime.days || []).length ? workTime.days.map((day: any, index: number) => <div key={day.period_date} className={`px-3 py-2.5 text-xs ${index ? 'border-t border-border2' : ''}`}>
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-medium">{day.period_date}</span>
                    <span className="text-green font-medium">{t('hr.emp.dayTotals', { total: formatMinutes(day.total_minutes), office: formatMinutes(day.in_person_minutes), remote: formatMinutes(day.remote_minutes) })}</span>
                  </div>
                  <div className="text-muted mt-1">{day.entries.map((entry: any) => `${entry.mode === 'remote' ? t('worktime.remote') : t('worktime.office')} ${formatTime(entry.started_at)}–${formatTime(entry.ended_at)} (${formatMinutes(entry.minutes)})`).join(' · ') || t('hr.emp.noInterval')}</div>
                </div>) : <div className="p-5 text-center text-sm text-muted">{t('hr.emp.noWorktime')}</div>}
              </div>

              <div className="flex items-center justify-between mb-2">
                <div className="font-medium">{t('hr.emp.reportStats')}</div>
                <div className="text-xs text-muted">{t('hr.emp.approvedTotal')}</div>
              </div>
              <div className="grid grid-cols-3 gap-3 mb-5 text-center">
                {[
                  [t('reports.detail.type.daily'), reports.daily],
                  [t('reports.detail.type.monthly'), reports.monthly],
                  [t('reports.detail.type.next_month_plan'), reports.next_month_plan],
                ].map(([label, stats]: any) => <div key={label} className="border border-border rounded-lg p-3">
                  <div className="text-xs text-muted">{label}</div>
                  <div className="font-semibold mt-1">{stats.approved} / {stats.total}</div>
                  {stats.pending > 0 && <div className="text-[11px] text-yellow mt-0.5">{t('hr.emp.pendingCount', { n: stats.pending })}</div>}
                </div>)}
              </div>

              <div className="font-medium mb-2">{t('hr.emp.recentReports')}</div>
              <div className="border border-border rounded-lg overflow-hidden max-h-52 overflow-y-auto">
                {data.recent_reports.length ? data.recent_reports.map((report: any, index: number) => <div key={report.id} className={`grid grid-cols-[minmax(0,1fr)_auto_auto] gap-3 items-center px-3 py-2.5 text-xs ${index ? 'border-t border-border2' : ''}`}>
                  <div className="min-w-0"><div className="font-medium">{reportTypeLabel(report.report_type)}</div><div className="text-muted mt-0.5">{report.period_date}{report.report_type === 'daily' ? t('hr.emp.reportTotals', { total: formatMinutes(report.work_time?.total_minutes || 0), office: formatMinutes(report.work_time?.in_person_minutes || 0), remote: formatMinutes(report.work_time?.remote_minutes || 0) }) : ''}</div>{report.text && <div className="text-muted mt-1 truncate">{report.text}</div>}</div>
                  <Badge color={report.status === 'approved' ? 'green' : report.status === 'awaiting' ? 'yellow' : 'blue'}>{report.status === 'approved' ? t('reports.detail.status.approved') : report.status === 'awaiting' ? t('hr.emp.pending') : t('reports.detail.status.draft')}</Badge>
                  <Btn onClick={() => setReportDetailId(report.id)}>{t('hr.emp.details')}</Btn>
                </div>) : <div className="p-5 text-center text-sm text-muted">{t('hr.emp.noReports')}</div>}
              </div>
            </div>
          })()}
          </section>}
        </Modal>, document.body)
      })()}
      {reportDetailId !== null && <ReportDetailModal reportId={reportDetailId} onClose={() => setReportDetailId(null)} />}
    </div>
  )
}
