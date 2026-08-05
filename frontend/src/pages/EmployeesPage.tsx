import { useState } from 'react'
import toast from 'react-hot-toast'
import { Badge, Btn, Card, Input, Modal, PageHeader, Select } from '../components/ui'
import { useEmployees, useCreateEmployee, useEmployeePerformance, useUpdateEmployee } from '../api/hooks'
import { useCreateManagedAccount, useManagedAccounts, useUpdateManagedAccount } from '../api/enterprise'
import { ReportDetailModal } from '../components/ReportDetailModal'

const TZ_OPTIONS = [
  { value: 'Asia/Ulaanbaatar',    label: 'Улаанбаатар (UTC+8)' },
  { value: 'Asia/Hovd',           label: 'Ховд (UTC+7)' },
  { value: 'Asia/Choibalsan',     label: 'Чойбалсан (UTC+8)' },
  { value: 'Asia/Almaty',         label: 'Алматы (UTC+5)' },
  { value: 'Europe/Moscow',       label: 'Москва (UTC+3)' },
]

const STATUS_OPTIONS = [
  { value: 'active',   label: 'Идэвхтэй' },
  { value: 'inactive', label: 'Идэвхгүй' },
]

const EMPTY_FORM = { name: '', telegram_id: '', telegram_username: '', timezone: 'Asia/Ulaanbaatar', is_active: true }

const REPORT_TYPE_LABELS: Record<string, string> = {
  daily: 'Өдрийн тайлан',
  monthly: 'Сарын тайлан',
  next_month_plan: 'Дараа сарын төлөвлөгөө',
}

const ACCESS_ROLES = [
  ['member', 'Member'], ['manager', 'Manager'], ['team_lead', 'Team lead'],
  ['contractor', 'Contractor'], ['client_auditor', 'Client auditor'], ['admin', 'Admin'],
] as const

function formatMinutes(minutes: number) {
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return hours ? `${hours}ц ${rest}м` : `${rest}м`
}

function formatTime(value: string | null) {
  return value ? new Date(value).toLocaleTimeString('mn-MN', { hour: '2-digit', minute: '2-digit' }) : '—'
}

function localDate(value = new Date()) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`
}

export function EmployeesPage() {
  const { data: employees = [] } = useEmployees()
  const create = useCreateEmployee()
  const update = useUpdateEmployee()
  const accounts = useManagedAccounts()
  const createAccount = useCreateManagedAccount()
  const updateAccount = useUpdateManagedAccount()

  const [search, setSearch] = useState('')
  // null = закрыто, { id: null } = создание, { id: number } = редактирование
  const [editing, setEditing] = useState<{ id: number | null } | null>(null)
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

  const openCreate = () => {
    setForm(EMPTY_FORM)
    setEditing({ id: null })
  }

  const openEdit = (emp: any) => {
    setForm({
      name: emp.name || '',
      telegram_id: emp.telegram_id || '',
      telegram_username: emp.telegram_username || '',
      timezone: emp.timezone || 'Asia/Ulaanbaatar',
      is_active: emp.is_active,
    })
    setEditing({ id: emp.id })
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
        telegram_id: form.telegram_id,
        telegram_username: form.telegram_username,
        timezone: form.timezone,
      })
    }
    close()
  }

  const toggle = (emp: any) => update.mutate({ id: emp.id, is_active: !emp.is_active })
  const accountFor = (emp: any) => accounts.data?.find((account) => account.telegram_id === emp.telegram_id)
    || accounts.data?.find((account) => account.employee_id === emp.id)
  const toggleAccessRole = async (emp: any, role: string) => {
    const account = accountFor(emp)
    if (!account) return
    const roles = account.roles.includes(role) ? account.roles.filter((item) => item !== role) : [...account.roles, role]
    if (!roles.length) { toast.error('Хэрэглэгч дор хаяж нэг эрхтэй байна'); return }
    try {
      await updateAccount.mutateAsync({ id: account.id, roles })
      toast.success('Хандалтын эрх шинэчлэгдлээ')
    } catch (error: any) {
      toast.error(error.response?.data?.detail || 'Эрх шинэчлэгдсэнгүй')
    }
  }
  const linkAccess = async (emp: any) => {
    const password = window.prompt(`${emp.name}-ийн шинэ нууц үг (10+ тэмдэгт):`)
    if (!password) return
    if (password.length < 10) { toast.error('Нууц үг 10+ тэмдэгт байх ёстой'); return }
    try {
      await createAccount.mutateAsync({ email: `telegram-${emp.telegram_id}`, password, employee_id: emp.id, roles: ['member'], locale: 'mn' })
      toast.success('Ажилтны хандалт холбогдлоо')
    } catch (error: any) {
      toast.error(error.response?.data?.detail || 'Хандалт холбогдсонгүй')
    }
  }
  const setPerformanceQuickRange = (days: number, key: 'day' | 'week' | 'month') => {
    const start = new Date()
    start.setDate(start.getDate() - days + 1)
    setPerformanceRange(key); setPerformanceFrom(localDate(start)); setPerformanceTo(localDate())
  }

  return (
    <div>
      <PageHeader title="Ажилтнууд" sub={`${employees.filter((e: any) => e.is_active).length} идэвхтэй · нийт ${employees.length}`}>
        <Btn variant="primary" onClick={openCreate}>+ Нэмэх</Btn>
      </PageHeader>

      <Card className="admin-table-card p-0 overflow-hidden">
        <div className="px-5 py-4 border-b border-border">
          <input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Нэр эсвэл @username-аар хайх…"
            className="w-full bg-surface2 border border-border rounded-lg px-3 py-[7px] text-text text-[13px] outline-none focus:border-accent" />
        </div>
        <table className="w-full border-collapse">
          <thead>
            <tr className="bg-surface2">
              {['Ажилтан', 'Telegram', 'ID', 'Хандалт', 'Цагийн бүс', 'Төлөв', ''].map((h) => (
                <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-muted border-b border-border whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((e: any, i: number) => (
              <tr key={e.id} onClick={() => { setPerformanceId(e.id); setPerformanceRange('month'); setPerformanceFrom(''); setPerformanceTo('') }}
                className={`cursor-pointer transition-colors hover:bg-surface2 ${i < filtered.length - 1 ? 'border-b border-border2' : ''}`}>
                <td className="px-4 py-3 font-medium">{e.name}</td>
                <td className="px-4 py-3 text-muted font-mono text-xs">{e.telegram_username || '—'}</td>
                <td className="px-4 py-3 text-muted2 font-mono text-[11px]">{e.telegram_id}</td>
                <td className="px-4 py-3" onClick={(event) => event.stopPropagation()}>
                  {(() => {
                    const account = accountFor(e)
                    if (!account) return <Btn variant="ghost" onClick={() => linkAccess(e)} disabled={createAccount.isPending}>Холбох</Btn>
                    return <div className="flex flex-wrap gap-x-2 gap-y-1 max-w-[240px]">
                      {ACCESS_ROLES.map(([value, label]) => <label key={value} className="inline-flex items-center gap-1 text-[11px] text-muted whitespace-nowrap">
                        <input type="checkbox" checked={account.roles.includes(value)} onChange={() => toggleAccessRole(e, value)} disabled={updateAccount.isPending} />
                        {label}
                      </label>)}
                    </div>
                  })()}
                </td>
                <td className="px-4 py-3 text-muted text-xs">{e.timezone}</td>
                <td className="px-4 py-3"><Badge color={e.is_active ? 'green' : 'muted'}>{e.is_active ? 'Идэвхтэй' : 'Идэвхгүй'}</Badge></td>
                <td className="px-4 py-3">
                  <div className="flex gap-1.5" onClick={(event) => event.stopPropagation()}>
                    <Btn variant="ghost" onClick={() => openEdit(e)}>Засах</Btn>
                    <Btn variant={e.is_active ? 'danger' : 'ghost'} onClick={() => toggle(e)}>{e.is_active ? 'Идэвхгүй болгох' : 'Идэвхжүүлэх'}</Btn>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && <div className="px-5 py-8 text-center text-muted">Ажилтан олдсонгүй</div>}
      </Card>

      {editing && (
        <Modal title={isEdit ? 'Ажилтан засах' : 'Шинэ ажилтан'} onClose={close}>
          <div className="flex flex-col gap-3.5">
            <Input label="Нэр, овог" value={form.name} onChange={(v) => setForm((f) => ({ ...f, name: v }))} placeholder="Бат Болд" fullWidth />
            {isEdit ? (
              <div className="flex flex-col gap-1.5">
                <label className="text-xs text-muted font-medium">Telegram ID</label>
                <div className="bg-surface2 border border-border rounded-lg px-3 py-2 text-muted font-mono text-[13px]">{form.telegram_id}</div>
              </div>
            ) : (
              <Input label="Telegram ID" value={form.telegram_id} onChange={(v) => setForm((f) => ({ ...f, telegram_id: v }))} placeholder="123456789" fullWidth />
            )}
            <Input label="Telegram username" value={form.telegram_username} onChange={(v) => setForm((f) => ({ ...f, telegram_username: v }))} placeholder="@username" fullWidth />
            <Select label="Цагийн бүс" value={form.timezone} onChange={(v) => setForm((f) => ({ ...f, timezone: v }))} options={TZ_OPTIONS} fullWidth />
            {isEdit && (
              <Select label="Төлөв" value={form.is_active ? 'active' : 'inactive'}
                onChange={(v) => setForm((f) => ({ ...f, is_active: v === 'active' }))} options={STATUS_OPTIONS} fullWidth />
            )}
            <div className="flex gap-2.5 justify-end pt-1">
              <Btn onClick={close}>Цуцлах</Btn>
              <Btn variant="primary" onClick={submit} disabled={create.isPending || update.isPending}>{isEdit ? 'Хадгалах' : 'Нэмэх'}</Btn>
            </div>
          </div>
        </Modal>
      )}

      {performanceId !== null && (
        <Modal title="Ажилтны гүйцэтгэл" onClose={() => setPerformanceId(null)} className="performance-modal max-w-6xl max-h-[calc(100vh-48px)] overflow-y-auto">
          {performance.isLoading && <div className="py-12 text-center text-muted">Гүйцэтгэлийн мэдээлэл ачаалж байна…</div>}
          {performance.isError && <div className="py-12 text-center text-red">Мэдээлэл ачаалахад алдаа гарлаа</div>}
          {performance.data && (() => {
            const data = performance.data
            const checkins = data.checkins
            const workTime = data.work_time
            const reports = data.reports
            return <div>
              <div className="flex items-start justify-between gap-4 mb-5">
                <div>
                  <div className="text-lg font-semibold">{data.employee.name}</div>
                  <div className="text-xs text-muted mt-0.5">{data.employee.telegram_username || 'Telegram username байхгүй'} · {data.employee.timezone}</div>
                </div>
                <Badge color={data.employee.is_active ? 'green' : 'muted'}>{data.employee.is_active ? 'Идэвхтэй' : 'Идэвхгүй'}</Badge>
              </div>

              <div className="flex gap-1 bg-surface2 rounded-lg p-1 flex-wrap mb-4">
                {[['day', 'Өнөөдөр'], ['week', '7 хоног'], ['month', '30 хоног'], ['all', 'Бүх хугацаа']].map(([key, label]) => (
                  <button key={key} onClick={() => key === 'day' ? setPerformanceQuickRange(1, 'day') : key === 'week' ? setPerformanceQuickRange(7, 'week') : key === 'month' ? setPerformanceQuickRange(30, 'month') : setPerformanceRange('all')}
                    className={`px-2.5 py-1.5 rounded text-xs cursor-pointer border-none ${performanceRange === key ? 'bg-accent text-white' : 'bg-transparent text-muted'}`}>{label}</button>
                ))}
                <input type="date" value={performanceFrom} onChange={(e) => { setPerformanceRange('custom'); setPerformanceFrom(e.target.value) }} className="ml-1 bg-surface border border-border rounded px-2 text-xs text-text outline-none" />
                <input type="date" value={performanceTo} onChange={(e) => { setPerformanceRange('custom'); setPerformanceTo(e.target.value) }} className="bg-surface border border-border rounded px-2 text-xs text-text outline-none" />
              </div>
              <div className="text-xs text-muted mb-2">{data.date_from ? `${data.date_from} – ${data.date_to}` : `Бүх хугацаа · ${data.date_to} хүртэл`}</div>
              <div className="grid grid-cols-3 gap-3 mb-5">
                <Card className="!p-4">
                  <div className="text-xs text-muted">Нийт ажилласан цаг</div>
                  <div className="text-2xl font-semibold text-green mt-1">{formatMinutes(workTime.total_minutes)}</div>
                  <div className="text-xs text-muted mt-1">{workTime.complete_entries} бүрэн цагийн бүртгэл</div>
                </Card>
                <Card className="!p-4">
                  <div className="text-xs text-muted">Чек-иний биелэлт</div>
                  <div className="text-2xl font-semibold text-accent mt-1">{checkins.completion_rate}%</div>
                  <div className="text-xs text-muted mt-1">{checkins.submitted} / {checkins.total} илгээсэн</div>
                </Card>
                <Card className="!p-4">
                  <div className="text-xs text-muted">Батлагдсан өдрийн тайлан</div>
                  <div className="text-2xl font-semibold text-purple mt-1">{reports.daily.approved}</div>
                  <div className="text-xs text-muted mt-1">Нийт {reports.daily.total} тайлан</div>
                </Card>
              </div>

              <div className="grid grid-cols-2 gap-4 mb-5">
                <div className="bg-surface2 border border-border rounded-xl p-4">
                  <div className="font-medium mb-3">Чек-иний статистик</div>
                  <div className="grid grid-cols-2 gap-y-2 text-[13px]">
                    <span className="text-muted">Бүрэн бөглөсөн</span><span className="text-right text-green font-medium">{checkins.completed}</span>
                    <span className="text-muted">Хэсэгчлэн</span><span className="text-right text-yellow font-medium">{checkins.partial}</span>
                    <span className="text-muted">Алгассан</span><span className="text-right text-red font-medium">{checkins.missed}</span>
                    <span className="text-muted">Хүлээгдэж буй</span><span className="text-right text-muted font-medium">{checkins.pending}</span>
                  </div>
                </div>
                <div className="bg-surface2 border border-border rounded-xl p-4">
                  <div className="font-medium mb-3">Ажлын цаг</div>
                  <div className="grid grid-cols-2 gap-y-2 text-[13px]">
                    <span className="text-muted">Оффис</span><span className="text-right font-medium">{formatMinutes(workTime.in_person_minutes)}</span>
                    <span className="text-muted">Remote</span><span className="text-right font-medium">{formatMinutes(workTime.remote_minutes)}</span>
                    <span className="text-muted">Өдрийн дундаж</span><span className="text-right font-medium">{formatMinutes(workTime.average_minutes)}</span>
                    <span className="text-muted">Бүрэн интервал</span><span className="text-right font-medium">{workTime.complete_entries}</span>
                    <span className="text-muted">Дутуу бүртгэл</span><span className="text-right text-yellow font-medium">{workTime.incomplete_entries}</span>
                  </div>
                </div>
              </div>

              <div className="font-medium mb-2">Өдрийн ажлын цагийн дэлгэрэнгүй</div>
              <div className="border border-border rounded-lg overflow-hidden max-h-56 overflow-y-auto mb-5">
                {(workTime.days || []).length ? workTime.days.map((day: any, index: number) => <div key={day.period_date} className={`px-3 py-2.5 text-xs ${index ? 'border-t border-border2' : ''}`}>
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-medium">{day.period_date}</span>
                    <span className="text-green font-medium">Нийт {formatMinutes(day.total_minutes)} · Оффис {formatMinutes(day.in_person_minutes)} · Remote {formatMinutes(day.remote_minutes)}</span>
                  </div>
                  <div className="text-muted mt-1">{day.entries.map((entry: any) => `${entry.mode === 'remote' ? 'Remote' : 'Оффис'} ${formatTime(entry.started_at)}–${formatTime(entry.ended_at)} (${formatMinutes(entry.minutes)})`).join(' · ') || 'Интервал бүртгэгдээгүй'}</div>
                </div>) : <div className="p-5 text-center text-sm text-muted">Ажлын цагийн мэдээлэл алга</div>}
              </div>

              <div className="flex items-center justify-between mb-2">
                <div className="font-medium">Тайлангийн статистик</div>
                <div className="text-xs text-muted">батлагдсан / нийт</div>
              </div>
              <div className="grid grid-cols-3 gap-3 mb-5 text-center">
                {[
                  ['Өдрийн тайлан', reports.daily],
                  ['Сарын тайлан', reports.monthly],
                  ['Дараа сарын төлөвлөгөө', reports.next_month_plan],
                ].map(([label, stats]: any) => <div key={label} className="border border-border rounded-lg p-3">
                  <div className="text-xs text-muted">{label}</div>
                  <div className="font-semibold mt-1">{stats.approved} / {stats.total}</div>
                  {stats.pending > 0 && <div className="text-[11px] text-yellow mt-0.5">{stats.pending} хүлээгдэж буй</div>}
                </div>)}
              </div>

              <div className="font-medium mb-2">Сүүлийн тайлангууд</div>
              <div className="border border-border rounded-lg overflow-hidden max-h-52 overflow-y-auto">
                {data.recent_reports.length ? data.recent_reports.map((report: any, index: number) => <div key={report.id} className={`grid grid-cols-[minmax(0,1fr)_auto_auto] gap-3 items-center px-3 py-2.5 text-xs ${index ? 'border-t border-border2' : ''}`}>
                  <div className="min-w-0"><div className="font-medium">{REPORT_TYPE_LABELS[report.report_type] || report.report_type}</div><div className="text-muted mt-0.5">{report.period_date}{report.report_type === 'daily' ? ` · ${formatMinutes(report.work_time?.total_minutes || 0)} · Оффис ${formatMinutes(report.work_time?.in_person_minutes || 0)} · Remote ${formatMinutes(report.work_time?.remote_minutes || 0)}` : ''}</div>{report.text && <div className="text-muted mt-1 truncate">{report.text}</div>}</div>
                  <Badge color={report.status === 'approved' ? 'green' : report.status === 'awaiting' ? 'yellow' : 'blue'}>{report.status === 'approved' ? 'Батлагдсан' : report.status === 'awaiting' ? 'Хүлээгдэж буй' : 'Ноорог'}</Badge>
                  <Btn onClick={() => setReportDetailId(report.id)}>Дэлгэрэнгүй</Btn>
                </div>) : <div className="p-5 text-center text-sm text-muted">Тайлан байхгүй</div>}
              </div>
            </div>
          })()}
        </Modal>
      )}
      {reportDetailId !== null && <ReportDetailModal reportId={reportDetailId} onClose={() => setReportDetailId(null)} />}
    </div>
  )
}
