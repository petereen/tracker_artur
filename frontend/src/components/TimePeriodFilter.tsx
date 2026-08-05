import { CalendarRange } from 'lucide-react'
import { DateRange } from '../api/enterprise'

export type PeriodPreset = 'today' | 'week' | 'month' | 'quarter'

function localDate(date: Date) {
  const offset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offset).toISOString().slice(0, 10)
}

export function periodFromPreset(preset: PeriodPreset): DateRange {
  const end = new Date()
  const start = new Date(end)
  const days = preset === 'today' ? 0 : preset === 'week' ? 6 : preset === 'month' ? 29 : 89
  start.setDate(start.getDate() - days)
  return { date_from: localDate(start), date_to: localDate(end) }
}

const OPTIONS: { key: PeriodPreset; label: string }[] = [
  { key: 'today', label: 'Өнөөдөр' },
  { key: 'week', label: '7 хоног' },
  { key: 'month', label: '30 хоног' },
  { key: 'quarter', label: '90 хоног' },
]

export function TimePeriodFilter({ preset, period, onChange }: { preset: PeriodPreset | 'custom'; period: DateRange; onChange: (preset: PeriodPreset | 'custom', period: DateRange) => void }) {
  return <div className="period-filter" aria-label="Хугацааны шүүлтүүр">
    <CalendarRange size={16} aria-hidden />
    <div className="period-presets">{OPTIONS.map((option) => <button key={option.key} className={preset === option.key ? 'active' : ''} onClick={() => onChange(option.key, periodFromPreset(option.key))}>{option.label}</button>)}</div>
    <label><span className="sr-only">Эхлэх огноо</span><input type="date" value={period.date_from} onChange={(event) => onChange('custom', { ...period, date_from: event.target.value })} /></label>
    <span>–</span>
    <label><span className="sr-only">Дуусах огноо</span><input type="date" value={period.date_to} onChange={(event) => onChange('custom', { ...period, date_to: event.target.value })} /></label>
  </div>
}
