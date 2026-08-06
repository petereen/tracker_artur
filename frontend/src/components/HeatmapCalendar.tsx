import { useMemo } from 'react'

// Adapted from fishdev20/shadcn-heatmap (MIT), customized for this Vite design system.
export interface HeatmapDatum { date: string | Date; value: number; meta?: unknown }
export interface HeatmapCell { date: string; value: number; level: number; meta?: unknown; label: string }

function localKey(value: Date) { const copy = new Date(value); copy.setMinutes(copy.getMinutes() - copy.getTimezoneOffset()); return copy.toISOString().slice(0, 10) }

export function HeatmapCalendar({ data, endDate = new Date(), rangeDays = 365, onCellClick, renderTooltip }: { data: HeatmapDatum[]; endDate?: Date; rangeDays?: number; onCellClick?: (cell: HeatmapCell) => void; renderTooltip?: (cell: HeatmapCell) => string }) {
  const { weeks, months, max } = useMemo(() => {
    const merged = new Map<string, HeatmapDatum>()
    for (const item of data) { const key = typeof item.date === 'string' ? item.date.slice(0, 10) : localKey(item.date); const existing = merged.get(key); merged.set(key, { date: key, value: (existing?.value || 0) + item.value, meta: item.meta ?? existing?.meta }) }
    const last = new Date(endDate); last.setHours(12, 0, 0, 0); const first = new Date(last); first.setDate(first.getDate() - rangeDays + 1); first.setDate(first.getDate() - ((first.getDay() + 6) % 7))
    const cells: HeatmapCell[] = []; const cursor = new Date(first); const maxValue = Math.max(1, ...Array.from(merged.values()).map((item) => item.value))
    while (cursor <= last) { const key = localKey(cursor); const item = merged.get(key); const value = item?.value || 0; cells.push({ date: key, value, level: value ? Math.max(1, Math.ceil(value / maxValue * 4)) : 0, meta: item?.meta, label: cursor.toLocaleDateString('mn-MN', { month: 'long', day: 'numeric', weekday: 'long' }) }); cursor.setDate(cursor.getDate() + 1) }
    const weekList: HeatmapCell[][] = []; for (let index = 0; index < cells.length; index += 7) weekList.push(cells.slice(index, index + 7))
    const monthLabels = weekList.map((week, index) => { const current = new Date(`${week[0].date}T12:00:00`); const previous = index ? new Date(`${weekList[index - 1][0].date}T12:00:00`) : null; return !previous || current.getMonth() !== previous.getMonth() ? current.toLocaleDateString('mn-MN', { month: 'short' }) : '' })
    return { weeks: weekList, months: monthLabels, max: maxValue }
  }, [data, endDate, rangeDays])
  return <div className="shadcn-heatmap" aria-label="Өдрүүдээр ажилласан цагийн heatmap"><div className="heatmap-months">{months.map((month, index) => <span key={index}>{month}</span>)}</div><div className="heatmap-body"><div className="heatmap-weekdays"><span>Да</span><span>Лх</span><span>Ба</span></div><div className="heatmap-weeks">{weeks.map((week, weekIndex) => <div className="heatmap-week" key={weekIndex}>{week.map((cell) => { const title = renderTooltip?.(cell) || `${cell.label}: ${Math.round(cell.value / 60 * 10) / 10} цаг`; return <button type="button" key={cell.date} data-level={cell.level} title={title} aria-label={title} onClick={() => onCellClick?.(cell)} /> })}</div>)}</div></div><div className="heatmap-legend"><span>Бага</span>{[0, 1, 2, 3, 4].map((level) => <i key={level} data-level={level} />)}<span>Их</span><small>max {Math.round(max / 60 * 10) / 10}ц</small></div></div>
}
