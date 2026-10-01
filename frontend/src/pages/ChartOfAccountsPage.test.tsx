import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ERPAccountOption } from '../api/enterprise'
import { accountSelectorOptions } from '../components/accounts/accountShared'
import { ChartOfAccountsPage } from './ChartOfAccountsPage'

const mocks = vi.hoisted(() => ({ update: vi.fn(), create: vi.fn(), remove: vi.fn(), permissions: { current: null as unknown } }))

const accounts: ERPAccountOption[] = [
  { id: 1, code: '1000', name: 'Касс дахь мөнгө', account_type: 'cash', classification: 'asset', purpose: 'cash', currency: 'MNT', parent_id: null, is_group: false, is_active: true },
  { id: 2, code: '1010', name: 'Харилцах данс (цалин)', account_type: 'cash', classification: 'asset', purpose: 'bank', currency: 'MNT', parent_id: null, is_group: false, is_active: true, bank_name: 'Хаан банк', bank_account_number: '5012345678' },
  { id: 5, code: '5', name: 'Зардлууд', account_type: 'expense', classification: 'expense', purpose: 'general', currency: 'MNT', parent_id: null, is_group: true, is_active: true },
  { id: 6, code: '5100', name: 'Цалингийн зардал', account_type: 'payroll_expense', classification: 'expense', purpose: 'salary_expense', currency: 'MNT', parent_id: 5, is_group: false, is_active: true },
  { id: 7, code: '5000', name: 'Үйл ажиллагааны зардал', account_type: 'expense', classification: 'expense', purpose: 'expense', currency: 'MNT', parent_id: 5, is_group: false, is_active: true },
  { id: 9, code: '10000', name: 'Tsalingiin dans', account_type: 'asset', classification: 'asset', purpose: 'general', currency: 'MNT', parent_id: null, is_group: false, is_active: false },
]
const catalog = {
  classifications: [
    { key: 'asset', label: 'Хөрөнгө', normal_side: 'debit' }, { key: 'liability', label: 'Өр төлбөр', normal_side: 'credit' }, { key: 'equity', label: 'Эздийн өмч', normal_side: 'credit' },
    { key: 'income', label: 'Орлого', normal_side: 'credit' }, { key: 'expense', label: 'Зардал', normal_side: 'debit' },
  ],
  purposes: [
    { key: 'general', label: 'Ерөнхий', classifications: ['asset', 'liability', 'equity', 'income', 'expense'], module: 'general', has_bank_details: false },
    { key: 'cash', label: 'Касс', classifications: ['asset'], module: 'cash', has_bank_details: true },
    { key: 'bank', label: 'Харилцах данс (банк)', classifications: ['asset'], module: 'cash', has_bank_details: true },
    { key: 'expense', label: 'Үйл ажиллагааны зардал', classifications: ['expense'], module: 'general', has_bank_details: false },
    { key: 'salary_expense', label: 'Цалингийн зардал', classifications: ['expense'], module: 'payroll', has_bank_details: false },
  ],
  usage_modules: { ledger: 'Журнал бичилт', payroll: 'Цалин', budget: 'Төсөв', children: 'Дэд данс' },
}
const usage = [
  { account_id: 5, modules: { children: 2 }, total: 2 },
  { account_id: 6, modules: { ledger: 4, payroll: 1 }, total: 5 },
]

vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() }))
vi.mock('../api/budget', () => ({
  useBudgetCapabilities: () => ({ data: { module_enabled: true, budgets: {}, settings: { view: true, create: true, edit: true, archive: true } } }),
  useBudgetLookups: () => ({ data: { accounts: [], erp_accounts: accounts.map((row) => ({ id: row.id, budget_account_id: null })) } }),
  useGenerateBudgetAccounts: () => ({ mutateAsync: vi.fn().mockResolvedValue({ created: 2 }) }),
}))
vi.mock('../api/enterprise', () => ({
  useERPAccountPermissions: () => ({ data: mocks.permissions.current, isLoading: false }),
  useERPAccountOptions: () => ({ data: accounts, isLoading: false }),
  useERPAccountCatalog: () => ({ data: catalog, isLoading: false }),
  useERPAccountUsage: () => ({ data: usage, isLoading: false }),
  useCreateERPAccount: () => ({ mutateAsync: mocks.create, isPending: false }),
  useUpdateERPAccount: () => ({ mutateAsync: mocks.update, isPending: false }),
  useDeleteERPAccount: () => ({ mutateAsync: mocks.remove, isPending: false }),
}))

const renderPage = () => render(<MemoryRouter><ChartOfAccountsPage /></MemoryRouter>)
const rowOf = (text: string) => screen.getAllByText(text)[0].closest('tr') as HTMLElement

describe('ChartOfAccountsPage', () => {
  beforeAll(() => {
    HTMLDialogElement.prototype.showModal ??= function showModal(this: HTMLDialogElement) { this.setAttribute('open', '') }
    HTMLDialogElement.prototype.close ??= function close(this: HTMLDialogElement) { this.removeAttribute('open') }
  })
  beforeEach(() => {
    mocks.permissions.current = { view: true, create: true, edit: true, administer: true }
    mocks.update.mockReset().mockResolvedValue(accounts[3])
    mocks.remove.mockReset().mockResolvedValue({ id: 7, outcome: 'deleted' })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  it('shows the active chart as a tree with purpose, bank details and usage', () => {
    renderPage()
    expect(screen.queryByRole('heading', { name: 'Дансны төлөвлөгөө' })).not.toBeInTheDocument()
    expect(screen.getByText('Хаан банк · 5012345678')).toBeInTheDocument()
    expect(within(rowOf('Цалингийн зардал')).getByText('Журнал бичилт')).toBeInTheDocument()
    expect(within(rowOf('Цалингийн зардал')).getByText('└ 5100')).toBeInTheDocument()
    // Inactive accounts are hidden until the status filter asks for them.
    expect(screen.queryByText('Tsalingiin dans')).not.toBeInTheDocument()
  })

  it('locks the posting identity of an account that is in use but lets the name change', async () => {
    renderPage()
    fireEvent.click(within(rowOf('Цалингийн зардал')).getByRole('button', { name: 'Засах' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Энэ данс ашиглагдаж байна')).toBeInTheDocument()
    expect(within(dialog).getByLabelText(/Дансны код/)).toHaveAttribute('aria-disabled', 'true')
    fireEvent.change(within(dialog).getByLabelText(/Дансны нэр/), { target: { value: 'Үндсэн цалингийн зардал' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Хадгалах' }))
    await waitFor(() => expect(mocks.update).toHaveBeenCalled())
    expect(mocks.update.mock.calls[0][0]).toMatchObject({ id: 6, code: '5100', name: 'Үндсэн цалингийн зардал', classification: 'expense', purpose: 'salary_expense', parent_id: 5 })
  })

  it('offers to create budget accounts from unlinked income/expense accounts', async () => {
    mocks.permissions.current = { view: true, create: true, edit: true, administer: true }
    render(<MemoryRouter><ChartOfAccountsPage /></MemoryRouter>)
    expect(await screen.findByText(/2 орлого\/зардлын данс төсөвт данстай холбогдоогүй/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Төсөвт данс үүсгэх' })).toBeTruthy()
  })

  it('deletes an unused account and archives a used one', async () => {
    renderPage()
    fireEvent.click(within(rowOf('Үйл ажиллагааны зардал')).getByRole('button', { name: 'Устгах' }))
    await waitFor(() => expect(mocks.remove).toHaveBeenCalledWith(7))
    expect(within(rowOf('Цалингийн зардал')).getByRole('button', { name: 'Идэвхгүй болгох' })).toBeInTheDocument()
  })

  it('explains missing access instead of an empty page', () => {
    mocks.permissions.current = { view: false, create: false, edit: false, administer: false }
    renderPage()
    expect(screen.getByText('Дансны төлөвлөгөөнд хандах эрх танд олгогдоогүй байна')).toBeInTheDocument()
  })
})

describe('accountSelectorOptions', () => {
  it('offers only matching active posting accounts, suggesting the purpose match first', () => {
    const sections = accountSelectorOptions(accounts, { classifications: ['expense'], preferredPurposes: ['salary_expense'] })
    expect(sections.map((section) => section.title)).toEqual(['Санал болгох', 'Зардал'])
    expect(sections[0].options.map((option) => option.label)).toEqual(['5100 · Цалингийн зардал'])
    expect(sections[1].options.map((option) => option.label)).toEqual(['5000 · Үйл ажиллагааны зардал'])
  })

  it('keeps a previously saved account visible even when it no longer fits', () => {
    const sections = accountSelectorOptions(accounts, { classifications: ['expense'], keepId: 9 })
    expect(sections.flatMap((section) => section.options.map((option) => option.value))).toContain('9')
  })
})
