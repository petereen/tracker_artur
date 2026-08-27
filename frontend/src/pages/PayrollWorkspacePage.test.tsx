import { describe, expect, it } from 'vitest'
import { canManagePayroll, formatPayrollMoney } from './PayrollWorkspacePage'

describe('payroll workspace policy helpers', () => {
  it('only grants management affordances to payroll administrators/managers', () => {
    expect(canManagePayroll(['member'])).toBe(false)
    expect(canManagePayroll(['manager'])).toBe(true)
    expect(canManagePayroll(['admin'])).toBe(true)
  })

  it('formats MNT amounts for review', () => {
    expect(formatPayrollMoney('1234567')).toMatch(/1,234,567/)
  })
})
