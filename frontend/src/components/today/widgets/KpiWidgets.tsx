import { useMemo } from 'react'
import { ArrowDownRight, ArrowUpRight, BarChart3, Gauge, Minus } from 'lucide-react'
import { CheckboxList, CheckboxListItem } from '@astryxdesign/core/CheckboxList'
import { RadioList, RadioListItem } from '@astryxdesign/core/RadioList'
import { VStack } from '@astryxdesign/core/VStack'
import { useDailyAnalytics, useEnterpriseSummary } from '../../../api/enterprise'
import { useAuthStore } from '../../../store/auth'
import { useWorkspaceMode } from '../../WorkspaceModeProvider'
import type { WidgetProps, WidgetSettingsProps } from '../types'
import { formatHours, normalizePeriod, Sparkline, WEEK_PERIOD_LABELS, WeekPeriodField, weekRanges, WidgetHeader, type SparkPoint, type WeekPeriod } from './shared'

type MetricKey = 'completed_tasks' | 'completion_rate' | 'worked_minutes' | 'average_work_minutes' | 'report_submission_rate' | 'active_projects'

interface MetricSpec {
  label: string
  format: (value: number) => string
  /** 'pp' = percentage-point change, 'relative' = % change, 'absolute' = count change, null = snapshot (no delta). */
  delta: 'pp' | 'relative' | 'absolute' | null
  /** Field of /analytics/daily used for the sparkline. */
  series?: 'completed_tasks' | 'worked_minutes'
}

const METRICS: Record<MetricKey, MetricSpec> = {
  completed_tasks: { label: 'Дууссан даалгавар', format: (value) => value.toLocaleString('mn-MN'), delta: 'absolute', series: 'completed_tasks' },
  completion_rate: { label: 'Гүйцэтгэл', format: (value) => `${value}%`, delta: 'pp' },
  worked_minutes: { label: 'Ажилласан цаг', format: formatHours, delta: 'relative', series: 'worked_minutes' },
  average_work_minutes: { label: 'Өдрийн дундаж цаг', format: formatHours, delta: 'relative' },
  report_submission_rate: { label: 'Тайлан илгээлт', format: (value) => `${value}%`, delta: 'pp' },
  active_projects: { label: 'Идэвхтэй төсөл', format: (value) => value.toLocaleString('mn-MN'), delta: null },
}
const METRIC_KEYS = Object.keys(METRICS) as MetricKey[]
const isMetric = (value: unknown): value is MetricKey => typeof value === 'string' && value in METRICS

export interface KpiSettings { period: WeekPeriod; metrics: MetricKey[] }
export interface SingleKpiSettings { period: WeekPeriod; metric: MetricKey }

export const DEFAULT_KPI_SETTINGS: KpiSettings = { period: 'this_week', metrics: ['active_projects', 'completed_tasks', 'completion_rate', 'worked_minutes'] }
export const DEFAULT_SINGLE_KPI_SETTINGS: SingleKpiSettings = { period: 'this_week', metric: 'worked_minutes' }

/** Summary + comparison + daily series for one week, scoped like the old dashboard (manager → organization). */
function useWeekMetrics(period: WeekPeriod) {
  const employeeId = useAuthStore((state) => state.actor?.employee_id)
  const { isManagerMode } = useWorkspaceMode()
  const scope = isManagerMode ? undefined : employeeId ?? undefined
  const { range, comparison } = useMemo(() => weekRanges(period), [period])
  const summary = useEnterpriseSummary(range, scope)
  const previous = useEnterpriseSummary(comparison, scope)
  const daily = useDailyAnalytics(range, scope)
  return { summary: summary.data, previous: previous.data, days: (daily.data?.days ?? []) as { date: string; worked_minutes: number; completed_tasks: number }[], isLoading: summary.isLoading }
}

function Delta({ spec, value, previous }: { spec: MetricSpec; value: number; previous: number | undefined }) {
  if (!spec.delta || previous === undefined) return null
  const change = spec.delta === 'relative' ? (previous ? ((value - previous) / previous) * 100 : value ? 100 : 0) : value - previous
  const rounded = Math.round(change * 10) / 10
  const direction = rounded > 0 ? 'up' : rounded < 0 ? 'down' : 'flat'
  const Icon = direction === 'up' ? ArrowUpRight : direction === 'down' ? ArrowDownRight : Minus
  const unit = spec.delta === 'pp' ? 'н.х' : spec.delta === 'relative' ? '%' : ''
  const text = `${rounded > 0 ? '+' : ''}${rounded.toLocaleString('mn-MN')}${unit}`
  return (
    <span className={`today-kpi-delta is-${direction}`} title="Өмнөх 7 хоногийн мөн үетэй харьцуулсан">
      <Icon size={12} aria-hidden />{text}<span className="sr-only"> өмнөх 7 хоногтой харьцуулахад</span>
    </span>
  )
}

function KpiTile({ metric, summary, previous, days }: { metric: MetricKey; summary: any; previous: any; days: { date: string; worked_minutes: number; completed_tasks: number }[] }) {
  const spec = METRICS[metric]
  const value = Number(summary?.[metric] ?? NaN)
  const points: SparkPoint[] = spec.series ? days.map((day) => ({ label: String(day.date).slice(5).replace('-', '.'), value: Number(day[spec.series!] ?? 0) })) : []
  return (
    <article className="today-kpi-tile">
      <span className="today-kpi-label">{spec.label}</span>
      <strong className="today-kpi-value">{Number.isFinite(value) ? spec.format(value) : '—'}</strong>
      {Number.isFinite(value) && <Delta spec={spec} value={value} previous={previous?.[metric] === undefined ? undefined : Number(previous[metric])} />}
      {spec.series && <Sparkline points={points} format={spec.series === 'worked_minutes' ? formatHours : (point) => String(point)} label={spec.label} />}
    </article>
  )
}

export function KpiWidget({ settings }: WidgetProps<KpiSettings>) {
  const period = normalizePeriod(settings.period)
  const metrics = (settings.metrics ?? DEFAULT_KPI_SETTINGS.metrics).filter(isMetric)
  const { summary, previous, days, isLoading } = useWeekMetrics(period)
  return (
    <section className="today-widget today-kpi" aria-label="Гүйцэтгэлийн үзүүлэлт">
      <WidgetHeader icon={BarChart3} title="Гүйцэтгэлийн үзүүлэлт" meta={WEEK_PERIOD_LABELS[period]} />
      {metrics.length ? (
        <div className={`today-kpi-grid${isLoading ? ' is-loading' : ''}`}>
          {metrics.map((metric) => <KpiTile key={metric} metric={metric} summary={summary} previous={previous} days={days} />)}
        </div>
      ) : <p className="today-widget-empty">Тохиргооноос үзүүлэлт сонгоно уу.</p>}
    </section>
  )
}

export function SingleKpiWidget({ settings }: WidgetProps<SingleKpiSettings>) {
  const period = normalizePeriod(settings.period)
  const metric = isMetric(settings.metric) ? settings.metric : DEFAULT_SINGLE_KPI_SETTINGS.metric
  const { summary, previous, days } = useWeekMetrics(period)
  return (
    <section className="today-widget today-kpi is-single" aria-label={METRICS[metric].label}>
      <WidgetHeader icon={Gauge} title={METRICS[metric].label} meta={WEEK_PERIOD_LABELS[period]} />
      <KpiTile metric={metric} summary={summary} previous={previous} days={days} />
    </section>
  )
}

export function KpiSettingsForm({ settings, onChange }: WidgetSettingsProps<KpiSettings>) {
  return (
    <VStack gap={4}>
      <WeekPeriodField value={normalizePeriod(settings.period)} onChange={(period) => onChange({ ...settings, period })} />
      <CheckboxList label="Үзүүлэлтүүд" density="compact" value={(settings.metrics ?? []).filter(isMetric)} onChange={(values) => onChange({ ...settings, metrics: METRIC_KEYS.filter((key) => values.includes(key)) })}>
        {METRIC_KEYS.map((key) => <CheckboxListItem key={key} value={key} label={METRICS[key].label} />)}
      </CheckboxList>
    </VStack>
  )
}

export function SingleKpiSettingsForm({ settings, onChange }: WidgetSettingsProps<SingleKpiSettings>) {
  return (
    <VStack gap={4}>
      <WeekPeriodField value={normalizePeriod(settings.period)} onChange={(period) => onChange({ ...settings, period })} />
      <RadioList label="Үзүүлэлт" size="sm" value={isMetric(settings.metric) ? settings.metric : DEFAULT_SINGLE_KPI_SETTINGS.metric} onChange={(metric) => onChange({ ...settings, metric: metric as MetricKey })}>
        {METRIC_KEYS.map((key) => <RadioListItem key={key} value={key} label={METRICS[key].label} />)}
      </RadioList>
    </VStack>
  )
}
