import { forwardRef } from 'react'
import { Link as RRLink, type LinkProps } from 'react-router-dom'
import { StatusDot } from '@astryxdesign/core/StatusDot'
import { Token } from '@astryxdesign/core/Token'
import type { BudgetKind, BudgetPeriodType, BudgetScenario, BudgetStatus, VarianceStatus } from '../../api/budget'

export const KIND_LABELS: Record<BudgetKind, string> = { income: 'Орлого', cogs: 'ББӨ', expense: 'Зардал', other: 'Бусад' }
export const KIND_HINTS: Record<BudgetKind, string> = { income: 'эерэг (+)', cogs: 'сөрөг (−)', expense: 'сөрөг (−)', other: 'дурын тэмдэг' }
export const SCENARIO_LABELS: Record<BudgetScenario, string> = { base: 'Үндсэн (Base)', optimistic: 'Өөдрөг (Optimistic)', conservative: 'Болгоомжит (Conservative)', other: 'Бусад' }
export const PERIOD_LABELS: Record<BudgetPeriodType, string> = { month: 'Сараар', quarter: 'Улирлаар', year: 'Жилээр', custom: 'Дурын хугацаа' }
export const STATUS_LABELS: Record<BudgetStatus, string> = { draft: 'Ноорог', approved: 'Батлагдсан', archived: 'Архивласан' }
export const VARIANCE_LABELS: Record<VarianceStatus, string> = {
  favorable: 'Төлөвлөгөөг давсан', on_track: 'Төлөвлөгөөний дагуу', unfavorable: 'Төлөвлөгөөнөөс хоцорсон', unplanned: 'Төлөвлөөгүй', no_activity: 'Гүйлгээгүй',
}

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

const moneyFormat = new Intl.NumberFormat('mn-MN', { maximumFractionDigits: 0 })
const compactFormat = new Intl.NumberFormat('mn-MN', { notation: 'compact', maximumFractionDigits: 1 })

export function formatMoney(value: string | number | null | undefined, currency = 'MNT') {
  if (value === null || value === undefined || value === '') return '—'
  const amount = Number(value)
  if (!Number.isFinite(amount)) return String(value)
  return `${moneyFormat.format(amount)}${currency === 'MNT' ? '₮' : ` ${currency}`}`
}
export const formatAmount = (value: string | number | null | undefined) => (value === null || value === undefined || value === '' ? '' : moneyFormat.format(Number(value)))
export const formatCompact = (value: string | number | null | undefined) => (value === null || value === undefined ? '—' : compactFormat.format(Number(value)))
export const formatPct = (value: string | null | undefined) => (value === null || value === undefined ? '—' : `${Number(value).toLocaleString('mn-MN', { maximumFractionDigits: 1 })}%`)

export const formatDate = (value: string | null | undefined) => (value ? value.slice(0, 10).replaceAll('-', '.') : '—')
export const formatPeriod = (start: string, end: string) => `${formatDate(start)} – ${formatDate(end)}`

export function budgetErrorText(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((item) => String(item?.msg || '').replace(/^Value error, /, '')).filter(Boolean).join('; ') || 'Мэдээлэл буруу байна'
  if (detail && typeof detail === 'object' && 'message' in detail && typeof (detail as { message: unknown }).message === 'string') return (detail as { message: string }).message
  return 'Үйлдэл амжилтгүй боллоо'
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

export const isoToday = () => { const now = new Date(); return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10) }

/** Lets Astryx Link / Button `href` navigate through react-router instead of reloading. */
export const RouterLink = forwardRef<HTMLAnchorElement, Omit<LinkProps, 'to'> & { href: string }>(function RouterLink({ href, ...props }, ref) {
  return <RRLink ref={ref} to={href} {...props} />
})
