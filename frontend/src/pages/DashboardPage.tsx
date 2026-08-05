import { useState } from 'react'
import { LineChart, Line, XAxis, ResponsiveContainer, Tooltip, Area, AreaChart } from 'recharts'
import { Card, PageHeader } from '../components/ui'
import { useDashboardSummary, useDashboardMetrics, useTopEmployees, useWorkPerformance } from '../api/hooks'

const METRICS = [
  { key: 'calls',    label: 'Дуудлага',  color: '#388BFD' },
  { key: 'meetings', label: 'Уулзалт',   color: '#3FB950' },
  { key: 'emails',   label: 'И-мэйл',    color: '#BC8CFF' },
  { key: 'zoom',     label: 'Zoom',    color: '#D29922' },
]

function localDate(value = new Date()) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`
}

function formatMinutes(minutes: number) {
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return hours ? `${hours}ц ${rest}м` : `${rest}м`
}

export function DashboardPage() {
  const [metric, setMetric] = useState('calls')
  const [range, setRange] = useState<'day' | 'week' | 'month' | 'all' | 'custom'>('month')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const quickRange = (days: number, key: 'day' | 'week' | 'month') => {
    const start = new Date()
    start.setDate(start.getDate() - days + 1)
    setRange(key); setDateFrom(localDate(start)); setDateTo(localDate())
  }
  const filters = range === 'all'
    ? { all_time: true }
    : { period: 30, date_from: dateFrom || undefined, date_to: dateTo || undefined }
  const rangeLabel = range === 'all' ? 'Бүх хугацааны мэдээлэл' : range === 'day' ? 'Өнөөдрийн мэдээлэл' : range === 'week' ? 'Сүүлийн 7 хоногийн мэдээлэл' : range === 'month' ? 'Сүүлийн 30 хоногийн мэдээлэл' : `${dateFrom || 'эхлэлгүй'} – ${dateTo || 'өнөөдөр'}`
  const summary = useDashboardSummary(filters)
  const metricsData = useDashboardMetrics(metric, filters)
  const topEmployees = useTopEmployees()
  const workPerformance = useWorkPerformance(filters)

  const m = METRICS.find((x) => x.key === metric)!
  const chartData = metricsData.data || []

  const kpis = summary.data ? [
    { label: 'Дуудлага', value: summary.data.calls, color: '#388BFD' },
    { label: 'Уулзалт',  value: summary.data.meetings, color: '#3FB950' },
    { label: 'И-мэйл',   value: summary.data.emails, color: '#BC8CFF' },
    { label: 'Бөглөлтийн хувь', value: `${summary.data.fill_rate}%`, color: '#D29922' },
  ] : []

  return (
    <div>
      <PageHeader title="Хянах самбар" sub={rangeLabel}>
        <a href="/api/answers/export?format=csv" className="inline-flex items-center gap-1.5 font-medium rounded-lg transition-all cursor-pointer border text-[13px] px-3 py-1 bg-accent text-white border-accent hover:opacity-85">
          CSV татах
        </a>
      </PageHeader>

      <Card className="!p-3 mb-5 flex gap-2 flex-wrap items-center">
        <div className="flex gap-1 bg-surface2 rounded-lg p-1">
          {[['day', 'Өнөөдөр'], ['week', '7 хоног'], ['month', '30 хоног'], ['all', 'Бүх хугацаа']].map(([key, label]) => (
            <button key={key} onClick={() => key === 'day' ? quickRange(1, 'day') : key === 'week' ? quickRange(7, 'week') : key === 'month' ? quickRange(30, 'month') : setRange('all')}
              className={`px-3 py-1.5 rounded text-xs cursor-pointer border-none ${range === key ? 'bg-accent text-white' : 'bg-transparent text-muted'}`}>{label}</button>
          ))}
        </div>
        <span className="text-xs text-muted ml-1">Эсвэл:</span>
        <input type="date" value={dateFrom} onChange={(e) => { setRange('custom'); setDateFrom(e.target.value) }} className="bg-surface2 border border-border rounded-lg px-2 py-1.5 text-text text-xs outline-none" />
        <span className="text-muted">–</span>
        <input type="date" value={dateTo} onChange={(e) => { setRange('custom'); setDateTo(e.target.value) }} className="bg-surface2 border border-border rounded-lg px-2 py-1.5 text-text text-xs outline-none" />
      </Card>

      {/* KPI */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        {kpis.map((k) => (
          <Card key={k.label}>
            <div className="text-xs text-muted font-medium mb-2">{k.label}</div>
            <div className="text-[28px] font-semibold mb-1" style={{ color: k.color, fontVariantNumeric: 'tabular-nums' }}>{k.value}</div>
            <div className="text-xs text-muted">{rangeLabel}</div>
          </Card>
        ))}
      </div>

      {workPerformance.data && (
        <div className="grid grid-cols-5 gap-4 mb-4">
          <Card><div className="text-xs text-muted font-medium mb-2">Өдрийн тайлангийн биелэлт</div><div className="text-[26px] font-semibold text-accent">{workPerformance.data.daily_report_rate}%</div><div className="text-xs text-muted mt-1">{workPerformance.data.approved_daily_reports} батлагдсан</div></Card>
          <Card><div className="text-xs text-muted font-medium mb-2">Нийт ажилласан цаг</div><div className="text-[26px] font-semibold text-green">{formatMinutes(workPerformance.data.work_time?.total_minutes || 0)}</div><div className="text-xs text-muted mt-1">{workPerformance.data.work_time_entries} интервал</div></Card>
          <Card><div className="text-xs text-muted font-medium mb-2">Оффис</div><div className="text-[26px] font-semibold text-blue">{formatMinutes(workPerformance.data.work_time?.in_person_minutes || 0)}</div><div className="text-xs text-muted mt-1">ажилласан цаг</div></Card>
          <Card><div className="text-xs text-muted font-medium mb-2">Remote</div><div className="text-[26px] font-semibold text-purple">{formatMinutes(workPerformance.data.work_time?.remote_minutes || 0)}</div><div className="text-xs text-muted mt-1">ажилласан цаг</div></Card>
          <Card><div className="text-xs text-muted font-medium mb-2">Сарын тайлангийн биелэлт</div><div className="text-[26px] font-semibold text-[#BC8CFF]">{workPerformance.data.monthly_report_rate}%</div><div className="text-xs text-muted mt-1">{workPerformance.data.approved_monthly_reports} батлагдсан</div></Card>
        </div>
      )}


      {/* Chart + Top */}
      <div className="grid grid-cols-[2fr_1fr] gap-4 mb-4">
        <Card>
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="font-semibold text-[15px]">Өөрчлөлт</div>
              <div className="text-xs text-muted mt-0.5">{rangeLabel}</div>
            </div>
            <div className="flex gap-2">
              {METRICS.map((mx) => (
                <button key={mx.key} onClick={() => setMetric(mx.key)}
                  style={{ borderColor: metric === mx.key ? mx.color : '#30363D', color: metric === mx.key ? mx.color : '#7D8590', background: metric === mx.key ? mx.color + '22' : 'transparent' }}
                  className="px-2.5 py-1 rounded text-xs border cursor-pointer font-medium transition-all">
                  {mx.label}
                </button>
              ))}
            </div>
          </div>
          <ResponsiveContainer width="100%" height={130}>
            <AreaChart data={chartData} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="grad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={m.color} stopOpacity={0.25} />
                  <stop offset="100%" stopColor={m.color} stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="date" tick={{ fontSize: 9, fill: '#484F58' }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={{ background: '#1C2128', border: '1px solid #30363D', borderRadius: 8, fontSize: 12 }} />
              <Area type="monotone" dataKey="value" stroke={m.color} strokeWidth={1.8} fill="url(#grad)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </Card>

        <Card>
          <div className="font-semibold text-[15px] mb-4">Шилдэг ажилтнууд</div>
          {(topEmployees.data || []).map((emp: any, i: number) => (
            <div key={emp.id} className={`flex items-center gap-2.5 py-2 ${i < (topEmployees.data?.length - 1) ? 'border-b border-border2' : ''}`}>
              <div style={{ background: ['#D29922','#7D8590','#388BFD','#21262D','#21262D'][i] }}
                className="w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-bold text-black flex-shrink-0">
                {i + 1}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-[13px] font-medium truncate">{emp.name}</div>
                <div className="text-[11px] text-muted">цуврал: {emp.current_streak} өдөр</div>
              </div>
              <div className="text-xs text-green font-mono whitespace-nowrap">🔥 {emp.current_streak} өдөр</div>
            </div>
          ))}
          {!topEmployees.data?.length && <div className="text-muted text-sm">Мэдээлэл алга</div>}
        </Card>
      </div>
    </div>
  )
}
