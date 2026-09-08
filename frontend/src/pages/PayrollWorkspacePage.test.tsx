import { describe, expect, it } from 'vitest'
import { canManagePayroll, formatPayrollMoney, localDateValue, payrollDocumentStatusLabel, payrollEntryNextAction } from './PayrollWorkspacePage'

describe('payroll workspace policy helpers', () => {
  it('only grants management affordances to payroll administrators/managers', () => {
    expect(canManagePayroll(['member'])).toBe(false)
    expect(canManagePayroll(['manager'])).toBe(true)
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
})
