import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ContractsWorkspacePage } from './ContractsWorkspacePage'

const state = vi.hoisted(() => ({
  list: { data: { items: [{ public_id: 'abc', id: 1, title: 'Үйлчилгээний гэрээ', document_type: 'contract', status: 'DRAFT', author_account_id: 1, project_id: null, task_id: null, submission_round: 0, version: 1, current_revision_id: 1, approved_revision_id: null, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' }], counts: { all: 1, drafts: 1, pending_my_approval: 0, submitted_by_me: 0, approved: 0, signed: 0, returned: 0 } }, isLoading: false },
}))

vi.mock('../api/enterprise', () => ({
  useContractList: () => state.list,
  useContractDetail: () => ({ data: undefined }),
  useActor: () => ({ data: { id: 1, employee_id: 1, roles: [] } }),
  useContractReviewerCandidates: () => ({ data: [] }),
  useCreateContract: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useUpdateContract: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useUploadContractFile: () => ({ isPending: false, mutate: vi.fn() }),
  useSubmitContract: () => ({ mutate: vi.fn() }), useResubmitContract: () => ({ mutate: vi.fn() }), useRecallContract: () => ({ mutate: vi.fn() }),
  useApproveContract: () => ({ mutate: vi.fn() }), useRequestContractChanges: () => ({ mutate: vi.fn() }), useRejectContract: () => ({ mutate: vi.fn() }),
  useDuplicateContract: () => ({ mutate: vi.fn() }), useConfirmContractFinal: () => ({ mutate: vi.fn() }), useMarkContractPrinted: () => ({ mutate: vi.fn() }),
  useAddContractComment: () => ({ mutate: vi.fn() }), useResolveContractComment: () => ({ mutate: vi.fn() }),
}))

describe('ContractsWorkspacePage', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('renders the lifecycle tabs and status-filtered list', () => {
    render(<MemoryRouter><ContractsWorkspacePage /></MemoryRouter>)
    expect(screen.getByRole('tablist')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Гэрээ' })).not.toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Ноорог/ })).toHaveTextContent('1')
    expect(screen.getByRole('button', { name: /Үйлчилгээний гэрээ/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: /Баталгаажсан/ }))
    expect(screen.getByRole('tab', { name: /Баталгаажсан/ })).toHaveAttribute('aria-selected', 'true')
  })

  it('offers a clear creation affordance', () => {
    render(<MemoryRouter><ContractsWorkspacePage /></MemoryRouter>)
    expect(screen.getByRole('button', { name: /Шинэ баримт бичиг/ })).toBeInTheDocument()
  })
})
