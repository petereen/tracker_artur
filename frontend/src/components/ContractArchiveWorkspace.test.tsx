import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ContractArchiveWorkspace } from './ContractArchiveWorkspace'

const state = vi.hoisted(() => ({
  actor: { data: { id: 1, roles: ['admin'] } },
  archive: { data: { current_folder: null, breadcrumbs: [], folders: [], folder_options: [], items: [], total: 0, page: 1, page_size: 50, pending_review_count: 0, can_manage: true }, isLoading: false, isError: false, refetch: vi.fn() },
}))

vi.mock('../api/enterprise', () => ({
  useActor: () => state.actor,
  useContractArchive: () => state.archive,
  useContractArchiveReviewQueue: () => ({ data: { items: [] }, isLoading: false }),
  useContractArchiveAccessCandidates: () => ({ data: [] }),
  useContractArchiveFolderDetail: () => ({ data: undefined, isLoading: false }),
  useContractArchiveEntryDetail: () => ({ data: undefined, isLoading: false }),
  useCreateContractArchiveFolder: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUploadContractArchiveEntry: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
  useUpdateContractArchiveFolder: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateContractArchiveEntry: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateContractArchiveAccess: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteContractArchiveFolder: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteContractArchiveEntry: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useReviewContractArchiveEntry: () => ({ mutateAsync: vi.fn(), isPending: false }),
  getContractArchiveEntryBlob: vi.fn().mockResolvedValue(new Blob(['preview'], { type: 'application/pdf' })),
  downloadContractArchiveEntry: vi.fn(),
}))

describe('ContractArchiveWorkspace', () => {
  beforeEach(() => {
    state.actor.data = { id: 1, roles: ['admin'] }
    state.archive.data = { current_folder: null, breadcrumbs: [], folders: [], folder_options: [], items: [], total: 0, page: 1, page_size: 50, pending_review_count: 0, can_manage: true }
  })

  it('renders archive navigation and the manager empty state', () => {
    render(<MemoryRouter initialEntries={['/contracts/archive']}><ContractArchiveWorkspace /></MemoryRouter>)
    expect(screen.getByRole('link', { name: 'Гэрээний төсөл' })).toHaveAttribute('href', '/contracts')
    expect(screen.getByRole('link', { name: 'Архив' })).toHaveAttribute('href', '/contracts/archive')
    expect(screen.getByText('Архивлагдсан гэрээ байхгүй байна')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Шинэ хавтас үүсгэх/ })).toBeInTheDocument()
  })

  it('keeps create/upload actions hidden from regular employees and supports slash search focus', () => {
    state.actor.data = { id: 2, roles: ['member'] }
    state.archive.data = { ...state.archive.data, can_manage: false }
    render(<MemoryRouter><ContractArchiveWorkspace /></MemoryRouter>)
    expect(screen.queryByRole('button', { name: /Шинэ хавтас үүсгэх/ })).not.toBeInTheDocument()
    fireEvent.keyDown(window, { key: '/' })
    expect(screen.getByPlaceholderText('Хайх… /')).toHaveFocus()
  })
})
