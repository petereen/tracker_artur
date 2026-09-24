import { useEffect, useMemo, useRef, useState, type PointerEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { CircleAlert, Plus } from 'lucide-react'
import { useMonthlyPayrollDashboard, usePayrollCapabilities } from '../../api/enterprise'
import type { MonthlyPayrollDashboard as DashboardData } from '../../api/enterprise'
import { MonthStepper, MonthlyShell, RunStatusChip, formatAmount, formatHours, formatMoney, monthKey, monthTitle, requestError, runTitle, toNumber } from './shared'

type TrendPoint = DashboardData['trend'][number]
const SERIES = [
  { key: 'company_cost' as const, label: 'Нийт зардал', className: 'series-2' },
  { key: 'gross' as const, label: 'Олговол зохих', className: 'series-1' },
]
const BUCKET_LABELS: Record<string, string> = { weekday: 'Ажлын өдрийн илүү цаг', rest_day: 'Амралтын өдөр', public_holiday: 'Баярын өдөр' }
const ALERT_LABELS: Record<string, string> = {
  blocking_rows: 'Батлах боломжгүй мөр', warning_rows: 'Анхааруулгатай мөр', incomplete_profiles: 'Цалингийн профайл дутуу', hr_changed: 'HR өөрчлөлт хүлээгдэж буй',
  advance_changed: 'Урьдчилгаа өөрчлөгдсөн', advance_not_calculated: 'Урьдчилгаа бодоогүй', flagged: 'Шалгахаар тэмдэглэсэн',
}
const millions = (value: number) => (value >= 1_000_000 ? `${(value / 1_000_000).toLocaleString('en-US', { maximumFractionDigits: 1 })} сая` : formatAmount(value))

function niceMax(value: number) {
  if (value <= 0) return 1
  const magnitude = 10 ** Math.floor(Math.log10(value))
  return [1, 2, 2.5, 5, 10].map((step) => step * magnitude).find((candidate) => candidate >= value) || value
}

/** Two-series line chart: gross vs total company cost, one ₮ axis, crosshair tooltip, table view. */
export function PayrollTrendChart({ points }: { points: TrendPoint[] }) {
  const [hover, setHover] = useState<number | null>(null)
  const plotRef = useRef<HTMLDivElement | null>(null)
  const [width, setWidth] = useState(640)
  useEffect(() => {
    const element = plotRef.current
    if (!element || typeof ResizeObserver === 'undefined') return
    // Match the viewBox to the rendered width so axis text keeps its size.
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(320, Math.round(entry.contentRect.width))))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  const height = 220, left = 56, right = 108, top = 14, bottom = 28
  const plotWidth = width - left - right, plotHeight = height - top - bottom
  const max = niceMax(Math.max(0, ...points.flatMap((point) => SERIES.map((series) => toNumber(point[series.key])))))
  const x = (index: number) => left + (points.length <= 1 ? plotWidth / 2 : (index * plotWidth) / (points.length - 1))
  const y = (value: number) => top + plotHeight - (value / max) * plotHeight
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => ratio * max)
  const onMove = (event: PointerEvent<SVGRectElement>) => {
    const box = event.currentTarget.getBoundingClientRect()
    const position = ((event.clientX - box.left) / box.width) * plotWidth
    setHover(points.length <= 1 ? 0 : Math.max(0, Math.min(points.length - 1, Math.round((position / plotWidth) * (points.length - 1)))))
  }
  if (!points.length) return <p className="mp-empty">Трендийн өгөгдөл алга — сарын бодолт хийгдсэний дараа гарна.</p>
  const last = points[points.length - 1]
  const labelY = SERIES.map((series) => y(toNumber(last[series.key])))
  if (Math.abs(labelY[0] - labelY[1]) < 14) { labelY[0] = Math.min(labelY[0], labelY[1]) - 7; labelY[1] = labelY[0] + 14 }
  return <figure className="mp-trend">
    <div className="mp-trend-legend">{[...SERIES].reverse().map((series) => <span key={series.key}><i className={series.className} />{series.label}</span>)}</div>
    <div className="mp-trend-plot" ref={plotRef}>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Олговол зохих цалин ба нийт зардлын сар бүрийн тренд">
        {ticks.map((tick) => <g key={tick}><line className="mp-grid" x1={left} x2={left + plotWidth} y1={y(tick)} y2={y(tick)} /><text className="mp-axis" x={left - 8} y={y(tick) + 4} textAnchor="end">{millions(tick)}</text></g>)}
        {points.map((point, index) => <text key={point.month} className="mp-axis" x={x(index)} y={height - 8} textAnchor="middle">{point.month.slice(2)}</text>)}
        {hover !== null && <line className="mp-crosshair" x1={x(hover)} x2={x(hover)} y1={top} y2={top + plotHeight} />}
        {SERIES.map((series) => <g key={series.key} className={series.className}>
          {points.length > 1 && <polyline fill="none" points={points.map((point, index) => `${x(index)},${y(toNumber(point[series.key]))}`).join(' ')} />}
          {points.map((point, index) => <circle key={point.month} cx={x(index)} cy={y(toNumber(point[series.key]))} r={hover === index ? 5 : 4} />)}
        </g>)}
        {SERIES.map((series, index) => <text key={series.key} className="mp-end-label" x={x(points.length - 1) + 10} y={labelY[index] + 4}>{millions(toNumber(last[series.key]))}</text>)}
        <rect x={left} y={top} width={plotWidth} height={plotHeight} fill="transparent" onPointerMove={onMove} onPointerLeave={() => setHover(null)} />
      </svg>
      {hover !== null && <div className="mp-trend-tooltip" style={{ left: `${(x(hover) / width) * 100}%` }}>
        <strong>{monthTitle(points[hover].month)}{points[hover].status === 'closed' ? ' · хаасан' : ''}</strong>
        {[...SERIES].reverse().map((series) => <span key={series.key}><i className={series.className} />{series.label}<b>{formatMoney(points[hover][series.key])}</b></span>)}
        <span>Ажилтан<b>{points[hover].headcount}</b></span>
      </div>}
    </div>
    <details className="mp-table-view"><summary>Хүснэгтээр харах</summary><table><thead><tr><th>Сар</th><th>Олговол зохих</th><th>Нийт зардал</th><th>Ажилтан</th></tr></thead><tbody>{points.map((point) => <tr key={point.month}><td>{point.month}</td><td>{formatAmount(point.gross)}</td><td>{formatAmount(point.company_cost)}</td><td>{point.headcount}</td></tr>)}</tbody></table></details>
  </figure>
}

export function MonthlyPayrollDashboard() {
  const [params, setParams] = useSearchParams()
  const now = new Date()
  const month = params.get('month') || monthKey(now.getFullYear(), now.getMonth() + 1)
  const dashboard = useMonthlyPayrollDashboard(month)
  const caps = usePayrollCapabilities()
  const data = dashboard.data
  const stats = data?.stats
  const totals = stats?.totals || {}
  const alerts = useMemo(() => Object.entries(data?.alerts || {}).filter(([, count]) => count > 0), [data?.alerts])
  const setMonth = (value: string) => setParams((current) => { const next = new URLSearchParams(current); next.set('month', value); return next }, { replace: true })
  const finalKpis: Array<[string, unknown, string?]> = data?.has_final ? [
    ['Олговол зохих цалин', totals.gross], ['ХХОАТ (хөнгөлөлтийн дараа)', totals.pit, `Хөнгөлөлт ${formatAmount(totals.relief)}`], ['Ажилтны НДШ', totals.employee_shi],
    ['БНДШ', totals.employer_shi], ['Бусад суутгал', totals.other_deductions], ['Сүүл цалин', totals.net_pay], ['Нийт зардал', totals.company_cost, 'Олговол зохих + БНДШ'],
  ] : []
  return <MonthlyShell canAdminister={Boolean(caps.data?.capabilities.administer)} actions={<Link className="payroll-v2-button primary" to={`/erp/payroll/monthly?month=${month}`}><Plus size={15} />Шинэ бодолт</Link>}>
    <header className="payroll-v2-page-title mp-page-head"><div><span className="payroll-v2-kicker">ЦАЛИН · ХЯНАХ САМБАР</span><h1>{monthTitle(month)}</h1><p>{data?.status === 'closed' ? 'Хаасан сар — архивын өгөгдөл.' : data?.month_id ? 'Нээлттэй сар.' : 'Энэ сард цалингийн бүртгэл нээгдээгүй.'}</p></div><MonthStepper value={month} onChange={setMonth} /></header>
    {dashboard.isLoading ? <p className="payroll-v2-loading">Самбар ачаалж байна…</p> : dashboard.error ? <p role="alert">{requestError(dashboard.error)}</p> : data && <>
      <section className="payroll-v2-metric-grid compact mp-kpis">
        <article><span>Урьдчилгаа (төлсөн / төлөвлөсөн)</span><strong>{formatMoney(data.advance.paid)}</strong><small>{formatMoney(data.advance.planned)} төлөвлөсөн</small></article>
        {finalKpis.map(([label, value, hint]) => <article key={label}><span>{label}</span><strong>{formatMoney(value)}</strong>{hint && <small>{hint}</small>}</article>)}
        {!data.has_final && <article className="mp-kpi-empty"><span>Сүүл цалин</span><strong>—</strong><small>Сүүл цалингийн бодолт үүссэний дараа олговол зохих, татвар, НДШ, зардал харагдана.</small></article>}
      </section>

      <section className="payroll-v2-section"><div className="payroll-v2-section-head"><h2>Бодолтын явц</h2><Link to={`/erp/payroll/monthly?month=${month}`}>Сарын бодолт нээх</Link></div>
        {data.pipeline.length ? <div className="mp-pipeline">{data.pipeline.map((run) => <article key={run.id} className="mp-pipeline-card">
          <div><Link to={`/erp/payroll/monthly/runs/${run.id}`}><strong>{runTitle(run)}</strong></Link><RunStatusChip status={run.status} /></div>
          <span>{run.pay_date} · {run.workers} ажилтан</span><b>{formatMoney(run.total)}</b>
          <div className="mp-progress-bar" role="progressbar" aria-valuemin={0} aria-valuemax={run.workers} aria-valuenow={run.approved_rows}><i style={{ width: `${run.workers ? (run.approved_rows * 100) / run.workers : 0}%` }} /></div>
          <small>{run.approved_rows} / {run.workers} батлагдсан{run.paid_at ? ' · төлсөн' : ''}</small>
          {run.approved_rows < run.workers && run.status === 'draft' && <Link className="mp-inline-link" to={`/erp/payroll/monthly/runs/${run.id}?status=draft`}>Батлагдаагүй мөр харах</Link>}
        </article>)}</div> : <p className="mp-empty">Энэ сард бодолт үүсгээгүй байна.</p>}
      </section>

      <div className="mp-dashboard-grid">
        <section className="payroll-v2-stage-card"><h2>Анхааруулга</h2>{alerts.length ? <ul className="mp-alerts">{alerts.map(([key, count]) => <li key={key}><CircleAlert size={14} />{ALERT_LABELS[key] || key}<b>{count}</b></li>)}</ul> : <p className="mp-empty">Анхааруулах зүйл алга.</p>}</section>
        <section className="payroll-v2-stage-card"><h2>Удахгүй хийх төлбөр</h2>{data.upcoming.length ? <ul className="mp-upcoming">{data.upcoming.map((item, index) => <li key={index}><span>{item.pay_date}</span><strong>{item.run_type === 'advance' ? 'Урьдчилгаа' : 'Сүүл цалин'}</strong><small>{item.workers} ажилтан{item.status === 'not_created' ? ' · бодолт үүсгээгүй' : ''}</small><b>{item.amount !== null ? formatMoney(item.amount) : '—'}</b></li>)}</ul> : <p className="mp-empty">Төлөгдөөгүй төлбөр алга.</p>}</section>
        <section className="payroll-v2-stage-card"><h2>Илүү цаг</h2>{stats && Object.keys(stats.overtime?.hours || {}).length ? <table className="mp-mini-table"><thead><tr><th>Ангилал</th><th>Цаг</th><th>Дүн</th></tr></thead><tbody>{Object.entries(stats.overtime.hours as Record<string, string>).map(([bucket, hours]) => <tr key={bucket}><td>{BUCKET_LABELS[bucket] || bucket}</td><td>{formatHours(hours)}</td><td>{formatAmount(stats.overtime.amounts?.[bucket])}</td></tr>)}</tbody><tfoot><tr><td>{stats.overtime.workers} ажилтан</td><td /><td>{formatAmount(Object.values(stats.overtime.amounts || {}).reduce((sum: number, value) => sum + toNumber(value), 0))}</td></tr></tfoot></table> : <p className="mp-empty">Илүү цаг бүртгэгдээгүй.</p>}</section>
      </div>

      <section className="payroll-v2-section"><div className="payroll-v2-section-head"><h2>Сүүлийн саруудын тренд</h2></div><PayrollTrendChart points={data.trend} /></section>

      {stats && Object.keys(stats.by_department || {}).length > 0 && <section className="payroll-v2-section"><div className="payroll-v2-section-head"><h2>Хэлтсээр</h2></div><div className="mp-table-wrap"><table className="mp-table compact"><thead><tr><th className="mp-text">Хэлтэс</th><th>Ажилтан</th><th>Олговол зохих</th><th>НДШ</th><th>ХХОАТ</th><th>БНДШ</th><th>Нийт зардал</th><th>Хувь</th></tr></thead><tbody>{Object.entries(stats.by_department as Record<string, any>).map(([name, group]) => <tr key={name}><th className="mp-text">{name}</th><td className="mp-num">{group.headcount}</td><td className="mp-num">{formatAmount(group.gross)}</td><td className="mp-num">{formatAmount(group.employee_shi)}</td><td className="mp-num">{formatAmount(group.pit)}</td><td className="mp-num">{formatAmount(group.employer_shi)}</td><td className="mp-num">{formatAmount(group.company_cost)}</td><td className="mp-num">{group.share}%</td></tr>)}</tbody></table></div></section>}

      {data.status === 'closed' && stats && <section className="payroll-v2-stage-card"><h2>Сарын хаалтын тайлан</h2><div className="mp-closing-mini">
        <span>Ажилтан<b>{stats.headcount?.on_register}</b></span><span>Шинэ / гарсан<b>{stats.headcount?.new} / {stats.headcount?.left}</b></span>
        <span>Дундаж олговол зохих<b>{formatMoney(stats.averages?.average_gross)}</b></span><span>Медиан<b>{formatMoney(stats.averages?.median_gross)}</b></span>
        {stats.comparison && <span>Өмнөх сараас (зардал)<b>{stats.comparison.metrics?.company_cost?.change_pct ?? '—'}%</b></span>}
      </div><Link to="/erp/payroll/monthly/archive">Архив нээх</Link></section>}
    </>}
  </MonthlyShell>
}
