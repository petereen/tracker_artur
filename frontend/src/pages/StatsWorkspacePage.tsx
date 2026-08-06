import { useMemo, useState } from 'react'
import { useDailyAnalytics, useEnterpriseSummary, useWorkerDirectory } from '../api/enterprise'
import { TimePeriodFilter } from '../components/TimePeriodFilter'
import { EMPTY_ROLES, useAuthStore } from '../store/auth'

function localDate(value: Date) { const offset = value.getTimezoneOffset() * 60_000; return new Date(value.getTime() - offset).toISOString().slice(0, 10) }

export function StatsWorkspacePage() {
  const end = useMemo(() => new Date(), [])
  const start = useMemo(() => { const value = new Date(end); value.setDate(value.getDate() - 364); return value }, [end])
  const [period, setPeriod] = useState({ date_from: localDate(start), date_to: localDate(end) })
  const [preset, setPreset] = useState<'custom' | 'today' | 'week' | 'month' | 'quarter'>('custom')
  const [employeeId, setEmployeeId] = useState<number>()
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const canReview = roles.some((role) => ['admin', 'manager', 'team_lead'].includes(role))
  const workers = useWorkerDirectory()
  const summary = useEnterpriseSummary(period, employeeId)
  const daily = useDailyAnalytics(period, employeeId)
  const days = daily.data?.days ?? []
  const workingDays = days.filter((day: any) => { const weekday = new Date(`${day.date}T12:00:00`).getDay(); return weekday > 0 && weekday < 6 }).length
  const totalMinutes = days.reduce((sum: number, day: any) => sum + day.worked_minutes, 0)
  const completed = days.reduce((sum: number, day: any) => sum + day.completed_tasks, 0)
  const maxMinutes = Math.max(1, ...days.map((day: any) => day.worked_minutes))
  return <div className="stats-workspace">
    <div className="view-toolbar"><div><h2>Гүйцэтгэлийн үзүүлэлт</h2><p>Ажлын цаг болон даалгаврын түүхэн зураглал.</p></div><div className="toolbar-cluster">{canReview && <select value={employeeId || ''} onChange={(event) => setEmployeeId(event.target.value ? Number(event.target.value) : undefined)}><option value="">Байгууллагын нийлбэр</option>{workers.data?.map((worker) => <option key={worker.id} value={worker.id}>{worker.name}</option>)}</select>}<TimePeriodFilter preset={preset} period={period} onChange={(next, value) => { setPreset(next); setPeriod(value) }} /></div></div>
    <section className="metrics-grid"><article className="metric-card blue"><span>Нийт ажилласан</span><strong>{Math.round(totalMinutes / 60 * 10) / 10}ц</strong></article><article className="metric-card green"><span>Өдрийн дундаж</span><strong>{Math.round(totalMinutes / Math.max(workingDays, 1) / 60 * 10) / 10}ц</strong></article><article className="metric-card purple"><span>Даалгаврын гүйцэтгэл</span><strong>{summary.data?.completion_rate ?? 0}%</strong></article><article className="metric-card amber"><span>Өдөрт дуусгасан дундаж</span><strong>{Math.round(completed / Math.max(workingDays, 1) * 10) / 10}</strong></article></section>
    <section className="panel heatmap-panel"><div className="panel-heading"><div><span className="eyebrow">Worktime heatmap</span><h2>Өдрүүдээр ажилласан цаг</h2></div></div><div className="worktime-heatmap" aria-label="Өдрийн ажлын цагийн heatmap">{days.map((day: any) => { const level = day.worked_minutes ? Math.max(1, Math.ceil(day.worked_minutes / maxMinutes * 4)) : 0; return <span key={day.date} data-level={level} title={`${day.date}: ${Math.round(day.worked_minutes / 60 * 10) / 10}ц, ${day.completed_tasks} даалгавар`} /> })}</div><div className="heatmap-legend"><span>Бага</span>{[0,1,2,3,4].map((level) => <i key={level} data-level={level} />)}<span>Их</span></div></section>
  </div>
}
