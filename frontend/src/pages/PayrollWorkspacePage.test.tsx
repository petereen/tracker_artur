import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { canManagePayroll, formatPayrollMoney, localDateValue, payrollDocumentStatusLabel, payrollEntryNextAction } from './PayrollWorkspacePage'
import { PayrollWorkspaceTabs, buildPayrollTrend, payrollPercentDelta, payrollSectionForPath } from '../components/payroll/PayrollWorkspaceUI'

describe('payroll workspace policy helpers', () => {
  it('only grants management affordances to payroll administrators/managers', () => {
    expect(canManagePayroll(['member'])).toBe(false)
    expect(canManagePayroll(['manager'])).toBe(false)
    expect(canManagePayroll(['admin'])).toBe(true)
  })

  it('formats MNT amounts for review', () => {
    expect(formatPayrollMoney('1234567')).toMatch(/1,234,567/)
  })

  it('formats payroll dates from the local calendar', () => {
    expect(localDateValue(new Date(2026, 8, 7))).toBe('2026-09-07')
  })

  it('maps Frappe document states to Mongolian labels and the next safe action', () => {
    expect(payrollDocumentStatusLabel('submitted')).toBe('Илгээсэн')
    expect(payrollDocumentStatusLabel('cancelled')).toBe('Цуцалсан')
    expect(payrollEntryNextAction({ document_status: 'draft' })).toBe('get-employees')
    expect(payrollEntryNextAction({ document_status: 'draft', salary_slips_created: true })).toBe('submit-slips')
    expect(payrollEntryNextAction({ document_status: 'submitted', salary_slips_created: true, salary_slips_submitted: true })).toBe('make-bank-entry')
  })

  it('aggregates the latest twelve months, excludes cancelled entries, and preserves empty months', () => {
    const entries = [
      { id: 1, period_start: '2026-09-01', period_end: '2026-09-30', total_net: '100', total_pit: '10', total_employee_shi: '5', total_employer_shi: '8', document_status: 'submitted', status: 'submitted' },
      { id: 2, period_start: '2026-08-01', period_end: '2026-08-31', total_net: '50', total_pit: '4', total_employee_shi: '2', total_employer_shi: '3', document_status: 'submitted', status: 'submitted' },
      { id: 3, period_start: '2026-09-01', period_end: '2026-09-30', total_net: '999', total_pit: '999', total_employee_shi: '999', total_employer_shi: '999', document_status: 'cancelled', status: 'cancelled' },
    ] as any
    const trend = buildPayrollTrend(entries, new Date(2026, 8, 15))
    expect(trend).toHaveLength(12)
    expect(trend.map((point) => point.monthKey)).toEqual(['2025-10', '2025-11', '2025-12', '2026-01', '2026-02', '2026-03', '2026-04', '2026-05', '2026-06', '2026-07', '2026-08', '2026-09'])
    expect(trend[10]).toMatchObject({ net: 50, pit: 4, shi: 5 })
    expect(trend[11]).toMatchObject({ net: 100, pit: 10, shi: 13 })
    expect(trend.slice(0, 10).every((point) => point.net === 0 && point.pit === 0 && point.shi === 0)).toBe(true)
  })

  it('keeps comparisons safe for zero and missing previous periods', () => {
    expect(payrollPercentDelta(100, 0)).toBeNull()
    expect(payrollPercentDelta(100, undefined)).toBeNull()
    expect(payrollPercentDelta(110, 100)).toBe(10)
  })

  it('groups every payroll route into an active module section', () => {
    expect(payrollSectionForPath('/erp/payroll')).toBe('overview')
    expect(payrollSectionForPath('/erp/payroll/salary-structures')).toBe('setup')
    expect(payrollSectionForPath('/erp/payroll/payroll-entries/42')).toBe('entries')
    expect(payrollSectionForPath('/erp/payroll/salary-slips')).toBe('payslips')
    expect(payrollSectionForPath('/erp/payroll/reports/bank-remittance')).toBe('reports')
    expect(payrollSectionForPath('/erp/payroll/tax-benefits')).toBe('reports')
  })

  it('exposes an accessible active tab for nested payroll routes', () => {
    render(<MemoryRouter initialEntries={['/erp/payroll/payroll-entries/42']}><PayrollWorkspaceTabs /></MemoryRouter>)
    expect(screen.getByRole('link', { name: 'Payroll Entries' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Тойм' })).not.toHaveAttribute('aria-current', 'page')
  })
})
