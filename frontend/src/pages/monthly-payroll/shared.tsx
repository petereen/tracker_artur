import { useCallback, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { NavLink } from 'react-router-dom'
import type { MonthlyPayrollRunRow } from '../../api/enterprise'
import './monthlyPayroll.css'

const wholeNumber = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const hourNumber = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 })

/** Whole tugrik with thousand separators and no decimals (plan §0.4). */
export const formatMoney = (value: unknown) => `${wholeNumber.format(Math.round(Number(value || 0)))} ₮`
export const formatAmount = (value: unknown) => wholeNumber.format(Math.round(Number(value || 0)))
export const formatHours = (value: unknown) => hourNumber.format(Number(value || 0))
export const toNumber = (value: unknown) => Number(value || 0)
/** Month figures: the final result, or an advance row's full-month projection over its own fields. */
export const monthFigures = (row: MonthlyPayrollRunRow): Record<string, any> => row.result.projection ? { ...row.result, ...row.result.projection } : row.result

export const monthKey = (year: number, month: number) => `${year}-${String(month).padStart(2, '0')}`
export const parseMonthKey = (value: string | null | undefined) => {
  const match = /^(\d{4})-(\d{2})$/.exec(value || '')
  const now = new Date()
  return match ? { year: Number(match[1]), month: Number(match[2]) } : { year: now.getFullYear(), month: now.getMonth() + 1 }
}
export const shiftMonth = (key: string, delta: number) => {
  const { year, month } = parseMonthKey(key)
  const date = new Date(year, month - 1 + delta, 1)
  return monthKey(date.getFullYear(), date.getMonth() + 1)
}
export const monthTitle = (key: string) => {
  const { year, month } = parseMonthKey(key)
  return `${year} оны ${month} сар`
}
export const dayOf = (isoDate: string) => Number(isoDate.slice(8, 10))

export const RUN_STATUS_LABELS: Record<string, string> = { draft: 'Ноорог', approved: 'Батлагдсан', paid: 'Төлсөн', closed: 'Хаасан', waived: 'Чөлөөлсөн' }
export const runStatusTone = (status: string) => (status === 'paid' || status === 'closed' ? 'success' : status === 'approved' ? 'info' : status === 'waived' ? 'muted' : 'warning')
export const runTitle = (run: { run_type: string; pay_date: string }) => (run.run_type === 'advance' ? `Урьдчилгаа — ${dayOf(run.pay_date)}-ны өдөр` : 'Сүүл цалин')

/** Mirror of the backend BLOCKING_ROW_WARNINGS: these keep a row out of approval. */
export const BLOCKING_WARNINGS = new Set(['negative_final_pay', 'profile_missing', 'salary_history_missing_or_incomplete', 'row_flagged', 'advance_changed', 'advance_not_due', 'advance_not_positive'])

export const WARNING_LABELS: Record<string, string> = {
  negative_final_pay: 'Сүүл цалин сөрөг', profile_missing: 'HR цалингийн профайл алга', profile_incomplete: 'HR цалингийн профайл дутуу',
  salary_history_missing_or_incomplete: 'Цалингийн түүх дутуу', advance_changed: 'Урьдчилгаа өөрчлөгдсөн', advance_not_calculated: 'Урьдчилгаа бодоогүй',
  advance_not_due: 'Энэ өдөр урьдчилгаа авахгүй ажилтан', advance_not_positive: 'Урьдчилгаа 0 байна', zero_worked_hours: 'Ажилласан цаг 0',
  advance_above_estimated_net: 'Урьдчилгаа сарын цэвэр цалингаас их', worked_to_date_without_time: 'Ирцийн цаг алга', deduction_details_missing: 'Суутгалын төрөл/тайлбар дутуу',
  worked_hours_above_planned: 'Ажилласан цаг төлөвлөгөөнөөс их', base_below_minimum_wage: 'Үндсэн цалин доод хэмжээнээс бага', overtime_work: 'Илүү цагтай',
  computed_cell_overridden: 'Тооцсон дүнг гараар зассан', row_flagged: 'Шалгах тэмдэглэгээтэй', hr_changed: 'HR мэдээлэл өөрчлөгдсөн', shi_cap_hit: 'НДШ дээд хязгаарт хүрсэн',
  invalid_input: 'Оролт буруу', final_run_required: 'Сүүл цалингийн бодолт шаардлагатай', all_runs_must_be_approved: 'Бүх бодолт батлагдаагүй',
  all_rows_must_be_approved: 'Бүх мөр батлагдаагүй', row_payroll_equation_mismatch: 'Суутгал + сүүл цалин ≠ олговол зохих',
  advance_reconciliation_mismatch: 'Урьдчилгааны нийлбэр таарахгүй',
}
export const warningLabel = (code: string) => WARNING_LABELS[code] || code

export function requestError(error: any): string {
  const detail = error?.response?.data?.detail
  if (Array.isArray(detail)) return detail.map((item) => `${(item?.loc || []).slice(1).join('.')}: ${item?.msg || ''}`).join('; ') || 'Оруулсан утга буруу байна.'
  if (detail && typeof detail === 'object') {
    const issues = Array.isArray(detail.issues) ? detail.issues.map(warningLabel).join(', ') : ''
    const who = detail.employee_name ? `${detail.employee_name}: ` : ''
    return `${who}${detail.message || issues || detail.code || 'Үйлдэл амжилтгүй боллоо.'}${detail.message && issues ? ` (${issues})` : ''}`
  }
  return String(detail || error?.message || 'Үйлдэл амжилтгүй боллоо.')
}

export type RowState = 'draft' | 'edited' | 'attention' | 'approved' | 'error'
export const ROW_STATE_LABELS: Record<RowState, string> = { draft: 'Ноорог', edited: 'Засварласан', attention: 'Анхаарах', approved: 'Батлагдсан', error: 'Алдаатай' }
const ROW_STATE_TONES: Record<RowState, string> = { draft: 'warning', edited: 'info', attention: 'danger', approved: 'success', error: 'danger' }
const EDIT_AUDIT = /^(inputs|excel_import|overrides_reverted|hr_profile_accepted|computed:)/

export function rowState(row: MonthlyPayrollRunRow): RowState {
  if (row.status === 'approved') return 'approved'
  if (row.warnings.some((warning) => BLOCKING_WARNINGS.has(warning) && warning !== 'row_flagged')) return 'error'
  if (row.status === 'flagged') return 'attention'
  if ((row.audit || []).some((item) => EDIT_AUDIT.test(item.field))) return 'edited'
  return 'draft'
}

export function RowStateChip({ row }: { row: MonthlyPayrollRunRow }) {
  const state = rowState(row)
  return <span className={`payroll-v2-chip ${ROW_STATE_TONES[state]}`}><span />{ROW_STATE_LABELS[state]}</span>
}

export function RunStatusChip({ status }: { status: string }) {
  return <span className={`payroll-v2-chip ${runStatusTone(status)}`}><span />{RUN_STATUS_LABELS[status] || status}</span>
}

type ReasonRequest = { title: string; label: string; confirm: string; resolve: (value: string | null) => void }

/** Promise-based reason prompt replacing window.prompt for audited actions. */
export function useReasonDialog(): [ReactNode, (title: string, label?: string, confirm?: string) => Promise<string | null>] {
  const [request, setRequest] = useState<ReasonRequest | null>(null)
  const [reason, setReason] = useState('')
  const inputRef = useRef<HTMLTextAreaElement | null>(null)
  const ask = useCallback((title: string, label = 'Шалтгаан', confirm = 'Хадгалах') => new Promise<string | null>((resolve) => {
    setReason('')
    setRequest({ title, label, confirm, resolve })
    window.setTimeout(() => inputRef.current?.focus(), 0)
  }), [])
  const finish = (value: string | null) => { request?.resolve(value); setRequest(null) }
  const dialog = request ? createPortal(<div className="mp-dialog-backdrop" onClick={() => finish(null)}>
    <form className="mp-dialog" role="dialog" aria-modal="true" aria-labelledby="mp-dialog-title" onClick={(event) => event.stopPropagation()} onSubmit={(event) => { event.preventDefault(); if (reason.trim()) finish(reason.trim()) }} onKeyDown={(event) => { if (event.key === 'Escape') finish(null) }}>
      <h2 id="mp-dialog-title">{request.title}</h2>
      <label>{request.label}<textarea ref={inputRef} rows={3} value={reason} onChange={(event) => setReason(event.target.value)} required /></label>
      <div className="mp-dialog-actions"><button type="button" className="payroll-v2-button secondary" onClick={() => finish(null)}>Болих</button><button className="payroll-v2-button primary" disabled={!reason.trim()}>{request.confirm}</button></div>
    </form>
  </div>, document.body) : null
  return [dialog, ask]
}

export function MonthlyShell({ children, actions, canAdminister = false }: { children: ReactNode; actions?: ReactNode; canAdminister?: boolean }) {
  const tab = ({ isActive }: { isActive: boolean }) => (isActive ? 'active' : undefined)
  return <main className="payroll-v2-shell"><div className="payroll-v2-content">
    <div className="payroll-compact-toolbar">
      <nav className="payroll-compact-nav" aria-label="Цалингийн навигаци">
        <NavLink className={tab} to="/erp/payroll" end>Хянах самбар</NavLink>
        <NavLink className={tab} to="/erp/payroll/monthly" end>Сарын цалин</NavLink>
        <NavLink className={tab} to="/erp/payroll/monthly/reports">Тайлан</NavLink>
        <NavLink className={tab} to="/erp/payroll/monthly/archive">Архив</NavLink>
        {canAdminister && <NavLink className={tab} to="/erp/payroll/monthly/settings">Тохиргоо</NavLink>}
        <NavLink to="/hr?tab=payroll">HR тохиргоо</NavLink>
      </nav>
      {actions ? <div className="payroll-compact-actions">{actions}</div> : null}
    </div>
    {children}
  </div></main>
}

export function MonthStepper({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return <div className="mp-month-stepper">
    <button type="button" className="payroll-v2-button secondary compact" aria-label="Өмнөх сар" onClick={() => onChange(shiftMonth(value, -1))}>◀</button>
    <input aria-label="Цалингийн сар" type="month" value={value} onChange={(event) => event.target.value && onChange(event.target.value)} />
    <button type="button" className="payroll-v2-button secondary compact" aria-label="Дараах сар" onClick={() => onChange(shiftMonth(value, 1))}>▶</button>
  </div>
}
