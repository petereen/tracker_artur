import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Banner } from '@astryxdesign/core/Banner'
import { Grid } from '@astryxdesign/core/Grid'
import { Heading } from '@astryxdesign/core/Heading'
import { HoverCard } from '@astryxdesign/core/HoverCard'
import { Table } from '@astryxdesign/core/Table'
import { Text } from '@astryxdesign/core/Text'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import { useTranslation } from 'react-i18next'
import i18n from '../../i18n'
import { labelMap } from '../../utils/labelMap'
import type { MonthlyPayrollRunRow } from '../../api/enterprise'
import { formatHours, toNumber } from './shared'

interface DayLine extends Record<string, unknown> {
  date: string; day_type?: string; hours?: string; normal_hours?: string; overtime_hours?: Record<string, string>; source?: string
}

const DAY_TYPE_COLORS: Record<string, 'default' | 'orange' | 'red'> = { working: 'default', weekly_rest: 'orange', public_holiday: 'red' }
const DAY_TYPE_LABELS = labelMap('mp.hoursDayType', ['working', 'weekly_rest', 'public_holiday'])
const SOURCES = labelMap('mp.source', ['attendance', 'worktime', 'qr', 'manual'])
const dateLabel = (value: string) => { const date = new Date(`${value}T12:00:00`); return `${String(date.getMonth() + 1).padStart(2, '0')}/${String(date.getDate()).padStart(2, '0')} ${i18n.t(`mp.weekday.${date.getDay()}`)}` }
const overtimeOf = (line: DayLine) => Object.values(line.overtime_hours || {}).reduce((sum, value) => sum + toNumber(value), 0)

function Figure({ label, value }: { label: string; value: string }) {
  return <VStack gap={0.5}><Text type="supporting">{label}</Text><Text type="label" weight="semibold" hasTabularNumbers>{value}</Text></VStack>
}

function Breakdown({ row, isFinal, cutoff }: { row: MonthlyPayrollRunRow; isFinal: boolean; cutoff?: string | null }) {
  const { t } = useTranslation()
  const inputs = row.inputs || {}
  const lines: DayLine[] = inputs.day_lines || []
  const totals = lines.reduce((sum, line) => ({ total: sum.total + toNumber(line.hours), normal: sum.normal + toNumber(line.normal_hours), overtime: sum.overtime + overtimeOf(line) }), { total: 0, normal: 0, overtime: 0 })
  const leaveDays = (inputs.approved_leave_days || []).filter((day: any) => (day.leave_ids || []).length > 0).length
  const missing: string[] = inputs.missing_dates || []
  const source = inputs._source_snapshot
  const manual = Boolean(source) && JSON.stringify(inputs.worked_normal_hours ?? null) !== JSON.stringify(source.worked_normal_hours ?? null)
  return <VStack gap={3} padding={1}>
    <VStack gap={0.5}>
      <Heading level={4}>{t('mp.hours.breakdown')}</Heading>
      <Text type="supporting">{isFinal ? t('mp.hours.finalSubtitle') : t('mp.hours.advanceSubtitle', { cutoff: cutoff || t('mp.hours.cutoffDay') })}</Text>
    </VStack>
    <Grid columns={4} gap={2}>
      <Figure label={t('mp.hours.planned')} value={formatHours(row.result.planned_hours)} />
      <Figure label={t('mp.hours.normal')} value={formatHours(inputs.worked_normal_hours)} />
      <Figure label={t('mp.hours.overtime')} value={formatHours(totals.overtime)} />
      <Figure label={t('mp.hours.workedDays')} value={`${lines.length}${row.result.planned_days != null ? ` / ${row.result.planned_days}` : ''}`} />
    </Grid>
    {lines.length ? <VStack gap={1} height={lines.length > 8 ? 300 : undefined} isScrollable={lines.length > 8}>
      <Table<DayLine>
        data={lines}
        idKey="date"
        density="compact"
        columns={[
          { key: 'date', header: t('mp.hours.col.date'), renderCell: (line) => dateLabel(line.date) },
          { key: 'day_type', header: t('mp.hours.col.type'), renderCell: (line) => { const key = line.day_type || ''; return <Token size="sm" label={DAY_TYPE_LABELS[key as keyof typeof DAY_TYPE_LABELS] || key || '—'} color={DAY_TYPE_COLORS[key] || 'default'} /> } },
          { key: 'hours', header: t('mp.hours.col.total'), align: 'end', renderCell: (line) => formatHours(line.hours) },
          { key: 'normal_hours', header: t('mp.hours.col.normal'), align: 'end', renderCell: (line) => formatHours(line.normal_hours) },
          { key: 'overtime_hours', header: t('mp.hours.col.overtime'), align: 'end', renderCell: (line) => overtimeOf(line) ? formatHours(overtimeOf(line)) : '—' },
          { key: 'source', header: t('mp.hours.col.source'), renderCell: (line) => SOURCES[(line.source || '') as keyof typeof SOURCES] || line.source || '—' },
        ]}
      />
      <Text type="supporting" hasTabularNumbers>{t('mp.hours.totalsLine', { total: formatHours(totals.total), normal: formatHours(totals.normal), overtime: formatHours(totals.overtime) })}</Text>
    </VStack> : <Text type="supporting">{t('mp.hours.noLines')}</Text>}
    {!isFinal && toNumber(inputs.projected_remaining_hours) > 0 && <Text type="supporting">{t('mp.hours.projected', { hours: formatHours(inputs.projected_remaining_hours) })}</Text>}
    {(leaveDays > 0 || missing.length > 0) && <Text type="supporting">{[leaveDays ? t('mp.hours.leave', { days: leaveDays }) : '', missing.length ? t('mp.hours.missing', { count: missing.length, list: `${missing.slice(0, 4).map((day) => dateLabel(day)).join(', ')}${missing.length > 4 ? '…' : ''}` }) : ''].filter(Boolean).join(' · ')}</Text>}
    {manual && <Banner status="warning" title={t('mp.hours.manualTitle')} description={t('mp.hours.manualDesc', { source: formatHours(source.worked_normal_hours), current: formatHours(inputs.worked_normal_hours) })} collapsible={false} />}
  </VStack>
}

/** Worked-hours cell: hover previews the per-day breakdown, click pins it open. */
export function WorkedHoursInfo({ row, isFinal, cutoff, children }: { row: MonthlyPayrollRunRow; isFinal: boolean; cutoff?: string | null; children: ReactNode }) {
  const { t } = useTranslation()
  const [hovered, setHovered] = useState(false)
  const [pinned, setPinned] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!pinned) return
    const close = (event: MouseEvent) => {
      const target = event.target as Element | null
      if (triggerRef.current?.contains(target) || target?.closest?.('.astryx-hover-card')) return
      setPinned(false)
    }
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') setPinned(false) }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', escape) }
  }, [pinned])
  return <HoverCard
    content={<Breakdown row={row} isFinal={isFinal} cutoff={cutoff} />}
    label={t('mp.hours.breakdown')}
    placement="below"
    alignment="start"
    isOpen={hovered || pinned}
    onOpenChange={setHovered}
  >
    <button ref={triggerRef} type="button" className="mp-ot-trigger" aria-expanded={hovered || pinned} aria-label={t('mp.hours.breakdownOpen')} onClick={() => setPinned((value) => !value)}>{children}</button>
  </HoverCard>
}
