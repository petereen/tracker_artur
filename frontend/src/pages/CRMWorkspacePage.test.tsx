import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CRMWorkspacePage } from './CRMWorkspacePage'

const mocks = vi.hoisted(() => ({ saveActivity: vi.fn(), saveParty: vi.fn(), capabilities: { current: null as unknown } }))
const allow = { view: true, create: true, edit: true, archive: true }
const fullCaps = { module_enabled: true, employee_id: 7, parties: allow, activities: allow, settings: allow }
const status = { id: 1, register: 'crm_activity', code: 'NEW', name: 'Шинэ', sort: 10, color: '#2D62EC', category: 'open', is_active: true }
const lookups = {
  employees: [{ id: 7, name: 'Сараа', job_title: 'Борлуулагч' }],
  statuses: [status, { ...status, id: 2, code: 'DONE', name: 'Дууссан', category: 'done', color: '#16A34A' }],
  activity_types: [{ id: 3, code: 'CALL', name: 'Утас', sort: 10, is_active: true }],
  party_groups: [{ id: 4, code: 'CUSTOMERS', name: 'Харилцагчид', parent_id: null, is_default: true, is_foreign: false, default_settlement_account_id: null, default_price_list_id: null, is_active: true }],
  payment_terms: [], contracts: [], projects: [], price_lists: [], settlement_accounts: [],
}
const activity = {
  id: 11, public_id: 'a', number: 'CRM-000011', party_id: 5, party_code: '10001', party_name: 'Даянсофт', contact_id: 9, contact_name: 'Болд', contact_phone: '99112233', contact_email: null,
  activity_at: '2026-09-20T02:00:00Z', subject: '100 ширхэг бараа', body: null, type_id: 3, type_name: 'Утас', is_important: true, due_at: '2026-09-21T02:00:00Z', duration_minutes: null,
  responsible_employee_id: 7, responsible_name: 'Сараа', status_id: 1, status: { id: 1, name: 'Шинэ', color: '#2D62EC', category: 'open' }, completed_at: null, completion_note: null,
  reference: null, contract_id: null, contract_title: null, project_id: null, project_name: null, task_id: null, task_title: null, is_closed: false, closed_at: null,
  reviewed_by_employee_id: null, reviewed_by_name: null, reviewed_at: null, expected_revenue: '5000000', currency: 'MNT', overdue_days: 4, is_open: true, is_overdue: true,
  is_active: true, custom: {}, created_by_employee_id: 7, created_by_name: 'Сараа', version: 3, created_at: null, updated_at: null,
}
const party = {
  id: 5, public_id: 'p', code: '10001', name: 'Даянсофт', name_en: null, business_name: null, party_type: 'customer', registry_no: '5922364', tax_id: '5922364',
  is_customer: true, is_supplier: false, is_individual: false, is_foreign: false, vat_payer: true, city_tax_payer: false, tax_status_checked_at: null, email: null, phone: '7510',
  website: null, legal_address: null, location: null, informal_address: null, tags: [], group_id: 4, group_name: 'Харилцагчид', responsible_employee_id: 7, responsible_name: 'Сараа',
  parent_party_id: null, parent_name: null, settle_via_parent: false, customer_since: null, inactive_since: null, payment_term_id: null, payment_term_name: null, price_list_id: null,
  price_list_name: null, settlement_account_id: null, settlement_account_name: null, credit_limit: null, currency: 'MNT', sales_discount_pct: null, sales_note: null, sales_lead_days: null,
  purchase_discount_pct: null, purchase_note: null, purchase_lead_days: null, delivery_terms: null, links: [], custom: {}, is_active: true, status: 'active', version: 1,
  created_at: null, updated_at: null, duplicate_tax_id: true, duplicate_name: false,
}
const idle = { mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }

vi.mock('../api/enterprise', () => ({ useActor: () => ({ data: { roles: ['member'], employee_id: 7 } }) }))
vi.mock('../api/crm', () => ({
  useCRMCapabilities: () => ({ data: mocks.capabilities.current, isLoading: false, isError: false }),
  useCRMLookups: () => ({ data: lookups, isLoading: false }),
  useCRMSummary: () => ({ data: { open: 1, overdue: 1, due_today: 0, due_this_week: 0, important: 1, expected_revenue: [{ currency: 'MNT', amount: '5000000' }], by_status: [], by_responsible: [] } }),
  useCRMActivities: () => ({ data: { items: [activity], total: 1, page: 1, page_size: 50 }, isLoading: false }),
  useCRMActivity: () => ({ data: undefined }),
  useCRMParties: () => ({ data: { items: [party], total: 1, page: 1, page_size: 50 }, isLoading: false }),
  useCRMParty: () => ({ data: { ...party, contacts: [{ id: 9, party_id: 5, name: 'Болд', nickname: null, position: 'Захирал', phone: '99112233', email: null, address: null, note: null, is_default: true, is_active: true }], bank_accounts: [], children: [], stats: { activities_total: 1, activities_open: 1, activities_overdue: 1, expected_revenue_open: null, last_activity_at: null, documents_total: 0 }, group_stats: null } }),
  useCRMFiles: () => ({ data: [] }),
  useSaveCRMActivity: () => ({ ...idle, mutateAsync: mocks.saveActivity }),
  useSaveCRMParty: () => ({ ...idle, mutateAsync: mocks.saveParty }),
  useCRMActivityAction: () => idle, useCreateCRMActivityTask: () => idle, useDeleteCRMActivity: () => idle, useUploadCRMFile: () => idle, useDeleteCRMFile: () => idle,
  useBulkCRMActivities: () => idle, useImportCRMParties: () => idle, useSaveCRMSetting: () => idle, useDeleteCRMSetting: () => idle,
  downloadCRMFile: vi.fn(), downloadCRMPartiesCsv: vi.fn(), downloadCRMImportTemplate: vi.fn(), lookupCRMTaxpayer: vi.fn(),
}))

const renderAt = (path: string) => render(<MemoryRouter initialEntries={[path]}><Routes>
  <Route path="/erp/crm" element={<CRMWorkspacePage />} />
  <Route path="/erp/crm/customers" element={<CRMWorkspacePage />} />
</Routes></MemoryRouter>)

describe('CRMWorkspacePage', () => {
  beforeEach(() => {
    mocks.capabilities.current = fullCaps
    mocks.saveActivity.mockReset().mockResolvedValue({ ...activity, version: 4 })
    mocks.saveParty.mockReset().mockResolvedValue({ ...party, id: 12, code: '10002' })
  })

  it('shows overdue activities and saves edits with optimistic version', async () => {
    renderAt('/erp/crm')
    const row = screen.getByText('100 ширхэг бараа').closest('tr')!
    expect(row.className).toContain('is-overdue')
    expect(within(row).getByText('4')).toBeTruthy()
    fireEvent.click(row)
    expect(screen.getByDisplayValue('99112233')).toBeTruthy()
    fireEvent.change(screen.getByDisplayValue('100 ширхэг бараа'), { target: { value: '120 ширхэг бараа' } })
    fireEvent.click(screen.getByRole('button', { name: 'Хадгалах' }))
    await waitFor(() => expect(mocks.saveActivity).toHaveBeenCalled())
    expect(mocks.saveActivity.mock.calls[0][0]).toMatchObject({ id: 11, version: 3, subject: '120 ширхэг бараа', contact_id: 9, party_id: 5 })
  })

  it('asks for confirmation before saving a branch that shares a TIN', async () => {
    const conflict = { response: { data: { detail: { code: 'crm_party_duplicate_tin', message: 'dup', matches: [{ party_id: 5, code: '10001', name: 'Даянсофт', reason: 'tax_id' }] } } } }
    mocks.saveParty.mockRejectedValueOnce(conflict)
    renderAt('/erp/crm/customers')
    expect(screen.getByText('5922364 / 5922364').className).toContain('crm-duplicate')
    fireEvent.click(screen.getByRole('button', { name: /Шинэ харилцагч/ }))
    const dialog = screen.getByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('Нэр'), { target: { value: 'Даянсофт салбар' } })
    fireEvent.change(within(dialog).getByLabelText('ТТД'), { target: { value: '5922364' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Хадгалах' }))
    await waitFor(() => expect(screen.getByText('10001 — Даянсофт')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: 'Салбар гэж баталгаажуулж хадгалах' }))
    await waitFor(() => expect(mocks.saveParty).toHaveBeenCalledTimes(2))
    expect(mocks.saveParty.mock.calls[0][0]).toMatchObject({ name: 'Даянсофт салбар', tax_id: '5922364', confirm_duplicate_tin: false })
    expect(mocks.saveParty.mock.calls[1][0]).toMatchObject({ confirm_duplicate_tin: true })
  })

  it('explains missing access instead of rendering an empty workspace', () => {
    mocks.capabilities.current = { ...fullCaps, parties: { ...allow, view: false }, activities: { ...allow, view: false } }
    renderAt('/erp/crm')
    expect(screen.getByText(/CRM-д хандах эрх/)).toBeTruthy()
  })
})
