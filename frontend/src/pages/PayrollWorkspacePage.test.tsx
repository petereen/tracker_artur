import { describe, expect, it } from 'vitest'
import { canManagePayroll, formatPayrollMoney, runSequenceState } from './PayrollWorkspacePage'

describe('payroll workspace policy helpers', () => {
  it('only grants management affordances to payroll administrators/managers', () => {
    expect(canManagePayroll(['member'])).toBe(false)
    expect(canManagePayroll(['manager'])).toBe(true)
    expect(canManagePayroll(['admin'])).toBe(true)
  })

  it('formats MNT amounts for review', () => {
    expect(formatPayrollMoney('1234567')).toMatch(/1,234,567/)
  })

  it('keeps the seven-stage sequence aligned with the run lifecycle', () => {
    expect(runSequenceState({ status: 'draft' })).toEqual({ completedThrough: 2, activeStep: 2 })
    expect(runSequenceState({ status: 'calculated' }).activeStep).toBe(3)
    expect(runSequenceState({ status: 'in_review' }).activeStep).toBe(4)
    expect(runSequenceState({ status: 'approved' }).activeStep).toBe(5)
    expect(runSequenceState({ status: 'posted' }).activeStep).toBe(6)
    expect(runSequenceState({ status: 'posted', payslips_published_at: '2026-08-27T12:00:00Z' })).toEqual({ completedThrough: 7, activeStep: -1 })
  })
})
