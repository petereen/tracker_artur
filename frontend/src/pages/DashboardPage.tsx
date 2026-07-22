import { useState } from 'react'
import { LineChart, Line, XAxis, ResponsiveContainer, Tooltip, Area, AreaChart } from 'recharts'
import { Card, PageHeader, Badge, Btn } from '../components/ui'
import { useDashboardSummary, useDashboardMetrics, useTopEmployees } from '../api/hooks'

const METRICS = [
  { key: 'calls',    label: 'Дуудлага',  color: '#388BFD' },
  { key: 'meetings', label: 'Уулзалт',   color: '#3FB950' },
  { key: 'emails',   label: 'И-мэйл',    color: '#BC8CFF' },
  { key: 'zoom',     label: 'Zoom',    color: '#D29922' },
]

export function DashboardPage() {
  const [metric, setMetric] = useState('calls')
  const summary = useDashboardSummary(30)
  const metricsData = useDashboardMetrics(metric, 30)
  const topEmployees = useTopEmployees()

  const m = METRICS.find((x) => x.key === metric)!
  const chartData = metricsData.data || []

  const kpis = summary.data ? [
    { label: 'Дуудлага (30 хоног)', value: summary.data.calls,    sub: 'Өмнөх сараас +12%', color: '#388BFD' },
    { label: 'Уулзалт (30 хоног)',  value: summary.data.meetings, sub: 'Өмнөх сараас +3',   color: '#3FB950' },
    { label: 'И-мэйл (30 хоног)',   value: summary.data.emails,   sub: 'Өмнөх сараас −5%',  color: '#BC8CFF' },
    { label: 'Бөглөлтийн хувь',     value: `${summary.data.fill_rate}%`, sub: 'Зорилго: ≥85%', color: '#D29922' },
  ] : []

  return (
    <div>
      <PageHeader title="Хянах самбар" sub="Сүүлийн 30 хоногийн мэдээлэл">
        <a href="/api/answers/export?format=csv" className="inline-flex items-center gap-1.5 font-medium rounded-lg transition-all cursor-pointer border text-[13px] px-3 py-1 bg-accent text-white border-accent hover:opacity-85">
          CSV татах
        </a>
      </PageHeader>

      {/* KPI */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        {kpis.map((k) => (
          <Card key={k.label}>
            <div className="text-xs text-muted font-medium mb-2">{k.label}</div>
            <div className="text-[28px] font-semibold mb-1" style={{ color: k.color, fontVariantNumeric: 'tabular-nums' }}>{k.value}</div>
            <div className="text-xs text-muted">{k.sub}</div>
          </Card>
        ))}
      </div>

      {/* Chart + Top */}
      <div className="grid grid-cols-[2fr_1fr] gap-4 mb-4">
        <Card>
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="font-semibold text-[15px]">Өөрчлөлт</div>
              <div className="text-xs text-muted mt-0.5">Сүүлийн 30 хоног</div>
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
