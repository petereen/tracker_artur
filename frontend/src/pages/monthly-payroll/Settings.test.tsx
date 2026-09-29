import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MonthlyPayrollSettingsPage } from './Settings'

const mocks = vi.hoisted(() => ({ save: vi.fn() }))
const settings = {
  legal_company_name: 'Оюунс ХХК', daily_norm_hours: '8', employer_injury_rate: '0.005', weekday_overtime_multiplier: '1.5', rest_day_overtime_multiplier: '1.5',
  public_holiday_overtime_multiplier: '2', default_advance_basis: 'FIXED', default_advance_percent: '40', deduction_types: ['Бусад'],
  salary_expense_account_id: 2, employer_shi_account_id: null, advance_clearing_account_id: null,
}
const accounts = [
  { id: 1, code: '2350', name: 'Цалингийн урьдчилгааны тооцоо', classification: 'asset', purpose: 'advance_clearing', is_active: true, is_group: false },
  { id: 2, code: '5100', name: 'Цалингийн зардал', classification: 'expense', purpose: 'salary_expense', is_active: true, is_group: false },
  { id: 4, code: '4000', name: 'Борлуулалтын орлого', classification: 'income', purpose: 'income', is_active: true, is_group: false },
]

vi.mock('../../api/enterprise', () => ({
  usePayrollCapabilities: () => ({ data: { capabilities: { administer: true } } }),
  useMonthlyPayrollSettings: () => ({ data: settings }),
  useSaveMonthlyPayrollSettings: () => ({ mutate: mocks.save, isPending: false }),
  useERPAccountOptions: () => ({ data: accounts }),
  useMonthlyPayrollRuleSets: () => ({ data: [], isLoading: false }),
  useMonthlyPayrollRuleTemplate: () => ({ data: undefined }),
  useCreateMonthlyPayrollRuleDraft: () => ({ isPending: false }),
  useUpdateMonthlyPayrollRuleDraft: () => ({ isPending: false }),
  useValidateMonthlyPayrollRuleDraft: () => ({ isPending: false }),
  usePublishMonthlyPayrollRuleDraft: () => ({ isPending: false }),
  useMonthlyPayrollCalendar: () => ({ data: [] }),
  useMonthlyPayrollMonths: () => ({ data: [] }),
  useSetMonthlyPayrollCalendarDay: () => ({ mutate: vi.fn(), isPending: false }),
}))

vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() }))

describe('MonthlyPayrollSettingsPage', () => {
  beforeEach(() => mocks.save.mockReset())

  it('keeps save disabled until something changes, then saves the edited settings', () => {
    render(<MemoryRouter><MonthlyPayrollSettingsPage /></MemoryRouter>)
    const saveButton = screen.getByRole('button', { name: 'Тохиргоо хадгалах' })
    expect(saveButton).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Компанийн нэр'), { target: { value: 'Шинэ ХХК' } })
    expect(screen.getByText('Хадгалаагүй өөрчлөлт байна')).toBeInTheDocument()
    expect(saveButton).toBeEnabled()
    fireEvent.click(saveButton)
    expect(mocks.save).toHaveBeenCalledWith(expect.objectContaining({ legal_company_name: 'Шинэ ХХК', daily_norm_hours: '8' }), expect.anything())
  })

  it('offers the advance account from asset and expense accounts only', () => {
    render(<MemoryRouter><MonthlyPayrollSettingsPage /></MemoryRouter>)
    expect(screen.getByText(/Хөрөнгө \(жишээ: 2350/)).toBeInTheDocument()
    expect(screen.getByText('Дансны холболт')).toBeInTheDocument()
  })
})
