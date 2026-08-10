import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import '../i18n'
import { CompanyFilesPage } from './CompanyFilesPage'

let canManage = true
const mutation = { mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }

vi.mock('../api/enterprise', () => ({
  downloadCompanyFile: vi.fn(),
  useCompanyFiles: () => ({
    data: {
      current_folder: null,
      breadcrumbs: [],
      items: [{ id: 1, parent_id: null, kind: 'folder', name: 'Policies', content_type: null, size: null, checksum: null, uploaded_by_account_id: 1, created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z', deleted_at: null }],
      folders: [{ id: 1, parent_id: null, name: 'Policies' }],
      can_manage: canManage,
      is_search: false,
      is_trash: false,
    },
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
  useCreateCompanyFolder: () => mutation,
  useUploadCompanyFile: () => mutation,
  useUpdateCompanyItem: () => mutation,
  useTrashCompanyItem: () => mutation,
  useRestoreCompanyItem: () => mutation,
  useDeleteCompanyItemPermanently: () => mutation,
}))

describe('company file library', () => {
  beforeEach(() => { canManage = true; mutation.mutate.mockReset(); mutation.mutateAsync.mockReset() })

  it('shows browsing and management actions to managers', () => {
    render(<CompanyFilesPage />)
    expect(screen.getByRole('heading', { name: 'Компаний файлууд' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Шинэ хавтас/ })).toBeEnabled()
    expect(screen.getByRole('button', { name: /Файл оруулах/ })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'PoliciesХавтас' })).toBeInTheDocument()
  })

  it('hides all mutation controls from ordinary members', () => {
    canManage = false
    render(<CompanyFilesPage />)
    expect(screen.queryByRole('button', { name: /Шинэ хавтас/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Файл оруулах/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Policies нэр солих/ })).not.toBeInTheDocument()
  })

  it('opens an accessible folder creation dialog', () => {
    render(<CompanyFilesPage />)
    fireEvent.click(screen.getByRole('button', { name: /Шинэ хавтас/ }))
    expect(screen.getByRole('dialog', { name: 'Шинэ хавтас' })).toBeInTheDocument()
    expect(screen.getByLabelText('Нэр')).toHaveFocus()
  })
})
