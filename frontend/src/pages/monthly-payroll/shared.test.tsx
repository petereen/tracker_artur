import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { formatAmount, formatMoney, requestError, rowState, runTitle, shiftMonth } from './shared'
import { PayrollTrendChart } from './Dashboard'

const row = (overrides: Record<string, unknown> = {}) => ({ id: 1, employee_id: 1, status: 'draft', identity: {}, profile: {}, inputs: {}, result: {}, warnings: [], approved_at: null, audit: [], ...overrides }) as any

describe('monthly payroll helpers', () => {
  it('formats whole tugrik with thousand separators and no decimals', () => {
    expect(formatMoney('838142.4')).toBe('838,142 ₮')
    expect(formatAmount('1788000')).toBe('1,788,000')
  })

  it('turns structured API errors into readable Mongolian messages', () => {
    expect(requestError({ response: { data: { detail: { code: 'monthly_payroll_row_blocked', employee_name: 'Бат', issues: ['negative_final_pay', 'advance_changed'] } } } })).toBe('Бат: Сүүл цалин сөрөг, Урьдчилгаа өөрчлөгдсөн')
    expect(requestError({ response: { data: { detail: [{ loc: ['body', 'worked_normal_hours'], msg: 'Input should be a valid decimal' }] } } })).toBe('worked_normal_hours: Input should be a valid decimal')
    expect(requestError({ response: { data: { detail: 'Сар хаагдсан' } } })).toBe('Сар хаагдсан')
    expect(requestError({})).toBe('Үйлдэл амжилтгүй боллоо.')
  })

  it('derives the register status chip from approval, blocking warnings, flags and edits', () => {
    expect(rowState(row({ status: 'approved' }))).toBe('approved')
    expect(rowState(row({ warnings: ['negative_final_pay'] }))).toBe('error')
    expect(rowState(row({ warnings: ['advance_not_calculated'] }))).toBe('draft')
    expect(rowState(row({ status: 'flagged', warnings: ['row_flagged'] }))).toBe('attention')
    expect(rowState(row({ audit: [{ field: 'inputs', old: null, new: null, reason: 'x', account_id: 1, at: '2026-08-01' }] }))).toBe('edited')
  })

  it('names runs and steps months across year boundaries', () => {
    expect(runTitle({ run_type: 'advance', pay_date: '2026-08-10' })).toBe('Урьдчилгаа — 10-ны өдөр')
    expect(runTitle({ run_type: 'final', pay_date: '2026-08-31' })).toBe('Сүүл цалин')
    expect(shiftMonth('2026-01', -1)).toBe('2025-12')
    expect(shiftMonth('2026-12', 1)).toBe('2027-01')
  })

  it('renders the trend chart with a legend, end labels and a table view', () => {
    render(<PayrollTrendChart points={[
      { month: '2026-07', status: 'closed', gross: '3400000', company_cost: '3800000', headcount: 3 },
      { month: '2026-08', status: 'open', gross: '3576000', company_cost: '4023000', headcount: 4 },
    ]} />)
    expect(screen.getByRole('img', { name: /тренд/ })).toBeTruthy()
    expect(screen.getAllByText('Олговол зохих').length).toBeGreaterThan(0)
    expect(screen.getByText('4 сая')).toBeTruthy()
    expect(screen.getByText('4,023,000')).toBeTruthy()
  })
})
