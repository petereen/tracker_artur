import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import { RadioList, RadioListItem } from '@astryxdesign/core/RadioList'
import type { DateRange } from '../../../api/enterprise'

/** One-line widget title: dense, icon + label, optional trailing actions. */
export function WidgetHeader({ icon: Icon, title, meta, children }: { icon: LucideIcon; title: string; meta?: ReactNode; children?: ReactNode }) {
  return (
    <header className="today-widget-header">
      <span className="today-widget-title"><Icon size={14} aria-hidden />{title}</span>
      {meta && <span className="today-widget-meta">{meta}</span>}
      {children && <span className="today-widget-actions" data-today-interactive>{children}</span>}
    </header>
  )
}

// ---- week periods ----------------------------------------------------------

export type WeekPeriod = 'this_week' | 'previous_week'

export const WEEK_PERIOD_LABELS: Record<WeekPeriod, string> = {
  this_week: 'Энэ долоо хоног',
  previous_week: 'Өмнөх долоо хоног',
}

export function localDateKey(value: Date) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`
}

const addDays = (value: Date, days: number) => {
  const next = new Date(value)
  next.setDate(next.getDate() + days)
  return next
}

/** Monday-based weeks. "This week" runs to today; the comparison is the same weekdays one week earlier. */
export function weekRanges(period: WeekPeriod, today = new Date()): { range: DateRange; comparison: DateRange; days: number } {
  const day = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  const monday = addDays(day, -((day.getDay() + 6) % 7))
  if (period === 'this_week') {
    const days = Math.round((day.getTime() - monday.getTime()) / 86_400_000) + 1
    return {
      range: { date_from: localDateKey(monday), date_to: localDateKey(day) },
      comparison: { date_from: localDateKey(addDays(monday, -7)), date_to: localDateKey(addDays(day, -7)) },
      days,
    }
  }
  return {
    range: { date_from: localDateKey(addDays(monday, -7)), date_to: localDateKey(addDays(monday, -1)) },
    comparison: { date_from: localDateKey(addDays(monday, -14)), date_to: localDateKey(addDays(monday, -8)) },
    days: 7,
  }
}

export function normalizePeriod(value: unknown): WeekPeriod {
  return value === 'previous_week' ? 'previous_week' : 'this_week'
}

/** The [ This Week | Previous Week ] radio used by every period-aware widget. */
export function WeekPeriodField({ value, onChange }: { value: WeekPeriod; onChange: (value: WeekPeriod) => void }) {
  return (
    <RadioList label="Хугацаа" value={value} onChange={(next) => onChange(normalizePeriod(next))} orientation="horizontal" size="sm">
      <RadioListItem value="this_week" label={WEEK_PERIOD_LABELS.this_week} />
      <RadioListItem value="previous_week" label={WEEK_PERIOD_LABELS.previous_week} />
    </RadioList>
  )
}

// ---- sparkline ---------------------------------------------------------------

export interface SparkPoint { label: string; value: number }

/**
 * Single-series trend line: 2px muted stroke, the latest point in the accent.
 * Every point has a hover hit-area with its own tooltip.
 */
export function Sparkline({ points, format, label }: { points: SparkPoint[]; format: (value: number) => string; label: string }) {
  if (points.length < 2) return <span className="today-sparkline is-empty" aria-hidden />
  const width = 100
  const height = 28
  const pad = 3
  const max = Math.max(...points.map((point) => point.value), 1)
  const step = (width - pad * 2) / (points.length - 1)
  const coords = points.map((point, index) => ({ ...point, x: pad + index * step, y: height - pad - (point.value / max) * (height - pad * 2) }))
  const last = coords[coords.length - 1]
  return (
    <svg className="today-sparkline" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label={`${label}: ${points.map((point) => `${point.label} ${format(point.value)}`).join(', ')}`}>
      <polyline points={coords.map((point) => `${point.x},${point.y}`).join(' ')} fill="none" vectorEffect="non-scaling-stroke" />
      {/* Round-capped dot that stays circular although the line stretches to the tile width. */}
      <line className="today-sparkline-last" x1={last.x} y1={last.y} x2={last.x + 0.01} y2={last.y} vectorEffect="non-scaling-stroke" />
      {coords.map((point, index) => (
        <rect key={point.label} className="today-sparkline-hit" x={point.x - step / 2} y={0} width={step} height={height} data-index={index}>
          <title>{`${point.label}: ${format(point.value)}`}</title>
        </rect>
      ))}
    </svg>
  )
}

export function formatHours(minutes: number) {
  const hours = Math.round((minutes / 60) * 10) / 10
  return `${hours.toLocaleString('mn-MN')}ц`
}
