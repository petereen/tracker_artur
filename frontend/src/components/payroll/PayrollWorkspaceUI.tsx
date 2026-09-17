import { Link, useLocation } from 'react-router-dom'
import { ArrowUpRight, BarChart3, ClipboardList, Landmark, WalletCards, type LucideIcon } from 'lucide-react'
import type { PayrollEntry, PayrollPayslip } from '../../api/enterprise'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

export type PayrollTrendPoint = {
  monthKey: string
  label: string
  net: number
  pit: number
  shi: number
}

const numeric = (value?: string | number | null) => Number(value || 0)

/** Aggregate active payroll entries into a stable twelve-month chart window. */
export function buildPayrollTrend(entries: PayrollEntry[], now = new Date()): PayrollTrendPoint[] {
  const start = new Date(now.getFullYear(), now.getMonth() - 11, 1)
  const months = Array.from({ length: 12 }, (_, index) => {
    const date = new Date(start.getFullYear(), start.getMonth() + index, 1)
    const monthKey = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
    return { monthKey, date, net: 0, pit: 0, shi: 0 }
  })
  const byMonth = new Map(months.map((month) => [month.monthKey, month]))
  entries.filter((entry) => (entry.document_status || entry.status) !== 'cancelled').forEach((entry) => {
    const source = entry.period_end || entry.period_start
    if (!source) return
    const monthKey = source.slice(0, 7)
    const point = byMonth.get(monthKey)
    if (!point) return
    point.net += numeric(entry.total_net)
    point.pit += numeric(entry.total_pit)
    point.shi += numeric(entry.total_employee_shi) + numeric(entry.total_employer_shi)
  })
  return months.map(({ monthKey, date, net, pit, shi }) => ({
    monthKey,
    label: new Intl.DateTimeFormat('mn-MN', { month: 'short' }).format(date),
    net,
    pit,
    shi,
  }))
}

export function payrollPercentDelta(current: number, previous: number | null | undefined) {
  if (previous === null || previous === undefined || previous === 0) return null
  return ((current - previous) / Math.abs(previous)) * 100
}

export type PayrollSection = 'overview' | 'setup' | 'entries' | 'payslips' | 'reports'

export function payrollSectionForPath(pathname: string): PayrollSection {
  if (pathname.includes('/payroll-entries')) return 'entries'
  if (pathname.endsWith('/salary-slips')) return 'payslips'
  if (pathname.includes('/reports/') || pathname.endsWith('/tax-benefits')) return 'reports'
  if (pathname.endsWith('/salary-components') || pathname.endsWith('/salary-structures') || pathname.endsWith('/payroll-periods') || pathname.endsWith('/assignments') || pathname.endsWith('/additional-salaries') || pathname.endsWith('/accounting')) return 'setup'
  return 'overview'
}

const tabs: Array<{ id: PayrollSection; label: string; href: string }> = [
  { id: 'overview', label: 'Тойм', href: '/erp/payroll' },
  { id: 'setup', label: 'Тохиргоо', href: '/erp/payroll/salary-components' },
  { id: 'entries', label: 'Payroll Entries', href: '/erp/payroll/payroll-entries' },
  { id: 'payslips', label: 'Salary Slips', href: '/erp/payroll/salary-slips' },
  { id: 'reports', label: 'Тайлан', href: '/erp/payroll/reports/salary-register' },
]

export function PayrollWorkspaceTabs() {
  const location = useLocation()
  const active = payrollSectionForPath(location.pathname)
  return <nav className="payroll-reference-tabs" aria-label="Payroll module sections">
    {tabs.map((tab) => <Link key={tab.id} to={tab.href} className={`payroll-reference-tab${active === tab.id ? ' active' : ''}`} aria-current={active === tab.id ? 'page' : undefined}>{tab.label}</Link>)}
    <Link className="payroll-reference-tab payroll-reference-tab-shortcut" to="/erp/payroll/additional-salaries">Нэмэлт цалин</Link>
    <Link className="payroll-reference-tab payroll-reference-tab-shortcut" to="/erp/payroll/tax-benefits">Татвар &amp; benefits</Link>
  </nav>
}

export function PayrollMetricCard({ label, value, detail, icon: Icon, tone = 'blue' }: { label: string; value: string; detail: string; icon: LucideIcon; tone?: 'blue' | 'green' | 'orange' | 'purple' }) {
  return <article className={`payroll-reference-kpi payroll-reference-kpi-${tone}`}>
    <div className="payroll-reference-kpi-icon"><Icon size={17} /></div>
    <span className="eyebrow">{label}</span>
    <strong>{value}</strong>
    <small>{detail}</small>
  </article>
}

const formatMnt = (value: number) => new Intl.NumberFormat('mn-MN', { style: 'currency', currency: 'MNT', maximumFractionDigits: 0 }).format(value)

export function PayrollAnnualChart({ data }: { data: PayrollTrendPoint[] }) {
  const hasData = data.some((point) => point.net || point.pit || point.shi)
  return <section className="payroll-reference-chart" aria-label="Сүүлийн 12 сарын payroll trend">
    <div className="payroll-reference-chart-header"><div><span className="eyebrow">ANNUAL BREAKDOWN</span><h2>Цалингийн жилийн тойм</h2><p>Сүүлийн 12 сарын net pay, PIT, нийт SHI</p></div><BarChart3 size={19} /></div>
    {hasData ? <div className="payroll-reference-chart-body"><ResponsiveContainer width="100%" height={240}><BarChart data={data} margin={{ top: 8, right: 4, left: 8, bottom: 2 }}>
      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--color-border)" />
      <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: 'var(--color-muted)' }} />
      <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 10, fill: 'var(--color-muted)' }} tickFormatter={(value) => `${Math.round(Number(value) / 1000000)}m`} width={34} />
      <Tooltip formatter={(value: number) => formatMnt(value)} contentStyle={{ borderRadius: 10, border: '1px solid var(--color-border)', background: 'var(--color-panel)', color: 'var(--color-text)' }} />
      <Legend iconType="circle" wrapperStyle={{ fontSize: 11 }} />
      <Bar dataKey="net" name="Net pay" stackId="payroll" fill="#2d62ec" radius={[4, 4, 0, 0]} />
      <Bar dataKey="pit" name="PIT" stackId="payroll" fill="#ff833b" />
      <Bar dataKey="shi" name="SHI" stackId="payroll" fill="#7657e8" />
    </BarChart></ResponsiveContainer></div> : <div className="payroll-reference-chart-empty"><BarChart3 size={22} /><span>Сүүлийн 12 сард тооцоолсон payroll entry алга.</span></div>}
  </section>
}

export function PayrollHistoryTable({ entries, statusLabel, formatMoney }: { entries: PayrollEntry[]; statusLabel: (status?: string | null) => string; formatMoney: (value: string) => string }) {
  return <div className="payroll-reference-table-wrap"><table className="payroll-reference-table"><caption className="sr-only">Payroll entry history</caption><thead><tr><th>Payroll Entry</th><th>Төрөл</th><th>Үе</th><th className="numeric">Gross</th><th className="numeric">Net pay</th><th>Төлөв</th><th><span className="sr-only">Үйлдэл</span></th></tr></thead><tbody>{entries.map((entry) => { const status = entry.document_status || entry.status; return <tr key={entry.id}><td><Link className="payroll-reference-record" to={`/erp/payroll/payroll-entries/${entry.id}`}><strong>{entry.run_number}</strong><small>{entry.posting_date || entry.period_end}</small></Link></td><td>{entry.run_type}</td><td>{entry.period_start} – {entry.period_end}</td><td className="numeric">{formatMoney(entry.total_gross)}</td><td className="numeric"><strong>{formatMoney(entry.total_net)}</strong></td><td><span className={`payroll-status payroll-status-${status || 'unknown'}`}><span aria-hidden="true" />{statusLabel(status)}</span></td><td><Link className="payroll-reference-row-action" to={`/erp/payroll/payroll-entries/${entry.id}`} aria-label={`${entry.run_number} дэлгэрэнгүй`}><ArrowUpRight size={15} /></Link></td></tr> })}</tbody></table></div>
}

export function PayrollPayslipTable({ slips, statusLabel, formatMoney }: { slips: PayrollPayslip[]; statusLabel: (status?: string | null) => string; formatMoney: (value: string) => string }) {
  return <div className="payroll-reference-table-wrap"><table className="payroll-reference-table payroll-reference-payslip-table"><caption className="sr-only">Employee salary slips</caption><thead><tr><th>Ажилтан</th><th>Payroll Entry</th><th className="numeric">Gross</th><th className="numeric">SHI</th><th className="numeric">PIT</th><th className="numeric">Net pay</th><th>Төлөв</th></tr></thead><tbody>{slips.map((slip) => <tr key={slip.id}><td><strong>Employee #{slip.employee_id}</strong><small className="payroll-reference-cell-note">Slip #{slip.id}</small></td><td>#{slip.payroll_run_id}</td><td className="numeric">{formatMoney(slip.gross)}</td><td className="numeric">{formatMoney(slip.employee_shi)}</td><td className="numeric">{formatMoney(slip.pit)}</td><td className="numeric"><strong>{formatMoney(slip.net_pay)}</strong></td><td><span className={`payroll-status payroll-status-${slip.document_status || 'submitted'}`}><span aria-hidden="true" />{statusLabel(slip.document_status || 'submitted')}</span></td></tr>)}</tbody></table></div>
}

export function PayrollShortcutGrid({ groups }: { groups: Array<{ title: string; icon: LucideIcon; links: Array<{ label: string; href: string; meta?: string }> }> }) {
  return <div className="payroll-reference-shortcuts">{groups.map((group) => <section className="payroll-reference-shortcut-card" key={group.title}><div className="payroll-reference-shortcut-heading"><group.icon size={16} /><h3>{group.title}</h3></div>{group.links.map((link) => <Link to={link.href} key={link.href}><span>{link.label}</span><small>{link.meta || 'Нээх'}</small><ArrowUpRight size={14} /></Link>)}</section>)}</div>
}

export const payrollMetricIcons = { wallet: WalletCards, clipboard: ClipboardList, bank: Landmark }
