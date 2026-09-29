import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { BudgetWorkspacePage } from './BudgetWorkspacePage'

const mocks = vi.hoisted(() => ({
  capabilities: { current: null as unknown },
  saveLines: vi.fn(),
  transactions: vi.fn(),
  generate: vi.fn(),
  detail: { current: null as unknown },
}))
const all = { view: true, create: true, edit: true, approve: true, archive: true, export: true }
const fullCaps = { module_enabled: true, budgets: all, settings: { view: true, create: true, edit: true, archive: true } }
const lookups = {
  currency: 'MNT',
  groups: [{ id: 1, code: 'INCOME', name: 'Орлого', kind: 'income', parent_id: null, sort: 10, is_active: true }, { id: 3, code: 'EXPENSE', name: 'Үйл ажиллагааны зардал', kind: 'expense', parent_id: null, sort: 30, is_active: true }],
  accounts: [
    { id: 11, code: '4000', name: 'Борлуулалтын орлого', kind: 'income', group_id: 1, group_name: 'Орлого', note: null, sort: 0, is_active: true, erp_accounts: [{ id: 101, code: '4000', name: 'Sales', classification: 'income' }], in_use: true },
    { id: 12, code: 'MKT', name: 'Маркетинг', kind: 'expense', group_id: 3, group_name: 'Үйл ажиллагааны зардал', note: null, sort: 0, is_active: true, erp_accounts: [], in_use: true },
  ],
  erp_accounts: [
    { id: 101, code: '4000', name: 'Sales', classification: 'income', is_active: true, budget_account_id: 11 },
    { id: 102, code: '6900', name: 'Бусад зардал', classification: 'expense', is_active: true, budget_account_id: null },
  ],
  projects: [], party_groups: [],
}
const budget = {
  id: 5, public_id: 'b', number: 'BUD-0001', name: '2026 оны үндсэн төсөв', purpose: 'Жилийн зорилт', scenario: 'base', period_type: 'quarter', start_date: '2026-01-01', end_date: '2026-12-31',
  project_id: null, project_name: null, currency: 'MNT', status: 'draft', is_primary: true, copied_from_id: null, approved_at: null, approved_by: null, created_by: 'Админ',
  totals: { income: '1200.00', cogs: '0.00', expense: '-400.00', other: '0.00', profit: '800.00' }, version: 3, created_at: null, updated_at: null,
}
const columns = ['01', '04', '07', '10'].map((month, index) => ({ start: `2026-${month}-01`, end: `2026-${month}-28`, label: `2026 Q${index + 1}` }))
const detail = {
  ...budget, columns,
  rows: [
    { budget_account_id: 11, account_code: '4000', account_name: 'Борлуулалтын орлого', kind: 'income', project_id: null, party_group_id: null, note: null, amounts: { '2026-01-01': '300' }, total: '300' },
    // A positive expense violates the d161 sign rule and must be flagged.
    { budget_account_id: 12, account_code: 'MKT', account_name: 'Маркетинг', kind: 'expense', project_id: null, party_group_id: null, note: null, amounts: { '2026-01-01': '40' }, total: '40' },
  ],
}
const measures = (budgeted: string, expected: string, actual: string, status = 'favorable', pct = '108.3') => ({ budgeted, expected, actual, variance: String(Number(actual) - Number(expected)), remaining: '0', performance_pct: pct, status })
const analysis = {
  budget,
  window: { date_from: '2026-01-01', date_to: '2026-12-31', as_of: '2026-06-30', elapsed_pct: '49.6' },
  group_by: ['account'], dimension_labels: { account: 'Төсөвт данс' },
  rows: [
    { key: { account: 11 }, labels: { account: '4000 · Борлуулалтын орлого' }, kind: 'income', ...measures('1200', '600', '650') },
    { key: { account: 12 }, labels: { account: 'MKT · Маркетинг' }, kind: 'expense', ...measures('-80', '-40', '-55', 'unfavorable', '137.5') },
  ],
  totals: { income: measures('1200', '600', '650'), cogs: measures('0', '0', '0', 'no_activity', ''), expense: measures('-80', '-40', '-55', 'unfavorable'), other: measures('0', '0', '0', 'no_activity', ''), profit: measures('1120', '560', '595') },
  unmapped: [{ erp_account_id: 102, code: '6900', name: 'Бусад зардал', classification: 'expense', actual: '-7.00' }],
}
const idle = { mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }

vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() }))

vi.mock('../api/enterprise', () => ({ useActor: () => ({ data: { roles: ['admin'] } }) }))
vi.mock('../api/budget', () => ({
  useBudgetCapabilities: () => ({ data: mocks.capabilities.current, isLoading: false, isError: false }),
  useBudgetLookups: () => ({ data: lookups, isLoading: false }),
  useBudgets: () => ({ data: { items: [budget] }, isLoading: false }),
  useBudget: () => ({ data: mocks.detail.current, isLoading: false, isError: false, refetch: vi.fn() }),
  useBudgetAnalysis: () => ({ data: analysis, isLoading: false, isError: false }),
  useBudgetTransactions: (filters: unknown) => { if (filters) mocks.transactions(filters); return { data: { total_count: 1, total_amount: '-55.00', items: [], window: { date_from: '2026-01-01', as_of: '2026-06-30' } }, isLoading: false, isError: false } },
  useSaveBudgetLines: () => ({ ...idle, mutateAsync: mocks.saveLines }),
  useGenerateBudgetAccounts: () => ({ ...idle, mutateAsync: mocks.generate }),
  useBudgetAction: () => idle, useSetPrimaryBudget: () => idle, useDeleteBudget: () => idle, useCreateBudget: () => idle, useUpdateBudget: () => idle,
  useCopyBudget: () => idle, useImportBudget: () => idle, useSaveBudgetGroup: () => idle, useDeleteBudgetGroup: () => idle,
  useSaveBudgetAccount: () => idle, useDeleteBudgetAccount: () => idle,
  downloadBudgetWorkbook: vi.fn(), downloadBudgetAnalysis: vi.fn(),
}))

const renderAt = (path: string) => render(<MemoryRouter initialEntries={[path]}><Routes>
  <Route path="/erp/budget" element={<BudgetWorkspacePage />} />
  <Route path="/erp/budget/analysis" element={<BudgetWorkspacePage />} />
  <Route path="/erp/budget/accounts" element={<BudgetWorkspacePage />} />
  <Route path="/erp/budget/:budgetId" element={<BudgetWorkspacePage />} />
</Routes></MemoryRouter>)

describe('BudgetWorkspacePage', () => {
  beforeAll(() => {
    // jsdom has no modal <dialog>; Astryx Dialog calls showModal/close.
    HTMLDialogElement.prototype.showModal ??= function showModal(this: HTMLDialogElement) { this.setAttribute('open', '') }
    HTMLDialogElement.prototype.close ??= function close(this: HTMLDialogElement) { this.removeAttribute('open') }
  })
  beforeEach(() => {
    mocks.capabilities.current = fullCaps
    mocks.detail.current = detail
    mocks.saveLines.mockReset().mockResolvedValue(detail)
    mocks.transactions.mockReset()
    mocks.generate.mockReset().mockResolvedValue({ created: 1, accounts: [] })
  })

  it('lists budgets with scenario, totals and the primary marker', () => {
    renderAt('/erp/budget')
    expect(screen.getByRole('link', { name: '2026 оны үндсэн төсөв' })).toHaveAttribute('href', '/erp/budget/5')
    expect(screen.getAllByText('Үндсэн (Base)').length).toBeGreaterThan(0)
    expect(screen.getByLabelText('Хүчин төгөлдөр')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /Шинэ төсөв/ }).length).toBeGreaterThan(0)
  })

  it('flags wrong signs in the editor, fixes them and saves signed amounts', async () => {
    renderAt('/erp/budget/5')
    expect(screen.getByText('1 нүдний тэмдэг буруу байна')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Тэмдгийг засах' }))
    expect(screen.queryByText(/нүдний тэмдэг буруу/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Хадгалах' }))
    await waitFor(() => expect(mocks.saveLines).toHaveBeenCalled())
    const payload = mocks.saveLines.mock.calls[0][0]
    expect(payload.version).toBe(3)
    expect(payload.rows).toEqual([
      { budget_account_id: 11, project_id: null, party_group_id: null, note: null, amounts: { '2026-01-01': '300' } },
      { budget_account_id: 12, project_id: null, party_group_id: null, note: null, amounts: { '2026-01-01': '-40' } },
    ])
  })

  it('keeps approved budgets read-only', () => {
    mocks.detail.current = { ...detail, status: 'approved', approved_by: 'Админ' }
    renderAt('/erp/budget/5')
    expect(screen.getByText('Батлагдсан · Админ')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Хадгалах' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ноорог болгох' })).toBeInTheDocument()
  })

  it('compares planned, should-be and actual, warns about unmapped accounts and drills down', async () => {
    renderAt('/erp/budget/analysis')
    expect(screen.getByText('4000 · Борлуулалтын орлого')).toBeInTheDocument()
    expect(screen.getAllByText(/^137[.,]5%$/).length).toBeGreaterThan(0)
    expect(screen.getByText(/холбогдоогүй 1 санхүүгийн данс/)).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: 'Гүйлгээ харах' })[1])
    await waitFor(() => expect(mocks.transactions).toHaveBeenCalledWith(expect.objectContaining({ budget_id: 5, budget_account_id: 12 })))
  })

  it('offers to generate budget accounts for unlinked income and expense accounts', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderAt('/erp/budget/accounts')
    expect(screen.getByText('1 орлого/зардлын данс төсөвт дансанд холбогдоогүй')).toBeInTheDocument()
    expect(screen.getByText('Холбоогүй')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Дансны төлөвлөгөөнөөс үүсгэх' }))
    await waitFor(() => expect(mocks.generate).toHaveBeenCalled())
  })

  it('explains missing access instead of showing data', () => {
    mocks.capabilities.current = { module_enabled: true, budgets: { ...all, view: false }, settings: { view: false, create: false, edit: false, archive: false } }
    renderAt('/erp/budget')
    expect(screen.getByText('Төсөв модульд хандах эрх танд олгогдоогүй байна')).toBeInTheDocument()
  })
})
