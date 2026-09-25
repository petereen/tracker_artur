import { Fragment, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Check, ChevronDown, ChevronRight, CircleAlert, Download, Info, LockKeyhole, MoreHorizontal, Pencil, RefreshCw, Trash2, Upload, UserPlus, X } from 'lucide-react'
import toast from 'react-hot-toast'
import {
  downloadMonthlyPayrollExport, downloadMonthlyPayrollInputTemplate, useAcceptMonthlyPayrollHRChange, useAddMonthlyPayrollRunWorkers,
  useApproveMonthlyPayrollRow, useApproveMonthlyPayrollRun, useCalculateMonthlyPayrollRun, useDeleteMonthlyPayrollRun, useFlagMonthlyPayrollRow,
  useImportMonthlyPayrollInputs, useMarkMonthlyPayrollPaid, useMarkMonthlyPayrollUnpaid, useMonthlyPayrollMonth, useMonthlyPayrollRun,
  usePayrollCapabilities, useRefreshMonthlyPayrollAdvances, useRefreshMonthlyPayrollTime, useReopenMonthlyPayrollRun,
  useSaveMonthlyPayrollRow, useSyncMonthlyPayrollWorkers, useUnapproveMonthlyPayrollRow, useUnapproveMonthlyPayrollRun,
  useUnflagMonthlyPayrollRow, useWorkerDirectory,
} from '../../api/enterprise'
import type { MonthlyPayrollApprovalSummary, MonthlyPayrollRunRow } from '../../api/enterprise'
import {
  BLOCKING_WARNINGS, MonthlyShell, RowStateChip, RunStatusChip, formatAmount, formatHours, monthFigures, monthKey, requestError,
  rowState, runTitle, shiftMonth, toNumber, useReasonDialog, warningLabel, type RowState,
} from './shared'
import { plainNumber } from '../../utils/numbers'
import { RowDrawer } from './RowDrawer'

type Row = MonthlyPayrollRunRow
type Kind = 'text' | 'money' | 'hours' | 'days'
type Column = {
  key: string; label: string; kind: Kind; short?: boolean; group?: string; sticky?: 'index' | 'name'
  value: (row: Row, index: number) => unknown
  manual?: (row: Row) => boolean
  render?: (row: Row, editing: boolean) => ReactNode
}
type Draft = Record<string, any>

const BUCKETS = [
  { key: 'weekday', label: 'Ажлын өдрийн илүү цаг', mark: 'И', law: '109.1' },
  { key: 'rest_day', label: 'Долоо хоногийн амралтын өдөр', mark: 'А', law: '109.2' },
  { key: 'public_holiday', label: 'Нийтийн амралтын өдөр', mark: 'Б', law: '109.4' },
] as const
const WEEKDAYS = ['Да', 'Мя', 'Лх', 'Пү', 'Ба', 'Бя', 'Ня']
const DAY_TYPES: Record<string, string> = { working: 'Ажлын өдөр', weekly_rest: 'Амралтын өдөр', public_holiday: 'Баярын өдөр' }
const BASIS_LABELS: Record<string, string> = { FIXED: 'Тогтмол дүн', PERCENT: 'Цалингийн хувь', 'WORKED-TO-DATE': 'Ажилласан цагаар' }
const SALARY_TYPES: Record<string, string> = { PRORATION: 'Цагаар', FIXED: 'Тогтмол' }
const FILTERS: Array<{ key: string; label: string; test: (row: Row) => boolean }> = [
  { key: 'all', label: 'Бүгд', test: () => true },
  { key: 'draft', label: 'Ноорог', test: (row) => row.status !== 'approved' },
  { key: 'approved', label: 'Батлагдсан', test: (row) => row.status === 'approved' },
  { key: 'attention', label: 'Анхаарах', test: (row) => row.status === 'flagged' || row.warnings.some((warning) => warning !== 'overtime_work') },
  { key: 'error', label: 'Алдаатай', test: (row) => rowState(row) === 'error' },
  { key: 'overtime', label: 'Илүү цагтай', test: (row) => row.warnings.includes('overtime_work') },
]
const PROFILE_WARNINGS = ['profile_missing', 'salary_history_missing_or_incomplete', 'profile_incomplete']

const sourceDiffers = (row: Row, key: string) => {
  const source = row.inputs._source_snapshot
  return Boolean(source) && JSON.stringify(row.inputs[key] ?? null) !== JSON.stringify(source[key] ?? null)
}
const overridden = (row: Row, field: string) => (row.result.computed_overrides || []).includes(field)
const overtimeTotal = (row: Row) => Object.values(row.inputs.overtime_hours || {}).reduce((sum: number, value) => sum + toNumber(value), 0)
const activeBuckets = (row: Row) => BUCKETS.filter((bucket) => toNumber(row.inputs.overtime_hours?.[bucket.key]) > 0)
const displayName = (row: Row) => row.identity.last_name || row.identity.first_name ? `${row.identity.last_name || ''} ${row.identity.first_name || ''}`.trim() : row.identity.name || `#${row.employee_id}`
const visibleWarnings = (row: Row) => row.warnings.filter((warning) => warning !== 'overtime_work')

function OvertimeInfo({ row, children }: { row: Row; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState<CSSProperties>({})
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const show = () => {
    // Fixed positioning keeps the box outside the register's scroll clipping.
    const rect = triggerRef.current?.getBoundingClientRect()
    if (rect) {
      const left = Math.max(8, Math.min(rect.right - 560, window.innerWidth - 568))
      setPosition(rect.bottom < window.innerHeight * 0.55 ? { top: rect.bottom + 6, left } : { bottom: window.innerHeight - rect.top + 6, left })
    }
    setOpen(true)
  }
  const buckets = activeBuckets(row)
  if (!buckets.length) return <>{children}</>
  const month = monthFigures(row)
  const lines: any[] = month.overtime_lines || []
  const manualHours = sourceDiffers(row, 'overtime_hours')
  return <span className="mp-ot-anchor" onMouseEnter={show} onMouseLeave={() => setOpen(false)}>
    <button ref={triggerRef} type="button" className="mp-ot-trigger" aria-expanded={open} onClick={() => (open ? setOpen(false) : show())} onBlur={() => setOpen(false)}>
      {children}<span className="mp-ot-marks" aria-hidden="true">{buckets.map((bucket) => <b key={bucket.key} className={`mp-ot-mark ${bucket.key}`}>{bucket.mark}</b>)}</span>
    </button>
    {open && <div className="mp-ot-box" role="tooltip" style={position}>
      <strong>Илүү цаг, амралт, баярын өдрийн ажил</strong>
      <table><thead><tr><th>Огноо</th><th>Гараг</th><th>Төрөл</th><th>Цаг</th><th>×</th><th>Цагийн үнэлгээ</th><th>Дүн</th></tr></thead><tbody>
        {BUCKETS.map((bucket) => {
          const bucketLines = lines.filter((line) => line.bucket === bucket.key)
          if (!bucketLines.length) return null
          return <Fragment key={bucket.key}>
            {bucketLines.map((line, index) => <tr key={`${bucket.key}-${index}`}><td>{line.date || 'Гараар'}</td><td>{line.weekday !== null && line.weekday !== undefined ? WEEKDAYS[line.weekday] : '—'}</td><td><b className={`mp-ot-mark ${bucket.key}`}>{bucket.mark}</b> {line.day_type ? DAY_TYPES[line.day_type] || line.day_type : bucket.label}</td><td>{formatHours(line.hours)}</td><td>{line.multiplier}</td><td>{formatAmount(line.rate)}</td><td>{formatAmount(line.amount)}</td></tr>)}
            <tr className="mp-ot-subtotal"><td colSpan={3}>{bucket.label} · ХТХ {bucket.law}</td><td>{formatHours(row.inputs.overtime_hours?.[bucket.key])}</td><td /><td /><td>{formatAmount(month.overtime_by_bucket?.[bucket.key])}</td></tr>
          </Fragment>
        })}
      </tbody><tfoot><tr><td colSpan={6}>Нийт илүү цагийн хөлс</td><td>{formatAmount(month.overtime_pay)}</td></tr></tfoot></table>
      <small>Цагийн үнэлгээ = үндсэн цалин ÷ {formatHours(row.result.planned_hours)} цаг = {formatAmount(row.result.hourly_rate)} ₮ (Хөдөлмөрийн тухай хууль 109.1, 109.2, 109.4).</small>
      {manualHours && <small className="mp-manual-note">Тооцоолсон: {formatHours(Object.values(row.inputs._source_snapshot?.overtime_hours || {}).reduce((sum: number, value) => sum + toNumber(value), 0))} цаг · Гараар: {formatHours(overtimeTotal(row))} цаг</small>}
    </div>}
  </span>
}

function Cell({ column, row, index, editing }: { column: Column; row: Row; index: number; editing: boolean }) {
  const content = column.render ? column.render(row, editing) : (() => {
    const value = column.value(row, index)
    if (column.kind === 'money') return formatAmount(value)
    if (column.kind === 'hours') return formatHours(value)
    return value as ReactNode
  })()
  const overtimeCell = ['worked_normal_hours', 'overtime_hours', 'overtime_pay'].includes(column.key)
  const buckets = overtimeCell ? activeBuckets(row) : []
  const classes = [
    column.kind === 'text' ? 'mp-text' : 'mp-num', column.sticky ? `mp-sticky-${column.sticky}` : '',
    buckets.length === 1 ? `mp-ot-${buckets[0].key}` : buckets.length > 1 ? 'mp-ot-multi' : '',
    column.key === 'net_pay' && toNumber(column.value(row, index)) < 0 ? 'mp-negative' : '',
    column.key === 'net_pay' || column.key === 'advance' ? 'mp-key' : '',
  ].filter(Boolean).join(' ')
  const manual = column.manual?.(row)
  const body = <>{content}{manual && <span className="mp-manual-dot" title="Гараар зассан" aria-label="Гараар зассан" />}</>
  if (column.sticky === 'index' || column.sticky === 'name') return <th scope="row" className={classes}>{body}</th>
  return <td className={classes}>{overtimeCell && !editing ? <OvertimeInfo row={row}>{body}</OvertimeInfo> : body}</td>
}

type MenuItem = { label: string; icon?: ReactNode; onClick: () => void; disabled?: boolean; danger?: boolean; hidden?: boolean; file?: boolean }

/** Secondary run actions collapsed into one menu so the header stays one line. */
function ActionMenu({ items }: { items: MenuItem[] }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent) => { if (!ref.current?.contains(event.target as Node)) setOpen(false) }
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', escape) }
  }, [open])
  const shown = items.filter((item) => !item.hidden)
  if (!shown.length) return null
  return <div className="mp-menu" ref={ref}>
    <button type="button" className="payroll-v2-button secondary compact" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((value) => !value)}><MoreHorizontal size={14} />Бусад</button>
    {open && <div className="mp-menu-list" role="menu">{shown.map((item) => <button key={item.label} type="button" role="menuitem" className={item.danger ? 'danger' : undefined} disabled={item.disabled} onClick={() => { setOpen(false); item.onClick() }}>{item.icon}{item.label}</button>)}</div>}
  </div>
}

export function RunRegister({ runId }: { runId: number }) {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const run = useMonthlyPayrollRun(runId)
  const month = useMonthlyPayrollMonth(run.data?.month_id)
  const caps = usePayrollCapabilities()
  const calculate = useCalculateMonthlyPayrollRun()
  const approve = useApproveMonthlyPayrollRun()
  const unapprove = useUnapproveMonthlyPayrollRun()
  const approveRow = useApproveMonthlyPayrollRow(runId)
  const unapproveRow = useUnapproveMonthlyPayrollRow(runId)
  const pay = useMarkMonthlyPayrollPaid()
  const unpay = useMarkMonthlyPayrollUnpaid()
  const reopen = useReopenMonthlyPayrollRun()
  const deleteRun = useDeleteMonthlyPayrollRun()
  const refreshAdvances = useRefreshMonthlyPayrollAdvances()
  const refreshTime = useRefreshMonthlyPayrollTime()
  const syncWorkers = useSyncMonthlyPayrollWorkers()
  const importInputs = useImportMonthlyPayrollInputs(runId)
  const flagRow = useFlagMonthlyPayrollRow(runId)
  const unflagRow = useUnflagMonthlyPayrollRow(runId)
  const acceptHR = useAcceptMonthlyPayrollHRChange(runId)
  const addWorkers = useAddMonthlyPayrollRunWorkers(runId)
  const save = useSaveMonthlyPayrollRow(runId)
  const [reasonDialog, askReason] = useReasonDialog()
  const fileRef = useRef<HTMLInputElement | null>(null)
  const [search, setSearch] = useState('')
  const [department, setDepartment] = useState('')
  const [filter, setFilter] = useState(params.get('status') || 'all')
  const [preset, setPreset] = useState<'full' | 'short'>(() => { try { return (localStorage.getItem('mp-register-preset') as 'full' | 'short') || 'full' } catch { return 'full' } })
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [editing, setEditing] = useState<number | null>(null)
  const [draft, setDraft] = useState<Draft>({})
  const [drawerRow, setDrawerRow] = useState<number | null>(Number(params.get('row')) || null)
  const [summary, setSummary] = useState<MonthlyPayrollApprovalSummary | null>(null)
  const [adding, setAdding] = useState(false)
  const [addIds, setAddIds] = useState<number[]>([])
  const workers = useWorkerDirectory(adding)
  useEffect(() => { try { localStorage.setItem('mp-register-preset', preset) } catch { /* preference only */ } }, [preset])
  useEffect(() => {
    if (editing === null) return
    const cancel = (event: KeyboardEvent) => { if (event.key === 'Escape') setEditing(null) }
    window.addEventListener('keydown', cancel)
    return () => window.removeEventListener('keydown', cancel)
  }, [editing])

  const data = run.data
  const rows = data?.rows || []
  const isFinal = data?.run_type === 'final'
  const capabilities = caps.data?.capabilities || {}
  const monthOpen = month.data?.status === 'open'
  const editable = data?.status === 'draft' && Boolean(capabilities.create)
  const canApprove = data?.status === 'draft' && Boolean(capabilities.approve)
  const approvedCount = rows.filter((row) => row.status === 'approved').length
  const unapprovedCount = rows.length - approvedCount
  const hasWorkedToDate = rows.some((row) => (row.result.advance_basis || row.profile.advance_basis) === 'WORKED-TO-DATE')

  const departments = useMemo(() => Array.from(new Set(rows.map((row) => row.identity.department || 'Бусад'))).sort((a, b) => a.localeCompare(b, 'mn')), [rows])
  const activeFilter = FILTERS.find((item) => item.key === filter) || FILTERS[0]
  const visibleRows = rows.filter((row) => {
    const text = search.trim().toLocaleLowerCase()
    return (!text || `${row.identity.name || ''} ${row.identity.job_title || ''} ${row.identity.rd || ''}`.toLocaleLowerCase().includes(text))
      && (!department || (row.identity.department || 'Бусад') === department) && activeFilter.test(row)
  })
  const groups = useMemo(() => {
    const map = new Map<string, Row[]>()
    for (const row of [...visibleRows].sort((a, b) => (a.identity.name || '').localeCompare(b.identity.name || '', 'mn'))) {
      const key = row.identity.department || 'Бусад'
      map.set(key, [...(map.get(key) || []), row])
    }
    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b, 'mn'))
  }, [visibleRows])
  const numbering = useMemo(() => new Map(groups.flatMap(([, list]) => list).map((row, position) => [row.employee_id, position + 1])), [groups])

  const startEdit = (row: Row) => {
    setEditing(row.employee_id)
    setDraft({
      worked_normal_hours: plainNumber(row.inputs.worked_normal_hours), worked_days: plainNumber(row.inputs.worked_days), leave_pay: plainNumber(row.inputs.leave_pay), bonus: plainNumber(row.inputs.bonus),
      overtime_hours: Object.fromEntries(Object.entries(row.inputs.overtime_hours || {}).map(([key, value]) => [key, plainNumber(value)])), worked_to_date_hours: plainNumber(row.inputs.worked_to_date_hours),
      advance_basis: row.inputs.advance_basis || row.result.advance_basis || row.profile.advance_basis,
      advance_value: plainNumber(row.inputs.fixed_advance ?? row.inputs.advance_percent ?? row.result.advance_value),
    })
  }
  const saveEdit = async (row: Row) => {
    const payload: Record<string, unknown> = { employeeId: row.employee_id, reason: 'Нягтлангийн засвар' }
    // Blank worked days keeps the server's estimate from hours.
    if (draft.worked_days !== '' && draft.worked_days !== undefined) payload.worked_days = draft.worked_days
    Object.assign(payload, { worked_normal_hours: draft.worked_normal_hours || '0', leave_pay: draft.leave_pay || '0', bonus: draft.bonus || '0', overtime_hours: Object.fromEntries(Object.entries(draft.overtime_hours || {}).map(([key, value]) => [key, value || '0'])) })
    if (!isFinal) {
      payload.advance_basis = draft.advance_basis
      if (draft.advance_basis === 'WORKED-TO-DATE') payload.worked_to_date_hours = draft.worked_to_date_hours || '0'
      else if (draft.advance_value !== '' && toNumber(draft.advance_value) > 0) payload[draft.advance_basis === 'PERCENT' ? 'advance_percent' : 'fixed_advance'] = draft.advance_value
    }
    try { await save.mutateAsync(payload as any); setEditing(null); toast.success('Мөр хадгалагдлаа') } catch (error) { toast.error(requestError(error)) }
  }
  const setDraftValue = (key: string, value: unknown) => setDraft((current) => ({ ...current, [key]: value }))
  const numberInput = (label: string, value: unknown, onChange: (value: string) => void) => <input className="mp-inline-input" aria-label={label} type="text" inputMode="decimal" value={String(value ?? '')} onChange={(event) => onChange(event.target.value.replace(/[^\d.]/g, ''))} />

  // Plan §7.2: Excel order; the name cell carries the job title only when that column is hidden.
  const nameColumn: Column = { key: 'name', label: 'Овог, Нэр', kind: 'text', short: true, sticky: 'name', value: displayName, render: (row) => <span className="mp-name">{displayName(row)}{preset === 'short' && row.identity.job_title ? <small>{row.identity.job_title}</small> : null}</span> }
  const identityColumns: Column[] = [
    { key: 'index', label: '№', kind: 'text', short: true, sticky: 'index', value: (_row, index) => index },
    nameColumn,
    { key: 'rd', label: 'РД', kind: 'text', value: (row) => row.identity.rd || '—' },
    { key: 'job_title', label: 'Албан тушаал', kind: 'text', value: (row) => row.identity.job_title || '—' },
    { key: 'base_salary', label: 'Үндсэн цалин', kind: 'money', value: (row) => row.profile.base_salary },
  ]
  // Plan §7.2 Excel order. Advance rows show the same month columns from their
  // full-month projection, so Суутгалын дүн = урьдчилгаа + НДШ + ХХОАТ there too.
  const workedTitle = (row: Row) => isFinal ? undefined : `${data?.cutoff_date || 'Таслах өдөр'} хүртэл ${formatHours(row.inputs.worked_to_date_hours)} цаг + үлдсэн ${formatHours(row.inputs.projected_remaining_hours)} цаг`
  const advanceTitle = (row: Row) => isFinal
    ? ((row.result.advance_lines || []).length ? `${row.result.advance_lines.length} батлагдсан урьдчилгааны бодолтоос` : undefined)
    : (toNumber(monthFigures(row).prior_advances) > 0 ? `Өмнөх урьдчилгаа ${formatAmount(monthFigures(row).prior_advances)} ₮ суутгалын дүнд орсон` : undefined)
  const monthColumns: Column[] = [
    { key: 'planned_days', label: 'Өдөр', group: 'Ажиллах', kind: 'days', value: (row) => row.result.planned_days ?? '—' },
    { key: 'planned_hours', label: 'Цаг', group: 'Ажиллах', kind: 'hours', value: (row) => row.result.planned_hours },
    { key: 'worked_normal_hours', label: 'Ажилласан цаг', kind: 'hours', short: true, value: (row) => row.inputs.worked_normal_hours, manual: (row) => sourceDiffers(row, 'worked_normal_hours'), render: (row, isEditing) => isEditing ? numberInput('Ажилласан цаг', draft.worked_normal_hours, (value) => setDraftValue('worked_normal_hours', value)) : <span title={workedTitle(row)}>{formatHours(row.inputs.worked_normal_hours)}</span> },
    { key: 'worked_days', label: 'Ажилласан өдөр', kind: 'days', value: (row) => row.inputs.worked_days ?? monthFigures(row).allowance_days, manual: (row) => sourceDiffers(row, 'worked_days'), render: (row, isEditing) => isEditing ? numberInput('Ажилласан өдөр', draft.worked_days, (value) => setDraftValue('worked_days', value)) : (row.inputs.worked_days == null ? '—' : formatHours(row.inputs.worked_days)) },
    { key: 'base_pay', label: 'Тооцсон цалин', kind: 'money', value: (row) => monthFigures(row).base_pay },
    { key: 'overtime_hours', label: 'Илүү цаг', kind: 'hours', value: overtimeTotal, manual: (row) => sourceDiffers(row, 'overtime_hours'), render: (row, isEditing) => isEditing ? <span className="mp-ot-edit">{BUCKETS.map((bucket) => <label key={bucket.key} title={bucket.label}><b className={`mp-ot-mark ${bucket.key}`}>{bucket.mark}</b><input className="mp-inline-input" aria-label={bucket.label} type="text" inputMode="decimal" value={String(draft.overtime_hours?.[bucket.key] ?? '')} onChange={(event) => setDraftValue('overtime_hours', { ...draft.overtime_hours, [bucket.key]: event.target.value.replace(/[^\d.]/g, '') })} /></label>)}</span> : formatHours(overtimeTotal(row)) },
    { key: 'overtime_pay', label: 'Илүү цагийн хөлс', kind: 'money', value: (row) => monthFigures(row).overtime_pay },
    { key: 'leave_pay', label: 'Ээлжийн амралтын мөнгө', kind: 'money', value: (row) => row.inputs.leave_pay, manual: (row) => toNumber(row.inputs.leave_pay) > 0, render: (row, isEditing) => isEditing ? numberInput('Ээлжийн амралтын мөнгө', draft.leave_pay, (value) => setDraftValue('leave_pay', value)) : formatAmount(row.inputs.leave_pay) },
    { key: 'meal_commute', label: 'Хоол унаа', kind: 'money', value: (row) => monthFigures(row).meal_commute },
    { key: 'bonus', label: 'Урамшуулал', kind: 'money', value: (row) => row.inputs.bonus, manual: (row) => toNumber(row.inputs.bonus) > 0, render: (row, isEditing) => isEditing ? numberInput('Урамшуулал', draft.bonus, (value) => setDraftValue('bonus', value)) : formatAmount(row.inputs.bonus) },
    { key: 'gross', label: 'Олговол зохих цалин', kind: 'money', short: true, value: (row) => monthFigures(row).gross, manual: (row) => isFinal && overridden(row, 'gross') },
    { key: 'employee_shi', label: 'НДШ', group: 'Суутгалууд', kind: 'money', value: (row) => monthFigures(row).employee_shi, manual: (row) => isFinal && overridden(row, 'employee_shi') },
    { key: 'relief', label: 'ХХОАТ ХӨН', group: 'Суутгалууд', kind: 'money', value: (row) => monthFigures(row).relief },
    { key: 'pit', label: 'ХХОАТ', group: 'Суутгалууд', kind: 'money', value: (row) => monthFigures(row).pit, manual: (row) => isFinal && overridden(row, 'pit') },
    { key: 'advance', label: 'Урьдчилгаа', group: 'Суутгалууд', kind: 'money', short: true, value: (row) => row.result.advance, manual: (row) => overridden(row, 'advance') || (!isFinal && Boolean(row.inputs.fixed_advance || row.inputs.advance_percent)), render: (row) => <span title={advanceTitle(row)}>{formatAmount(row.result.advance)}</span> },
  ]
  const finalColumns: Column[] = [
    ...identityColumns,
    ...monthColumns,
    { key: 'other_deductions', label: 'Бусад суутгал', group: 'Суутгалууд', kind: 'money', value: (row) => row.result.other_deductions, manual: (row) => (row.inputs.other_deductions || []).length > 0 || overridden(row, 'other_deductions') },
    { key: 'total_deductions', label: 'Суутгалын дүн', kind: 'money', short: true, value: (row) => row.result.total_deductions },
    { key: 'net_pay', label: 'Сүүл цалин (Гарт олгох)', kind: 'money', short: true, value: (row) => row.result.net_pay },
    { key: 'employer_shi', label: 'БНДШ', kind: 'money', value: (row) => row.result.employer_shi, manual: (row) => overridden(row, 'employer_shi') },
  ]
  // Plan §7.1 basis columns first; the cut-off hours column appears only for WORKED-TO-DATE workers.
  const advanceColumns: Column[] = [
    ...identityColumns,
    { key: 'salary_type', label: 'Төрөл', kind: 'text', value: (row) => SALARY_TYPES[String(row.profile.salary_type)] || row.profile.salary_type },
    { key: 'advance_basis', label: 'Суурь', group: 'Урьдчилгааны тооцоо', kind: 'text', value: (row) => BASIS_LABELS[row.result.advance_basis] || row.result.advance_basis || '—', render: (row, isEditing) => isEditing ? <select className="mp-inline-input" aria-label="Урьдчилгааны суурь" value={draft.advance_basis} onChange={(event) => setDraftValue('advance_basis', event.target.value)}>{Object.entries(BASIS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select> : (BASIS_LABELS[row.result.advance_basis] || row.result.advance_basis || '—') },
    { key: 'advance_value', label: 'Хувь / дүн', group: 'Урьдчилгааны тооцоо', kind: 'text', manual: (row) => Boolean(row.inputs.fixed_advance || row.inputs.advance_percent), value: (row) => row.result.advance_value, render: (row, isEditing) => isEditing ? (draft.advance_basis === 'WORKED-TO-DATE' ? '—' : numberInput('Хувь эсвэл дүн', draft.advance_value, (value) => setDraftValue('advance_value', value))) : row.result.advance_basis === 'PERCENT' ? `${formatHours(row.result.advance_value)}%` : row.result.advance_basis === 'FIXED' ? formatAmount(row.result.advance_value) : '—' },
    ...(hasWorkedToDate ? [{ key: 'worked_to_date_hours', label: 'Таслах өдөр хүртэл цаг', group: 'Урьдчилгааны тооцоо', kind: 'hours' as Kind, value: (row: Row) => (row.result.advance_basis === 'WORKED-TO-DATE' ? row.inputs.worked_to_date_hours : 0), manual: (row: Row) => sourceDiffers(row, 'worked_to_date_hours'), render: (row: Row, isEditing: boolean) => isEditing && draft.advance_basis === 'WORKED-TO-DATE' ? numberInput('Таслах өдөр хүртэл ажилласан цаг', draft.worked_to_date_hours, (value) => setDraftValue('worked_to_date_hours', value)) : row.result.advance_basis === 'WORKED-TO-DATE' ? formatHours(row.inputs.worked_to_date_hours) : '—' }] : []),
    ...monthColumns,
    { key: 'total_deductions', label: 'Суутгалын дүн', kind: 'money', short: true, value: (row) => monthFigures(row).total_deductions },
    { key: 'net_pay', label: 'Сүүл цалин (тооцоолсон)', kind: 'money', short: true, value: (row) => monthFigures(row).net_pay },
    { key: 'pay_date', label: 'Төлбөрийн өдөр', kind: 'text', value: (row) => row.identity.pay_date || data?.pay_date },
  ]
  const columns = (isFinal ? finalColumns : advanceColumns).filter((column) => preset === 'full' || column.short)
  const grouped = preset === 'full' && columns.some((column) => column.group)
  const sumColumns = new Set(columns.filter((column) => column.kind === 'money' || column.kind === 'hours').map((column) => column.key).filter((key) => !['base_salary', 'planned_hours'].includes(key)))
  const sumOf = (list: Row[], column: Column) => list.reduce((total, row, index) => total + toNumber(column.value(row, index)), 0)
  const totalCell = (list: Row[], column: Column) => sumColumns.has(column.key) ? (column.kind === 'hours' ? formatHours(sumOf(list, column)) : formatAmount(sumOf(list, column))) : ''

  const runAction = async (task: Promise<unknown>, success: string) => { try { await task; toast.success(success) } catch (error) { toast.error(requestError(error)) } }
  const approveAll = async () => {
    try {
      const result = await approve.mutateAsync(runId)
      const outcome = result.approval_summary || { approved: 0, skipped: [] }
      setSummary(outcome.skipped.length ? outcome : null)
      toast.success(outcome.skipped.length ? `${outcome.approved} мөр батлагдлаа · ${outcome.skipped.length} мөр шалгалтад үлдлээ` : 'Бүх мөр батлагдлаа')
    } catch (error) { toast.error(requestError(error)) }
  }
  const flag = async (row: Row) => { const reason = await askReason(`${displayName(row)} — шалгах тэмдэглэгээ`, 'Юуг шалгах вэ?', 'Тэмдэглэх'); if (reason) runAction(flagRow.mutateAsync({ employeeId: row.employee_id, reason }), 'Мөрийг шалгахаар тэмдэглэлээ') }
  const reopenRun = async () => { const reason = await askReason(data?.status === 'paid' ? 'Төлсөн бодолтыг дахин нээх' : 'Баталсан бодолтыг дахин нээх', 'Шалтгаан', 'Нээх'); if (reason) runAction(reopen.mutateAsync({ id: runId, reason }), 'Бодолт ноорог төлөвт орлоо') }

  if (run.isLoading || !data) return <MonthlyShell><div className="payroll-v2-loading">{run.error ? requestError(run.error) : 'Бодолт ачаалж байна…'}</div></MonthlyShell>

  const monthValue = month.data ? monthKey(month.data.year, month.data.month) : data.pay_date.slice(0, 7)
  const removeRun = async () => {
    const reason = await askReason(`«${runTitle(data)}» бодолтыг устгах`, 'Устгах шалтгаан (бүх мөр, засварын түүх устана)', 'Устгах')
    if (!reason) return
    try { await deleteRun.mutateAsync({ id: runId, reason }); toast.success('Бодолт устгагдлаа. Шинээр үүсгэж болно.'); navigate(`/erp/payroll/monthly?month=${monthValue}`) } catch (error) { toast.error(requestError(error)) }
  }
  const incomplete = rows.filter((row) => row.warnings.some((warning) => PROFILE_WARNINGS.includes(warning)))
  const hrChanged = rows.filter((row) => row.warnings.includes('hr_changed'))
  const advanceChanged = rows.filter((row) => row.warnings.includes('advance_changed')).length
  const advanceMissing = rows.filter((row) => row.warnings.includes('advance_not_calculated')).length
  const advanceRuns = (month.data?.runs || []).filter((item) => item.run_type === 'advance')
  const withTime = rows.filter((row) => row.inputs.time_source && row.inputs.time_source !== 'manual').length
  const checklist = isFinal ? [
    { label: 'Урьдчилгаа батлагдсан', done: advanceRuns.every((item) => ['approved', 'paid', 'closed', 'waived'].includes(item.status)), detail: advanceRuns.length ? `${advanceRuns.filter((item) => item.status !== 'draft').length}/${advanceRuns.length}` : 'бодолтгүй' },
    { label: 'Цаг татсан', done: rows.every((row) => row.inputs.time_source !== 'manual' || toNumber(row.inputs.worked_normal_hours) > 0), detail: `${withTime}/${rows.length}` },
    { label: 'Илүү цаг', done: true, detail: `${rows.filter((row) => row.warnings.includes('overtime_work')).length}` },
    { label: 'Гар оролт', done: true, detail: `${rows.filter((row) => toNumber(row.inputs.leave_pay) || toNumber(row.inputs.bonus) || (row.inputs.other_deductions || []).length).length}` },
  ] : []
  const drawer = rows.find((row) => row.employee_id === drawerRow)
  const exportDisabled = data.status === 'draft'
  const canDelete = monthOpen && Boolean(capabilities.create) && ['draft', 'approved'].includes(data.status)
  const progress = rows.length ? Math.round((approvedCount * 100) / rows.length) : 0

  const menu: MenuItem[] = [
    { label: 'Ажилчид шинэчлэх', icon: <RefreshCw size={13} />, hidden: !editable, disabled: syncWorkers.isPending, onClick: () => syncWorkers.mutate(runId, { onSuccess: (result) => toast.success(`${result.added_workers || 0} ажилтан нэмэгдлээ · ${result.hr_changed_rows || 0} мөрөнд HR өөрчлөлт`), onError: (error) => toast.error(requestError(error)) }) },
    { label: 'Дахин бодох', icon: <RefreshCw size={13} />, hidden: !editable || !capabilities.calculate, disabled: calculate.isPending, onClick: () => runAction(calculate.mutateAsync(runId), 'Дахин бодлоо (батлагдсан мөр өөрчлөгдөөгүй)') },
    { label: 'Ажилтан нэмэх', icon: <UserPlus size={13} />, hidden: !editable || isFinal, onClick: () => setAdding((value) => !value) },
    { label: 'Урьдчилгаа дахин татах', icon: <RefreshCw size={13} />, hidden: !editable || !isFinal, disabled: refreshAdvances.isPending, onClick: () => runAction(refreshAdvances.mutateAsync(runId), 'Урьдчилгаа дахин татагдлаа') },
    { label: 'Оролтын загвар (Excel)', icon: <Download size={13} />, hidden: !editable || !capabilities.export, onClick: () => { downloadMonthlyPayrollInputTemplate(runId).catch((error) => toast.error(requestError(error))) } },
    { label: 'Excel оролт оруулах', icon: <Upload size={13} />, hidden: !editable, disabled: importInputs.isPending, onClick: () => fileRef.current?.click() },
    { label: 'Батлалт цуцлах', hidden: !(data.status === 'approved' && monthOpen && capabilities.approve), disabled: unapprove.isPending, onClick: () => runAction(unapprove.mutateAsync(runId), 'Батлалт цуцлагдлаа') },
    { label: 'Төлсөнийг буцаах', hidden: !(data.status === 'paid' && monthOpen && capabilities.pay), disabled: unpay.isPending, onClick: () => runAction(unpay.mutateAsync(runId), 'Төлөөгүй болголоо') },
    { label: 'Дахин нээх', icon: <LockKeyhole size={13} />, hidden: !(['approved', 'paid'].includes(data.status) && monthOpen && capabilities.administer), disabled: reopen.isPending, onClick: reopenRun },
    { label: 'Сар хаах', icon: <LockKeyhole size={13} />, hidden: !(isFinal && monthOpen), onClick: () => navigate(`/erp/payroll/monthly?month=${monthValue}&close=1`) },
    { label: 'Архив', onClick: () => navigate('/erp/payroll/monthly/archive') },
    { label: 'Бодолт устгах', icon: <Trash2 size={13} />, danger: true, hidden: !canDelete, disabled: deleteRun.isPending, onClick: removeRun },
  ]

  const notices: ReactNode[] = []
  if (incomplete.length) notices.push(<div key="profile" className="mp-strip danger"><CircleAlert size={14} /><span><strong>{incomplete.length} ажилтны цалингийн профайл дутуу</strong> — {incomplete.slice(0, 3).map(displayName).join(', ')}{incomplete.length > 3 ? '…' : ''}</span><Link to="/hr?tab=directory">HR профайл</Link></div>)
  if (hrChanged.length) notices.push(<div key="hr" className="mp-strip info"><Info size={14} /><span><strong>{hrChanged.length} мөрөнд HR мэдээлэл өөрчлөгдсөн</strong> — мөр бүрийн «HR» товчоор хүлээн авна.</span></div>)
  if (isFinal && (advanceChanged || advanceMissing)) notices.push(<div key="advance" className="mp-strip warning"><CircleAlert size={14} /><span><strong>Урьдчилгаа: {advanceChanged} өөрчлөгдсөн · {advanceMissing} бодоогүй</strong></span>{editable && advanceChanged > 0 && <button className="payroll-v2-button secondary compact" disabled={refreshAdvances.isPending} onClick={() => runAction(refreshAdvances.mutateAsync(runId), 'Урьдчилгаа дахин татагдлаа')}><RefreshCw size={12} />Дахин татах</button>}</div>)
  if (summary) notices.push(<div key="summary" className="mp-strip warning"><CircleAlert size={14} /><span><strong>{summary.skipped.length} мөр батлагдаагүй:</strong> {summary.skipped.map((item) => `${item.employee_name || item.employee_id} (${item.message || item.issues.map(warningLabel).join(', ')})`).join(' · ')}</span><button type="button" className="mp-icon-button" aria-label="Хаах" onClick={() => setSummary(null)}><X size={13} /></button></div>)
  if (adding && editable) notices.push(<div key="adding" className="mp-strip info"><UserPlus size={14} /><label className="mp-add-workers">Нэг удаагийн урьдчилгаа авах ажилтан<select multiple value={addIds.map(String)} onChange={(event) => setAddIds(Array.from(event.currentTarget.selectedOptions, (option) => Number(option.value)))}>{(workers.data || []).filter((worker) => !rows.some((row) => row.employee_id === worker.id)).map((worker) => <option key={worker.id} value={worker.id}>{worker.name}</option>)}</select><small>Ctrl / ⌘ дарж олныг сонгоно.</small></label><button className="payroll-v2-button primary compact" disabled={!addIds.length || addWorkers.isPending} onClick={() => addWorkers.mutate(addIds, { onSuccess: (result) => { toast.success(`${result.added_workers} ажилтан нэмэгдлээ`); setAdding(false); setAddIds([]) }, onError: (error) => toast.error(requestError(error)) })}>Нэмэх</button><button type="button" className="mp-icon-button" aria-label="Хаах" onClick={() => setAdding(false)}><X size={13} /></button></div>)

  const header = <div className="mp-run-header">
    <div className="mp-month-stepper">
      <button type="button" className="mp-icon-button" aria-label="Өмнөх сар" onClick={() => navigate(`/erp/payroll/monthly?month=${shiftMonth(monthValue, -1)}`)}>◀</button>
      <Link to={`/erp/payroll/monthly?month=${monthValue}`} className="mp-month-link">{monthValue}</Link>
      <button type="button" className="mp-icon-button" aria-label="Дараах сар" onClick={() => navigate(`/erp/payroll/monthly?month=${shiftMonth(monthValue, 1)}`)}>▶</button>
    </div>
    <h1>{runTitle(data)}</h1>
    <RunStatusChip status={data.status} />
    <span className="mp-progress" aria-label="Батлалтын явц"><span className="mp-progress-bar"><i style={{ width: `${progress}%` }} /></span>{approvedCount}/{rows.length} батлагдсан</span>
    <div className="mp-run-actions">
      {editable && <button className="payroll-v2-button secondary compact" disabled={refreshTime.isPending} title="Ажилтны цагийн бүртгэл, ирцээс ажилласан цагийг дахин татна" onClick={() => runAction(refreshTime.mutateAsync(runId), 'Цагийн бүртгэлээс татлаа')}><RefreshCw size={13} />Цагийн бүртгэлээс татах</button>}
      {canApprove && <button className="payroll-v2-button primary compact" disabled={approve.isPending || unapprovedCount === 0} onClick={approveAll}><Check size={13} />Бүгдийг батлах</button>}
      {data.status === 'approved' && Boolean(capabilities.pay) && <button className="payroll-v2-button primary compact" disabled={pay.isPending} onClick={() => runAction(pay.mutateAsync(runId), 'Төлсөн гэж тэмдэглэлээ')}>Төлсөн</button>}
      {Boolean(capabilities.export) && <span title={exportDisabled ? `${unapprovedCount} мөр батлагдаагүй` : undefined}><button className="payroll-v2-button secondary compact" disabled={exportDisabled} onClick={() => downloadMonthlyPayrollExport(runId).catch((error) => toast.error(requestError(error)))}><Download size={13} />Excel татах</button></span>}
      <ActionMenu items={menu} />
    </div>
  </div>

  const rowActions = (row: Row, isEditing: boolean) => {
    const blocking = row.warnings.filter((warning) => BLOCKING_WARNINGS.has(warning))
    if (isEditing) return <>
      <button type="button" className="mp-icon-button primary" aria-label="Хадгалах" title="Хадгалах (Enter)" disabled={save.isPending} onClick={() => saveEdit(row)}><Check size={13} /></button>
      <button type="button" className="mp-icon-button" aria-label="Болих" title="Болих (Esc)" onClick={() => setEditing(null)}><X size={13} /></button>
    </>
    return <>
      {canApprove && row.status === 'draft' && <button type="button" className="mp-icon-button approve" aria-label="Батлах" title={blocking.length ? `Батлах боломжгүй: ${blocking.map(warningLabel).join(', ')}` : 'Батлах'} disabled={approveRow.isPending || blocking.length > 0} onClick={() => runAction(approveRow.mutateAsync(row.employee_id), 'Мөр батлагдлаа')}><Check size={13} /></button>}
      {canApprove && row.status === 'approved' && <button type="button" className="mp-icon-button" aria-label="Батлалт цуцлах" title="Батлалт цуцлах" disabled={unapproveRow.isPending} onClick={() => runAction(unapproveRow.mutateAsync(row.employee_id), 'Мөрийн батлалт цуцлагдлаа')}>↺</button>}
      {editable && row.status === 'draft' && <button type="button" className="mp-icon-button flag" aria-label="Шалгах тэмдэглэх" title="Шалгах тэмдэглэх" onClick={() => flag(row)}><X size={13} /></button>}
      {editable && row.status === 'flagged' && <button type="button" className="mp-icon-button" aria-label="Тэмдэглэгээ арилгах" title={`Тэмдэглэгээ арилгах: ${row.inputs.flag_reason || ''}`} onClick={() => runAction(unflagRow.mutateAsync(row.employee_id), 'Тэмдэглэгээ арилгалаа')}>⚑</button>}
      {editable && row.profile.complete !== false && <button type="button" className="mp-icon-button" aria-label="Засах" title={row.status === 'approved' ? 'Засвал мөр дахин ноорог болно' : 'Засах'} onClick={() => startEdit(row)}><Pencil size={12} /></button>}
      {editable && row.warnings.includes('hr_changed') && <button type="button" className="mp-icon-button" aria-label="HR өөрчлөлт хүлээн авах" title="HR өөрчлөлт хүлээн авах" disabled={acceptHR.isPending} onClick={() => runAction(acceptHR.mutateAsync(row.employee_id), 'HR өөрчлөлтийг хүлээн авлаа')}>HR</button>}
      <button type="button" className="mp-icon-button" aria-label="Тооцооны дэлгэрэнгүй" title="Тооцооны дэлгэрэнгүй" onClick={() => setDrawerRow(row.employee_id)}><Info size={13} /></button>
    </>
  }
  const stateCell = (row: Row) => {
    const warnings = visibleWarnings(row)
    const first = warnings.find((warning) => BLOCKING_WARNINGS.has(warning)) || warnings[0]
    return <td className="mp-state" title={warnings.map(warningLabel).join('\n') || undefined}>
      <RowStateChip row={row} />
      {first && <small className={BLOCKING_WARNINGS.has(first) ? 'mp-warning blocking' : 'mp-warning'}>{warningLabel(first)}{warnings.length > 1 ? ` +${warnings.length - 1}` : ''}</small>}
    </td>
  }

  // One header block: ungrouped columns span both rows, so the grouped
  // Ажиллах / Суутгалууд labels sit above their own columns only.
  const groupCells = columns.reduce<Array<{ column?: Column; label: string; span: number }>>((cells, column) => {
    const previous = cells[cells.length - 1]
    if (!column.group || !grouped) cells.push({ column, label: column.label, span: 1 })
    else if (previous && !previous.column && previous.label === column.group) previous.span += 1
    else cells.push({ label: column.group, span: 1 })
    return cells
  }, [])
  const headClass = (column: Column) => `${column.kind === 'text' ? 'mp-text' : 'mp-num'}${column.sticky ? ` mp-sticky-${column.sticky}` : ''}`

  return <MonthlyShell canAdminister={Boolean(capabilities.administer)}>
    {reasonDialog}
    {header}
    {isFinal && <ul className="mp-checklist" aria-label="Сүүл цалингийн шалгах жагсаалт">{checklist.map((item) => <li key={item.label} className={item.done ? 'done' : 'pending'}>{item.done ? <Check size={12} /> : <CircleAlert size={12} />}{item.label}<small>{item.detail}</small></li>)}</ul>}
    {notices}
    <input ref={fileRef} type="file" accept=".xlsx" hidden onChange={(event) => { const file = event.currentTarget.files?.[0]; if (file) importInputs.mutate(file, { onSuccess: (result) => toast.success(`${result.updated_rows} мөр шинэчлэгдлээ`), onError: (error) => toast.error(requestError(error)) }); event.currentTarget.value = '' }} />

    <section className="mp-register">
      <div className="mp-register-toolbar">
        <input className="mp-search" aria-label="Хайх" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Нэр, албан тушаал, РД хайх" />
        {departments.length > 1 && <select aria-label="Хэлтэс" value={department} onChange={(event) => setDepartment(event.target.value)}><option value="">Бүх хэлтэс</option>{departments.map((name) => <option key={name}>{name}</option>)}</select>}
        <div className="mp-segmented" role="group" aria-label="Төлвөөр шүүх">{FILTERS.map((item) => { const count = rows.filter(item.test).length; if (item.key !== 'all' && item.key !== filter && !count) return null; return <button key={item.key} type="button" className={filter === item.key ? 'active' : ''} aria-pressed={filter === item.key} onClick={() => { setFilter(item.key); setParams((current) => { const next = new URLSearchParams(current); if (item.key === 'all') next.delete('status'); else next.set('status', item.key); return next }, { replace: true }) }}>{item.label}<small>{count}</small></button> })}</div>
        <div className="mp-segmented mp-preset" role="group" aria-label="Баганын багц"><button type="button" className={preset === 'full' ? 'active' : ''} aria-pressed={preset === 'full'} onClick={() => setPreset('full')}>Бүрэн</button><button type="button" className={preset === 'short' ? 'active' : ''} aria-pressed={preset === 'short'} onClick={() => setPreset('short')}>Товч</button></div>
      </div>
      <div className="mp-table-wrap">
        <table className={`mp-table${grouped ? ' mp-grouped' : ''}`}>
          <thead>
            <tr>
              {groupCells.map((cell, index) => cell.column
                ? <th key={cell.column.key} scope="col" rowSpan={grouped ? 2 : 1} className={headClass(cell.column)}>{cell.label}</th>
                : <th key={`group-${index}`} scope="colgroup" colSpan={cell.span} className="mp-group-head">{cell.label}</th>)}
              <th scope="col" rowSpan={grouped ? 2 : 1} className="mp-text">Төлөв</th>
              <th scope="col" rowSpan={grouped ? 2 : 1}><span className="sr-only">Үйлдэл</span></th>
            </tr>
            {grouped && <tr className="mp-subhead">{columns.filter((column) => column.group).map((column) => <th key={column.key} scope="col" className={headClass(column)}>{column.label}</th>)}</tr>}
          </thead>
          <tbody>
            {groups.map(([name, groupRows]) => {
              const closed = collapsed.has(name)
              const showDepartment = groups.length > 1 || departments.length > 1
              return <Fragment key={name}>
                {showDepartment && <tr className="mp-dept-row">
                  {columns.map((column, columnIndex) => columnIndex === 0 ? null : columnIndex === 1
                    ? <th key={column.key} colSpan={2} scope="rowgroup" className="mp-sticky-label"><button type="button" aria-expanded={!closed} onClick={() => setCollapsed((current) => { const next = new Set(current); if (next.has(name)) next.delete(name); else next.add(name); return next })}>{closed ? <ChevronRight size={13} /> : <ChevronDown size={13} />}{name}<small>{groupRows.length}</small></button></th>
                    : <td key={column.key} className="mp-num">{totalCell(groupRows, column)}</td>)}
                  <td colSpan={2} className="mp-text"><small>{groupRows.filter((row) => row.status === 'approved').length}/{groupRows.length} батлагдсан</small></td>
                </tr>}
                {!closed && groupRows.map((row) => {
                  const index = numbering.get(row.employee_id) || 0
                  const isEditing = editing === row.employee_id
                  const state: RowState = rowState(row)
                  return <tr key={row.employee_id} className={`mp-row mp-row-${state}${isEditing ? ' mp-row-editing' : ''}`} onKeyDown={(event) => { if (!isEditing) return; if (event.key === 'Enter') { event.preventDefault(); saveEdit(row) } if (event.key === 'Escape') setEditing(null) }}>
                    {columns.map((column) => <Cell key={column.key} column={column} row={row} index={index} editing={isEditing} />)}
                    {stateCell(row)}
                    <td className="mp-actions">{rowActions(row, isEditing)}</td>
                  </tr>
                })}
              </Fragment>
            })}
            {!visibleRows.length && <tr><td colSpan={columns.length + 2} className="mp-empty">Шүүлтэд тохирох ажилтан алга.</td></tr>}
          </tbody>
          <tfoot><tr>{columns.map((column, columnIndex) => columnIndex === 0 ? null : columnIndex === 1 ? <th key={column.key} colSpan={2} className="mp-sticky-label">{visibleRows.length === rows.length ? `Нийт · ${rows.length} ажилтан` : `Нийт · ${visibleRows.length}/${rows.length}`}</th> : <td key={column.key} className="mp-num">{totalCell(visibleRows, column)}</td>)}<td colSpan={2} /></tr></tfoot>
        </table>
      </div>
      <p className="mp-legend"><span><b className="mp-ot-mark weekday">И</b>ажлын өдрийн илүү цаг</span><span><b className="mp-ot-mark rest_day">А</b>амралтын өдөр</span><span><b className="mp-ot-mark public_holiday">Б</b>баярын өдөр</span><span><span className="mp-manual-dot" />гараар зассан</span>{!isFinal && <span>Сарын дүн (НДШ, ХХОАТ, сүүл цалин) тооцоолсон төлөв — эцсийн дүн сүүл цалингийн бодолтод гарна.</span>}</p>
    </section>
    {drawer && month.data && <RowDrawer row={drawer} run={data} month={month.data} editable={editable} onClose={() => setDrawerRow(null)} askReason={askReason} />}
  </MonthlyShell>
}
