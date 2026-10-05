import { Link, useLocation } from 'react-router-dom'
import { BarChart3, ClipboardList, Landmark, LayoutDashboard, Receipt, Settings2, WalletCards, type LucideIcon } from 'lucide-react'
import type { PayrollEntry } from '../../api/enterprise'
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

const tabs: Array<{ id: PayrollSection; label: string; href: string; icon: LucideIcon }> = [
  { id: 'overview', label: 'Тойм', href: '/erp/payroll', icon: LayoutDashboard },
  { id: 'setup', label: 'Тохиргоо', href: '/erp/payroll/salary-components', icon: Settings2 },
  { id: 'entries', label: 'Payroll Entries', href: '/erp/payroll/payroll-entries', icon: ClipboardList },
  { id: 'payslips', label: 'Salary Slips', href: '/erp/payroll/salary-slips', icon: Receipt },
  { id: 'reports', label: 'Тайлан', href: '/erp/payroll/reports/salary-register', icon: BarChart3 },
]

export function PayrollWorkspaceTabs() {
  const location = useLocation()
  const active = payrollSectionForPath(location.pathname)
  return <nav className="page-tabs"><div className="page-tabs-list" aria-label="Payroll module sections">
    {tabs.map((tab) => <Link key={tab.id} to={tab.href} className={active === tab.id ? 'active' : undefined} aria-current={active === tab.id ? 'page' : undefined}><tab.icon size={15} />{tab.label}</Link>)}
    <Link to="/erp/payroll/additional-salaries"><WalletCards size={15} />Нэмэлт цалин</Link>
    <Link to="/erp/payroll/tax-benefits"><Landmark size={15} />Татвар &amp; benefits</Link>
  </div></nav>
}
