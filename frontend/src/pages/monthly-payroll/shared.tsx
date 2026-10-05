import { useCallback, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { NavLink } from 'react-router-dom'
import { Archive, BarChart3, CalendarRange, LayoutDashboard, Settings2, Users } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import i18n from '../../i18n'
import { labelMap, labelOr } from '../../utils/labelMap'
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
  return i18n.t('mp.monthTitle', { year, month: i18n.t(`mp.monthValue.${month}`) })
}
export const dayOf = (isoDate: string) => Number(isoDate.slice(8, 10))

export const RUN_STATUS_LABELS: Record<string, string> = labelMap('mp.runStatus', ['draft', 'approved', 'paid', 'closed', 'waived'])
export const runStatusTone = (status: string) => (status === 'paid' || status === 'closed' ? 'success' : status === 'approved' ? 'info' : status === 'waived' ? 'muted' : 'warning')
export const runTitle = (run: { run_type: string; pay_date: string }) => (run.run_type === 'advance' ? i18n.t('mp.run.advanceTitle', { day: dayOf(run.pay_date) }) : i18n.t('mp.run.finalTitle'))

/** Mirror of the backend BLOCKING_ROW_WARNINGS: these keep a row out of approval. */
export const BLOCKING_WARNINGS = new Set(['negative_final_pay', 'profile_missing', 'salary_history_missing_or_incomplete', 'allowance_daily_rate_required', 'row_flagged', 'advance_changed', 'advance_not_due', 'advance_not_positive'])
export const warningLabel = (code: string) => labelOr('mp.warning', code)

export function requestError(error: any): string {
  const detail = error?.response?.data?.detail
  if (Array.isArray(detail)) return detail.map((item) => `${(item?.loc || []).slice(1).join('.')}: ${item?.msg || ''}`).join('; ') || i18n.t('mp.error.invalidValue')
  if (detail && typeof detail === 'object') {
    const issues = Array.isArray(detail.issues) ? detail.issues.map(warningLabel).join(', ') : ''
    const who = detail.employee_name ? `${detail.employee_name}: ` : ''
    return `${who}${detail.message || issues || detail.code || i18n.t('mp.error.actionFailed')}${detail.message && issues ? ` (${issues})` : ''}`
  }
  return String(detail || error?.message || i18n.t('mp.error.actionFailed'))
}

export type RowState = 'draft' | 'edited' | 'attention' | 'approved' | 'error'
export const ROW_STATE_LABELS: Record<RowState, string> = labelMap('mp.rowState', ['draft', 'edited', 'attention', 'approved', 'error'])
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
  const { t } = useTranslation()
  const [reason, setReason] = useState('')
  const inputRef = useRef<HTMLTextAreaElement | null>(null)
  const ask = useCallback((title: string, label = t('mp.reason.label'), confirm = t('mp.common.save')) => new Promise<string | null>((resolve) => {
    setReason('')
    setRequest({ title, label, confirm, resolve })
    window.setTimeout(() => inputRef.current?.focus(), 0)
  }), [])
  const finish = (value: string | null) => { request?.resolve(value); setRequest(null) }
  const dialog = request ? createPortal(<div className="mp-dialog-backdrop" onClick={() => finish(null)}>
    <form className="mp-dialog" role="dialog" aria-modal="true" aria-labelledby="mp-dialog-title" onClick={(event) => event.stopPropagation()} onSubmit={(event) => { event.preventDefault(); if (reason.trim()) finish(reason.trim()) }} onKeyDown={(event) => { if (event.key === 'Escape') finish(null) }}>
      <h2 id="mp-dialog-title">{request.title}</h2>
      <label>{request.label}<textarea ref={inputRef} rows={3} value={reason} onChange={(event) => setReason(event.target.value)} required /></label>
      <div className="mp-dialog-actions"><button type="button" className="payroll-v2-button secondary" onClick={() => finish(null)}>{t('mp.common.cancel')}</button><button className="payroll-v2-button primary" disabled={!reason.trim()}>{request.confirm}</button></div>
    </form>
  </div>, document.body) : null
  return [dialog, ask]
}

export function MonthlyShell({ children, actions, canAdminister = false }: { children: ReactNode; actions?: ReactNode; canAdminister?: boolean }) {
  const { t } = useTranslation()
  const tab = ({ isActive }: { isActive: boolean }) => (isActive ? 'active' : undefined)
  return <main className="payroll-v2-shell"><div className="payroll-v2-content">
    <div className="page-tabs">
      <nav className="page-tabs-list" aria-label={t('mp.nav.label')}>
        <NavLink className={tab} to="/erp/payroll" end><LayoutDashboard size={15} />{t('mp.nav.dashboard')}</NavLink>
        <NavLink className={tab} to="/erp/payroll/monthly" end><CalendarRange size={15} />{t('mp.nav.monthly')}</NavLink>
        <NavLink className={tab} to="/erp/payroll/monthly/reports"><BarChart3 size={15} />{t('mp.nav.reports')}</NavLink>
        <NavLink className={tab} to="/erp/payroll/monthly/archive"><Archive size={15} />{t('mp.nav.archive')}</NavLink>
        {canAdminister && <NavLink className={tab} to="/erp/payroll/monthly/settings"><Settings2 size={15} />{t('mp.nav.settings')}</NavLink>}
        <NavLink to="/hr?tab=payroll"><Users size={15} />{t('mp.nav.hrSettings')}</NavLink>
      </nav>
      {actions ? <div className="page-tabs-actions payroll-compact-actions">{actions}</div> : null}
    </div>
    {children}
  </div></main>
}

export function MonthStepper({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const { t } = useTranslation()
  return <div className="mp-month-stepper">
    <button type="button" className="payroll-v2-button secondary compact" aria-label={t('mp.month.prev')} onClick={() => onChange(shiftMonth(value, -1))}>◀</button>
    <input aria-label={t('mp.month.label')} type="month" value={value} onChange={(event) => event.target.value && onChange(event.target.value)} />
    <button type="button" className="payroll-v2-button secondary compact" aria-label={t('mp.month.next')} onClick={() => onChange(shiftMonth(value, 1))}>▶</button>
  </div>
}
