import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowDownRight, ArrowUpRight, BarChart3, Gauge, Minus } from 'lucide-react'
import { CheckboxList, CheckboxListItem } from '@astryxdesign/core/CheckboxList'
import { RadioList, RadioListItem } from '@astryxdesign/core/RadioList'
import { VStack } from '@astryxdesign/core/VStack'
import { useDailyAnalytics, useEnterpriseSummary } from '../../../api/enterprise'
import i18n from '../../../i18n'
import { useAuthStore } from '../../../store/auth'
import { intlLocale } from '../../../utils/locale'
import { useWorkspaceMode } from '../../WorkspaceModeProvider'
import type { WidgetProps, WidgetSettingsProps } from '../types'
import { formatHours, normalizePeriod, Sparkline, WeekPeriodToggle, weekRanges, WidgetHeader, type SparkPoint, type WeekPeriod } from './shared'

type MetricKey = 'completed_tasks' | 'completion_rate' | 'worked_minutes' | 'average_work_minutes' | 'report_submission_rate' | 'active_projects'

interface MetricSpec {
  format: (value: number) => string
  /** 'pp' = percentage-point change, 'relative' = % change, 'absolute' = count change, null = snapshot (no delta). */
  delta: 'pp' | 'relative' | 'absolute' | null
  /** Field of /analytics/daily used for the sparkline. */
  series?: 'completed_tasks' | 'worked_minutes'
}

const METRICS: Record<MetricKey, MetricSpec> = {
  completed_tasks: { format: (value) => value.toLocaleString(intlLocale()), delta: 'absolute', series: 'completed_tasks' },
  completion_rate: { format: (value) => `${value}%`, delta: 'pp' },
  worked_minutes: { format: formatHours, delta: 'relative', series: 'worked_minutes' },
  average_work_minutes: { format: formatHours, delta: 'relative' },
  report_submission_rate: { format: (value) => `${value}%`, delta: 'pp' },
  active_projects: { format: (value) => value.toLocaleString(intlLocale()), delta: null },
}
const METRIC_KEYS = Object.keys(METRICS) as MetricKey[]
const metricLabel = (metric: MetricKey) => i18n.t(`today.kpi.${metric}`)
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
  const { t } = useTranslation()
  if (!spec.delta || previous === undefined) return null
  const change = spec.delta === 'relative' ? (previous ? ((value - previous) / previous) * 100 : value ? 100 : 0) : value - previous
  const rounded = Math.round(change * 10) / 10
  const direction = rounded > 0 ? 'up' : rounded < 0 ? 'down' : 'flat'
  const Icon = direction === 'up' ? ArrowUpRight : direction === 'down' ? ArrowDownRight : Minus
  const unit = spec.delta === 'pp' ? i18n.t('today.kpi.ppUnit') : spec.delta === 'relative' ? '%' : ''
  const text = `${rounded > 0 ? '+' : ''}${rounded.toLocaleString(intlLocale())}${unit}`
  return (
    <span className={`today-kpi-delta is-${direction}`} title={t('today.kpi.deltaTitle')}>
      <Icon size={12} aria-hidden />{text}<span className="sr-only">{t('today.kpi.deltaSr')}</span>
    </span>
  )
}

function KpiTile({ metric, summary, previous, days }: { metric: MetricKey; summary: any; previous: any; days: { date: string; worked_minutes: number; completed_tasks: number }[] }) {
  useTranslation()
  const spec = METRICS[metric]
  const value = Number(summary?.[metric] ?? NaN)
  const points: SparkPoint[] = spec.series ? days.map((day) => ({ label: String(day.date).slice(5).replace('-', '.'), value: Number(day[spec.series!] ?? 0) })) : []
  return (
    <article className="today-kpi-tile">
      <span className="today-kpi-label">{metricLabel(metric)}</span>
      <strong className="today-kpi-value">{Number.isFinite(value) ? spec.format(value) : '—'}</strong>
      {Number.isFinite(value) && <Delta spec={spec} value={value} previous={previous?.[metric] === undefined ? undefined : Number(previous[metric])} />}
      {spec.series && <Sparkline points={points} format={spec.series === 'worked_minutes' ? formatHours : (point) => String(point)} label={metricLabel(metric)} />}
    </article>
  )
}

export function KpiWidget({ settings, updateSettings }: WidgetProps<KpiSettings>) {
  const { t } = useTranslation()
  const period = normalizePeriod(settings.period)
  const metrics = (settings.metrics ?? DEFAULT_KPI_SETTINGS.metrics).filter(isMetric)
  const { summary, previous, days, isLoading } = useWeekMetrics(period)
  return (
    <section className="today-widget today-kpi" aria-label={t('today.widget.kpi.title')}>
      <WidgetHeader icon={BarChart3} title={t('today.widget.kpi.title')}><WeekPeriodToggle value={period} onChange={(next) => updateSettings({ period: next })} /></WidgetHeader>
      {metrics.length ? (
        <div className={`today-kpi-grid${isLoading ? ' is-loading' : ''}`}>
          {metrics.map((metric) => <KpiTile key={metric} metric={metric} summary={summary} previous={previous} days={days} />)}
        </div>
      ) : <p className="today-widget-empty">{t('today.kpi.pickMetrics')}</p>}
    </section>
  )
}

export function SingleKpiWidget({ settings, updateSettings }: WidgetProps<SingleKpiSettings>) {
  useTranslation()
  const period = normalizePeriod(settings.period)
  const metric = isMetric(settings.metric) ? settings.metric : DEFAULT_SINGLE_KPI_SETTINGS.metric
  const { summary, previous, days } = useWeekMetrics(period)
  return (
    <section className="today-widget today-kpi is-single" aria-label={metricLabel(metric)}>
      <WidgetHeader icon={Gauge} title={metricLabel(metric)}><WeekPeriodToggle value={period} onChange={(next) => updateSettings({ period: next })} /></WidgetHeader>
      <KpiTile metric={metric} summary={summary} previous={previous} days={days} />
    </section>
  )
}

export function KpiSettingsForm({ settings, onChange }: WidgetSettingsProps<KpiSettings>) {
  const { t } = useTranslation()
  return (
    <VStack gap={4}>
      <CheckboxList label={t('today.kpi.metrics')} density="compact" value={(settings.metrics ?? []).filter(isMetric)} onChange={(values) => onChange({ ...settings, metrics: METRIC_KEYS.filter((key) => values.includes(key)) })}>
        {METRIC_KEYS.map((key) => <CheckboxListItem key={key} value={key} label={metricLabel(key)} />)}
      </CheckboxList>
    </VStack>
  )
}

export function SingleKpiSettingsForm({ settings, onChange }: WidgetSettingsProps<SingleKpiSettings>) {
  const { t } = useTranslation()
  return (
    <VStack gap={4}>
      <RadioList label={t('today.kpi.metric')} size="sm" value={isMetric(settings.metric) ? settings.metric : DEFAULT_SINGLE_KPI_SETTINGS.metric} onChange={(metric) => onChange({ ...settings, metric: metric as MetricKey })}>
        {METRIC_KEYS.map((key) => <RadioListItem key={key} value={key} label={metricLabel(key)} />)}
      </RadioList>
    </VStack>
  )
}
