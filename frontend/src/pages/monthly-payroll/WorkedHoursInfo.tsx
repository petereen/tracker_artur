import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Banner } from '@astryxdesign/core/Banner'
import { Grid } from '@astryxdesign/core/Grid'
import { Heading } from '@astryxdesign/core/Heading'
import { HoverCard } from '@astryxdesign/core/HoverCard'
import { Table } from '@astryxdesign/core/Table'
import { Text } from '@astryxdesign/core/Text'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import type { MonthlyPayrollRunRow } from '../../api/enterprise'
import { formatHours, toNumber } from './shared'

interface DayLine extends Record<string, unknown> {
  date: string; day_type?: string; hours?: string; normal_hours?: string; overtime_hours?: Record<string, string>; source?: string
}

const WEEKDAYS = ['Ня', 'Да', 'Мя', 'Лх', 'Пү', 'Ба', 'Бя']
const DAY_TYPES: Record<string, { label: string; color: 'default' | 'orange' | 'red' }> = {
  working: { label: 'Ажлын', color: 'default' }, weekly_rest: { label: 'Амралт', color: 'orange' }, public_holiday: { label: 'Баяр', color: 'red' },
}
const SOURCES: Record<string, string> = { attendance: 'HR ирц', worktime: 'Цаг бүртгэл', qr: 'QR', manual: 'Гараар' }
const dateLabel = (value: string) => { const date = new Date(`${value}T12:00:00`); return `${String(date.getMonth() + 1).padStart(2, '0')}/${String(date.getDate()).padStart(2, '0')} ${WEEKDAYS[date.getDay()]}` }
const overtimeOf = (line: DayLine) => Object.values(line.overtime_hours || {}).reduce((sum, value) => sum + toNumber(value), 0)

function Figure({ label, value }: { label: string; value: string }) {
  return <VStack gap={0.5}><Text type="supporting">{label}</Text><Text type="label" weight="semibold" hasTabularNumbers>{value}</Text></VStack>
}

function Breakdown({ row, isFinal, cutoff }: { row: MonthlyPayrollRunRow; isFinal: boolean; cutoff?: string | null }) {
  const inputs = row.inputs || {}
  const lines: DayLine[] = inputs.day_lines || []
  const totals = lines.reduce((sum, line) => ({ total: sum.total + toNumber(line.hours), normal: sum.normal + toNumber(line.normal_hours), overtime: sum.overtime + overtimeOf(line) }), { total: 0, normal: 0, overtime: 0 })
  const leaveDays = (inputs.approved_leave_days || []).filter((day: any) => (day.leave_ids || []).length > 0).length
  const missing: string[] = inputs.missing_dates || []
  const source = inputs._source_snapshot
  const manual = Boolean(source) && JSON.stringify(inputs.worked_normal_hours ?? null) !== JSON.stringify(source.worked_normal_hours ?? null)
  return <VStack gap={3} padding={1}>
    <VStack gap={0.5}>
      <Heading level={4}>Ажилласан цагийн задаргаа</Heading>
      <Text type="supporting">{isFinal ? 'Цалингийн сарын ажилласан өдрүүд' : `${cutoff || 'Таслах өдөр'} хүртэлх бүртгэл + сарын үлдсэн төлөвлөгөө`}</Text>
    </VStack>
    <Grid columns={4} gap={2}>
      <Figure label="Ажиллах цаг" value={formatHours(row.result.planned_hours)} />
      <Figure label="Ердийн цаг" value={formatHours(inputs.worked_normal_hours)} />
      <Figure label="Илүү цаг" value={formatHours(totals.overtime)} />
      <Figure label="Ажилласан өдөр" value={`${lines.length}${row.result.planned_days != null ? ` / ${row.result.planned_days}` : ''}`} />
    </Grid>
    {lines.length ? <VStack gap={1} height={lines.length > 8 ? 300 : undefined} isScrollable={lines.length > 8}>
      <Table<DayLine>
        data={lines}
        idKey="date"
        density="compact"
        columns={[
          { key: 'date', header: 'Огноо', renderCell: (line) => dateLabel(line.date) },
          { key: 'day_type', header: 'Төрөл', renderCell: (line) => { const type = DAY_TYPES[line.day_type || ''] || { label: line.day_type || '—', color: 'default' as const }; return <Token size="sm" label={type.label} color={type.color} /> } },
          { key: 'hours', header: 'Нийт', align: 'end', renderCell: (line) => formatHours(line.hours) },
          { key: 'normal_hours', header: 'Ердийн', align: 'end', renderCell: (line) => formatHours(line.normal_hours) },
          { key: 'overtime_hours', header: 'Илүү', align: 'end', renderCell: (line) => overtimeOf(line) ? formatHours(overtimeOf(line)) : '—' },
          { key: 'source', header: 'Эх сурвалж', renderCell: (line) => SOURCES[line.source || ''] || line.source || '—' },
        ]}
      />
      <Text type="supporting" hasTabularNumbers>Нийт {formatHours(totals.total)} ц = ердийн {formatHours(totals.normal)} ц + илүү {formatHours(totals.overtime)} ц</Text>
    </VStack> : <Text type="supporting">Энэ хугацаанд цагийн бүртгэл татагдаагүй; цагийг гараар оруулсан.</Text>}
    {!isFinal && toNumber(inputs.projected_remaining_hours) > 0 && <Text type="supporting">Таслах өдрөөс хойш төлөвлөсөн {formatHours(inputs.projected_remaining_hours)} ц нэмэгдсэн.</Text>}
    {(leaveDays > 0 || missing.length > 0) && <Text type="supporting">{[leaveDays ? `Чөлөө: ${leaveDays} өдөр` : '', missing.length ? `Бүртгэлгүй ажлын өдөр: ${missing.length} (${missing.slice(0, 4).map((day) => dateLabel(day)).join(', ')}${missing.length > 4 ? '…' : ''})` : ''].filter(Boolean).join(' · ')}</Text>}
    {manual && <Banner status="warning" title="Гараар засагдсан" description={`Бүртгэлээс ${formatHours(source.worked_normal_hours)} ц тооцоолсон, одоо ${formatHours(inputs.worked_normal_hours)} ц.`} collapsible={false} />}
  </VStack>
}

/** Worked-hours cell: hover previews the per-day breakdown, click pins it open. */
export function WorkedHoursInfo({ row, isFinal, cutoff, children }: { row: MonthlyPayrollRunRow; isFinal: boolean; cutoff?: string | null; children: ReactNode }) {
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
    label="Ажилласан цагийн задаргаа"
    placement="below"
    alignment="start"
    isOpen={hovered || pinned}
    onOpenChange={setHovered}
  >
    <button ref={triggerRef} type="button" className="mp-ot-trigger" aria-expanded={hovered || pinned} aria-label="Ажилласан цагийн задаргаа харах" onClick={() => setPinned((value) => !value)}>{children}</button>
  </HoverCard>
}
