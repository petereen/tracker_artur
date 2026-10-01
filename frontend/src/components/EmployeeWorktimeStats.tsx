import { useTranslation } from 'react-i18next'
import { useMemo, useState } from 'react'
import { Download, FileSpreadsheet } from 'lucide-react'
import toast from 'react-hot-toast'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { Grid } from '@astryxdesign/core/Grid'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { ProgressBar } from '@astryxdesign/core/ProgressBar'
import { Skeleton } from '@astryxdesign/core/Skeleton'
import { Table } from '@astryxdesign/core/Table'
import { Text } from '@astryxdesign/core/Text'
import { VStack } from '@astryxdesign/core/VStack'
import { downloadWorktimeReport, useDailyAnalytics, useEnterpriseSummary, type DateRange } from '../api/enterprise'
import { periodFromPreset, TimePeriodFilter, type PeriodPreset } from './TimePeriodFilter'
import i18n from '../i18n'
import { intlLocale } from '../utils/locale'

interface DayRow extends Record<string, unknown> { date: string; worked_minutes: number; completed_tasks: number }

const hours = (minutes: number) => `${Math.round((minutes / 60) * 10) / 10}${i18n.t('worktime.unit.hour')}`
const isWeekday = (value: string) => { const day = new Date(`${value}T12:00:00`).getDay(); return day > 0 && day < 6 }
const dayLabel = (value: string) => new Intl.DateTimeFormat(intlLocale(), { month: 'short', day: 'numeric', weekday: 'short' }).format(new Date(`${value}T12:00:00`))

function Stat({ label, value }: { label: string; value: string }) {
  return <VStack gap={0.5}><Text type="supporting">{label}</Text><Text type="large" weight="semibold" hasTabularNumbers>{value}</Text></VStack>
}

/** Stats-module worktime figures for one worker, sized for the HR side panel. */
export function EmployeeWorktimeStats({ employeeId, employeeName }: { employeeId: number; employeeName: string }) {
  const { t } = useTranslation()
  const [preset, setPreset] = useState<PeriodPreset | 'custom'>('month')
  const [period, setPeriod] = useState<DateRange>(() => periodFromPreset('month'))
  const summary = useEnterpriseSummary(period, employeeId)
  const daily = useDailyAnalytics(period, employeeId)
  const days: DayRow[] = daily.data?.days ?? []
  const figures = useMemo(() => {
    const worked = days.filter((day) => day.worked_minutes > 0)
    const total = worked.reduce((sum, day) => sum + day.worked_minutes, 0)
    const workingDays = days.filter((day) => isWeekday(day.date)).length
    return { total, worked, workingDays, average: worked.length ? total / worked.length : 0 }
  }, [days])
  const recent = useMemo(() => [...figures.worked].reverse(), [figures.worked])
  const peak = Math.max(1, ...recent.map((day) => day.worked_minutes))
  const download = async (format: 'csv' | 'xlsx') => {
    try { await downloadWorktimeReport({ from: period.date_from, to: period.date_to, worker_id: employeeId }, format) } catch { toast.error(t('worktime.stats.exportFailed')) }
  }
  const failed = summary.isError || daily.isError
  return <VStack gap={3}>
    <HStack gap={2} hAlign="between" vAlign="center" wrap="wrap">
      <Heading level={3}>{t('worktime.stats.title')}</Heading>
      <TimePeriodFilter preset={preset} period={period} onChange={(next, value) => { setPreset(next); setPeriod(value) }} />
    </HStack>
    {failed ? <Banner status="error" title={t('worktime.stats.loadFailed')} description={t('worktime.stats.loadFailedBody')} collapsible={false} />
      : daily.isLoading || summary.isLoading ? <Skeleton height={160} />
      : <>
        <Grid columns={2} gap={3}>
          <Stat label={t('worktime.stats.total')} value={hours(figures.total)} />
          <Stat label={t('worktime.stats.avgWorkedDay')} value={hours(figures.average)} />
          <Stat label={t('worktime.stats.workedDays')} value={`${figures.worked.length} / ${figures.workingDays}`} />
          <Stat label={t('worktime.stats.taskCompletion')} value={`${summary.data?.completion_rate ?? 0}%`} />
        </Grid>
        {recent.length ? <VStack gap={1} height={recent.length > 6 ? 280 : undefined} isScrollable={recent.length > 6}>
          <Table<DayRow>
            data={recent}
            idKey="date"
            density="compact"
            columns={[
              { key: 'date', header: t('worktime.stats.date'), renderCell: (day) => dayLabel(day.date) },
              { key: 'worked_minutes', header: t('worktime.stats.worked'), renderCell: (day) => <ProgressBar label={t('worktime.stats.dayWorked', { day: dayLabel(day.date) })} isLabelHidden value={day.worked_minutes} max={peak} hasValueLabel formatValueLabel={(value) => hours(value)} variant={day.worked_minutes >= 480 ? 'success' : 'accent'} /> },
              { key: 'completed_tasks', header: t('worktime.stats.tasks'), align: 'end', width: { type: 'pixel', value: 90 } },
            ]}
          />
        </VStack> : <Text type="supporting">{t('worktime.stats.empty')}</Text>}
      </>}
    <HStack gap={2} wrap="wrap">
      <Button label={t('worktime.stats.downloadCsv')} size="sm" icon={<Download size={14} />} clickAction={() => download('csv')} tooltip={`${employeeName} · ${period.date_from} – ${period.date_to}`} />
      <Button label={t('worktime.stats.downloadExcel')} size="sm" icon={<FileSpreadsheet size={14} />} clickAction={() => download('xlsx')} tooltip={`${employeeName} · ${period.date_from} – ${period.date_to}`} />
    </HStack>
  </VStack>
}
