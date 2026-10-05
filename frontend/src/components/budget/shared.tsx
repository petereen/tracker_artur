import { forwardRef } from 'react'
import { Link as RRLink, type LinkProps } from 'react-router-dom'
import { StatusDot } from '@astryxdesign/core/StatusDot'
import { Token } from '@astryxdesign/core/Token'
import type { BudgetKind, BudgetPeriodType, BudgetScenario, BudgetStatus, VarianceStatus } from '../../api/budget'
import i18n from '../../i18n'
import { labelMap } from '../../utils/labelMap'
import { intlLocale } from '../../utils/locale'

export { labelMap }

export const KIND_LABELS = labelMap<BudgetKind>('budget.kind', ['income', 'cogs', 'expense', 'other'])
export const KIND_HINTS = labelMap<BudgetKind>('budget.kindHint', ['income', 'cogs', 'expense', 'other'])
export const SCENARIO_LABELS = labelMap<BudgetScenario>('budget.scenario', ['base', 'optimistic', 'conservative', 'other'])
export const PERIOD_LABELS = labelMap<BudgetPeriodType>('budget.period', ['month', 'quarter', 'year', 'custom'])
export const STATUS_LABELS = labelMap<BudgetStatus>('budget.status', ['draft', 'approved', 'archived'])
export const VARIANCE_LABELS = labelMap<VarianceStatus>('budget.variance', ['favorable', 'on_track', 'unfavorable', 'unplanned', 'no_activity'])

const KIND_COLORS: Record<BudgetKind, 'green' | 'orange' | 'red' | 'gray'> = { income: 'green', cogs: 'orange', expense: 'red', other: 'gray' }
const SCENARIO_COLORS: Record<BudgetScenario, 'green' | 'blue' | 'orange' | 'gray'> = { base: 'green', optimistic: 'blue', conservative: 'orange', other: 'gray' }
const STATUS_COLORS: Record<BudgetStatus, 'yellow' | 'green' | 'gray'> = { draft: 'yellow', approved: 'green', archived: 'gray' }
const VARIANCE_DOTS: Record<VarianceStatus, 'success' | 'warning' | 'error' | 'neutral' | 'accent'> = {
  favorable: 'success', on_track: 'warning', unfavorable: 'error', unplanned: 'accent', no_activity: 'neutral',
}

export function KindToken({ kind }: { kind: BudgetKind }) {
  return <Token size="sm" color={KIND_COLORS[kind]} label={KIND_LABELS[kind]} />
}
export function ScenarioToken({ scenario }: { scenario: BudgetScenario }) {
  return <Token size="sm" color={SCENARIO_COLORS[scenario]} label={SCENARIO_LABELS[scenario]} />
}
export function StatusToken({ status }: { status: BudgetStatus }) {
  return <Token size="sm" color={STATUS_COLORS[status]} label={STATUS_LABELS[status]} />
}
export function VarianceDot({ status }: { status: VarianceStatus }) {
  return <StatusDot variant={VARIANCE_DOTS[status]} label={VARIANCE_LABELS[status]} tooltip={VARIANCE_LABELS[status]} />
}

const formatters = new Map<string, Intl.NumberFormat>()
function numberFormat(kind: 'money' | 'compact'): Intl.NumberFormat {
  const locale = intlLocale()
  const key = `${locale}:${kind}`
  let format = formatters.get(key)
  if (!format) {
    format = new Intl.NumberFormat(locale, kind === 'money' ? { maximumFractionDigits: 0 } : { notation: 'compact', maximumFractionDigits: 1 })
    formatters.set(key, format)
  }
  return format
}

export function formatMoney(value: string | number | null | undefined, currency = 'MNT') {
  if (value === null || value === undefined || value === '') return '—'
  const amount = Number(value)
  if (!Number.isFinite(amount)) return String(value)
  return `${numberFormat('money').format(amount)}${currency === 'MNT' ? '₮' : ` ${currency}`}`
}
export const formatAmount = (value: string | number | null | undefined) => (value === null || value === undefined || value === '' ? '' : numberFormat('money').format(Number(value)))
export const formatPct = (value: string | null | undefined) => (value === null || value === undefined ? '—' : `${Number(value).toLocaleString(intlLocale(), { maximumFractionDigits: 1 })}%`)

export const formatDate = (value: string | null | undefined) => (value ? value.slice(0, 10).replaceAll('-', '.') : '—')
export const formatPeriod = (start: string, end: string) => `${formatDate(start)} – ${formatDate(end)}`

export function budgetErrorText(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((item) => String(item?.msg || '').replace(/^Value error, /, '')).filter(Boolean).join('; ') || i18n.t('budget.error.invalid')
  if (detail && typeof detail === 'object' && 'message' in detail && typeof (detail as { message: unknown }).message === 'string') return (detail as { message: string }).message
  return i18n.t('budget.error.failed')
}
export function budgetErrorDetail<T = Record<string, unknown>>(error: unknown): (T & { code?: string }) | undefined {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return detail && typeof detail === 'object' && !Array.isArray(detail) ? (detail as T & { code?: string }) : undefined
}

/** Budget sign rule (d161): income positive, cost of sales and expenses negative. */
export function signOk(kind: BudgetKind, amount: number) {
  if (!amount || kind === 'other') return true
  return kind === 'income' ? amount > 0 : amount < 0
}
export function applySign(kind: BudgetKind, amount: number) {
  if (kind === 'income') return Math.abs(amount)
  if (kind === 'cogs' || kind === 'expense') return -Math.abs(amount)
  return amount
}

/** Split a total evenly over n periods; the rounding remainder lands on the last one. */
export function splitEvenly(total: number, periods: number): number[] {
  if (periods <= 0) return []
  const share = Math.trunc((total / periods) * 100) / 100
  const values = Array.from({ length: periods }, () => share)
  values[periods - 1] = Math.round((total - share * (periods - 1)) * 100) / 100
  return values
}

/** Lets Astryx Link / Button `href` navigate through react-router instead of reloading. */
export const RouterLink = forwardRef<HTMLAnchorElement, Omit<LinkProps, 'to'> & { href: string }>(function RouterLink({ href, ...props }, ref) {
  return <RRLink ref={ref} to={href} {...props} />
})
