import { type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useActor, usePayrollCapabilities } from '../api/enterprise'
import i18n from '../i18n'
import { MonthlyPayrollDashboard, MonthlyPayrollWorkspace } from './MonthlyPayrollWorkspace'
import { MonthlyShell } from './monthly-payroll/shared'

// Shared helpers still used by legacy payroll modules (setup hub, documents, tax benefits).
export const formatPayrollMoney = (value: string) => new Intl.NumberFormat(undefined, { style: 'currency', currency: 'MNT', maximumFractionDigits: 0 }).format(Number(value || 0))
export const canManagePayroll = (roles: string[]) => roles.includes('admin') || roles.includes('hr') || roles.includes('payroll_manager')
export const localDateValue = (value = new Date()) => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`
export function payrollDocumentStatusLabel(status?: string | null) { return (status && i18n.exists(`mp.docStatus.${status}`) ? i18n.t(`mp.docStatus.${status}`) : status?.replaceAll('_', ' ')) || i18n.t('mp.docStatus.unknown') }
export function payrollEntryNextAction(entry: { document_status?: string | null; salary_slips_created?: boolean; salary_slips_submitted?: boolean; bank_entry_id?: number | null }) { if (entry.document_status === 'cancelled') return 'amend'; if (!entry.salary_slips_created) return 'get-employees'; if (!entry.salary_slips_submitted) return 'submit-slips'; if (!entry.bank_entry_id) return 'make-bank-entry'; return 'view' }
export function PayrollShell({ children, actions }: { children: ReactNode; actions?: ReactNode }) { return <MonthlyShell actions={actions}>{children}</MonthlyShell> }

const RETIRED_ROUTES = ['/setup', '/inputs', '/runs', '/payroll-entries', '/salary-components', '/payroll-periods', '/salary-structures', '/accounting', '/additional-salaries', '/assignments', '/salary-slips', '/reports']

export function PayrollWorkspacePage() {
  const location = useLocation()
  const actor = useActor()
  const permissions = usePayrollCapabilities()
  const manager = Boolean(permissions.data?.capabilities.view) || canManagePayroll(actor.data?.roles || [])
  if (!manager) return <Navigate to="/hr" replace />
  const path = location.pathname
  // The previous multi-step payroll workflow is retired; its routes land on the monthly dashboard.
  if (RETIRED_ROUTES.some((route) => path === `/erp/payroll${route}` || path.startsWith(`/erp/payroll${route}/`))) return <Navigate to="/erp/payroll" replace />
  if (path.endsWith('/monthly/reports')) return <MonthlyPayrollWorkspace reports />
  if (path.endsWith('/monthly/settings')) return <MonthlyPayrollWorkspace settings />
  if (path.endsWith('/monthly/archive')) return <MonthlyPayrollWorkspace archive />
  if (path.includes('/monthly/runs/')) return <MonthlyPayrollWorkspace detail />
  if (path.endsWith('/monthly')) return <MonthlyPayrollWorkspace />
  return <MonthlyPayrollDashboard />
}
