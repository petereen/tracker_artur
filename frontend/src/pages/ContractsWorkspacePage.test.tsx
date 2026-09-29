import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ContractsWorkspacePage } from './ContractsWorkspacePage'

const state = vi.hoisted(() => ({
  list: { data: { items: [{ public_id: 'abc', id: 1, title: 'Үйлчилгээний гэрээ', document_type: 'contract', status: 'DRAFT', author_account_id: 1, project_id: null, task_id: null, submission_round: 0, version: 1, current_revision_id: 1, approved_revision_id: null, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' }], counts: { all: 1, drafts: 1, pending_my_approval: 0, submitted_by_me: 0, approved: 0, signed: 0, returned: 0 } }, isLoading: false },
  create: vi.fn().mockResolvedValue({ public_id: 'new-contract' }),
  upload: vi.fn().mockResolvedValue({ id: 2 }),
  listCalls: [] as Array<[string, Record<string, unknown> | undefined]>,
  options: {
    next_code: 'CT-0007', can_manage_groups: true,
    groups: [{ id: 1, code: 'SALES', name: 'Борлуулалтын гэрээ', parent_id: null, is_active: true, contract_count: 0 }, { id: 2, code: 'SVC', name: 'Үйлчилгээний гэрээ', parent_id: 1, is_active: true, contract_count: 0 }],
    units: [{ id: 5, code: 'HR', name: 'Цаг', symbol: 'ц' }],
    payment_terms: [{ id: 9, code: 'NET30', name: '30 хоногт', days: 30 }],
  },
  parties: [{ id: 42, code: '10002', name: 'Салбар ХХК', tax_id: null, is_customer: true, is_supplier: false, currency: 'MNT', payment_term_id: 9, head_party: { id: 41, code: '10001', name: 'Толгой ХХК' } }],
}))

vi.mock('../api/enterprise', () => ({
  useContractList: (view: string, filters?: Record<string, unknown>) => { state.listCalls.push([view, filters]); return state.list },
  useContractRegistryOptions: () => ({ data: state.options }),
  useContractPartyOptions: () => ({ data: state.parties }),
  useUpdateContractRegistry: () => ({ isPending: false, mutate: vi.fn() }),
  useCreateContractGroup: () => ({ isPending: false, mutate: vi.fn() }),
  useUpdateContractGroup: () => ({ isPending: false, mutate: vi.fn() }),
  useDeleteContractGroup: () => ({ isPending: false, mutate: vi.fn() }),
  useContractDetail: () => ({ data: undefined }),
  useActor: () => ({ data: { id: 1, employee_id: 1, roles: [] } }),
  useContractReviewerCandidates: () => ({ data: [] }),
  useCreateContract: () => ({ isPending: false, mutateAsync: state.create }),
  useUpdateContract: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useUploadContractFile: () => ({ isPending: false, mutate: vi.fn(), mutateAsync: state.upload }),
  useProjects: () => ({ data: [] }),
  useEnterpriseTasks: () => ({ data: [] }),
  useSubmitContract: () => ({ mutate: vi.fn() }), useResubmitContract: () => ({ mutate: vi.fn() }), useRecallContract: () => ({ mutate: vi.fn() }),
  useApproveContract: () => ({ mutate: vi.fn() }), useRequestContractChanges: () => ({ mutate: vi.fn() }), useRejectContract: () => ({ mutate: vi.fn() }),
  useDuplicateContract: () => ({ mutate: vi.fn() }), useConfirmContractFinal: () => ({ mutate: vi.fn() }), useMarkContractPrinted: () => ({ mutate: vi.fn() }),
  useAddContractComment: () => ({ mutate: vi.fn() }), useResolveContractComment: () => ({ mutate: vi.fn() }),
}))

describe('ContractsWorkspacePage', () => {
  beforeEach(() => { vi.clearAllMocks(); state.listCalls.length = 0 })

  it('renders the lifecycle tabs and status-filtered list', () => {
    render(<MemoryRouter><ContractsWorkspacePage /></MemoryRouter>)
    expect(screen.getByRole('tablist')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Гэрээ' })).not.toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Ноорог/ })).toHaveTextContent('1')
    expect(screen.getByRole('button', { name: /Үйлчилгээний гэрээ/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: /Баталгаажсан/ }))
    expect(screen.getByRole('tab', { name: /Баталгаажсан/ })).toHaveAttribute('aria-selected', 'true')
  })

  it('offers a clear icon-only creation affordance', () => {
    render(<MemoryRouter><ContractsWorkspacePage /></MemoryRouter>)
    const button = screen.getByRole('button', { name: /Шинэ баримт бичиг/ })
    expect(button).toBeInTheDocument()
    expect(button).toHaveAttribute('title', 'Шинэ баримт бичиг')
    expect(button).toHaveClass('contract-icon-button')
  })

  it('queues and uploads attachments while creating a new draft', async () => {
    render(<MemoryRouter initialEntries={['/contracts?create=1']}><ContractsWorkspacePage /></MemoryRouter>)

    expect(screen.getAllByRole('button', { name: 'Болих' })).toHaveLength(2)
    expect(screen.getAllByRole('button', { name: 'Болих' })[0]).toHaveClass('contract-icon-button-danger')
    expect(screen.getByRole('button', { name: 'Ноорог хадгалах' })).toHaveClass('contract-icon-button-save')
    fireEvent.change(screen.getByLabelText('Файл хавсаргах'), { target: { files: [new File(['contract'], 'terms.pdf', { type: 'application/pdf' })] } })
    expect(screen.getByText('terms.pdf')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Гарчиг / сэдэв'), { target: { value: 'Шинэ гэрээ' } })
    fireEvent.change(screen.getByLabelText(/Дуусах/), { target: { value: '2026-12-31' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ноорог хадгалах' }))

    await waitFor(() => expect(state.upload).toHaveBeenCalledWith(expect.objectContaining({ publicId: 'new-contract', purpose: 'supporting' })))
  })

  it('registers d028 metadata: code, CRM counterparty, group, amounts, links and meta', async () => {
    render(<MemoryRouter initialEntries={['/contracts?create=1']}><ContractsWorkspacePage /></MemoryRouter>)

    expect(screen.getByPlaceholderText('Автомат: CT-0007')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Гарчиг / сэдэв'), { target: { value: 'Үйлчилгээний гэрээ' } })
    fireEvent.change(screen.getByLabelText(/Дуусах/), { target: { value: '2026-12-31' } })
    fireEvent.change(screen.getByLabelText('Гэрээний дугаар'), { target: { value: 'ГД-15/2026' } })
    fireEvent.change(screen.getByLabelText('Гэрээний бүлэг'), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText('Гэрээ байгуулсан огноо'), { target: { value: '2026-09-01' } })
    fireEvent.change(screen.getByLabelText('Харилцагч'), { target: { value: '42' } })
    expect(screen.getByText(/Толгой харилцагч: 10001 · Толгой ХХК/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Тоо хэмжээ'), { target: { value: '120' } })
    fireEvent.change(screen.getByLabelText('Нэгж үнэ'), { target: { value: '50000' } })
    expect(screen.getByLabelText('Гэрээний дүн')).toHaveValue('6000000')
    fireEvent.change(screen.getByLabelText('Алданги %'), { target: { value: '0.5' } })
    fireEvent.click(screen.getByRole('button', { name: /Линк нэмэх/ }))
    fireEvent.change(screen.getByLabelText('Холбоос'), { target: { value: 'https://drive.example/scan.pdf' } })
    fireEvent.click(screen.getByRole('button', { name: /Мета нэмэх/ }))
    fireEvent.change(screen.getByLabelText('Мета талбарын нэр'), { target: { value: 'Хариуцагч хуульч' } })
    fireEvent.change(screen.getByLabelText('Мета утга'), { target: { value: 'Б. Сараа' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ноорог хадгалах' }))

    await waitFor(() => expect(state.create).toHaveBeenCalled())
    expect(state.create).toHaveBeenCalledWith(expect.objectContaining({
      code: null, contract_number: 'ГД-15/2026', group_id: 2, party_id: 42, signed_on: '2026-09-01',
      quantity: '120', unit_price: '50000', amount: '6000000', currency: 'MNT', penalty_pct: '0.5', payment_term_id: 9,
      links: [{ kind: 'online', label: '', url: 'https://drive.example/scan.pdf' }],
      custom_fields: [{ label: 'Хариуцагч хуульч', value: 'Б. Сараа' }],
    }))
  })

  it('filters the list by group, active flag and a CRM party deep link', async () => {
    render(<MemoryRouter initialEntries={['/contracts?party=42']}><ContractsWorkspacePage /></MemoryRouter>)
    expect(state.listCalls[state.listCalls.length - 1]).toEqual(['registry', { party_id: 42 }])
    fireEvent.change(screen.getByLabelText('Бүлгээр шүүх'), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText('Идэвхээр шүүх'), { target: { value: 'false' } })
    expect(state.listCalls[state.listCalls.length - 1]).toEqual(['registry', { party_id: 42, group_id: 1, active: false }])
    fireEvent.click(screen.getByRole('button', { name: 'Харилцагчийн шүүлтүүр арилгах' }))
    await waitFor(() => expect(state.listCalls[state.listCalls.length - 1]).toEqual(['all', { group_id: 1, active: false }]))
  })
})
