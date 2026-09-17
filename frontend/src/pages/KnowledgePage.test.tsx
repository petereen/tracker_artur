import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { KnowledgePage } from './KnowledgePage'
import { useAuthStore } from '../store/auth'

vi.mock('../api/hooks', () => ({
  useKnowledge: () => ({ data: [{ id: 1, title: 'Leave policy', category: 'HR', content: 'Ask HR before taking leave.', attachment_filename: null, attachment_content_type: null, attachment_size: null, is_active: true, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' }], isLoading: false }),
  useCreateKnowledge: () => ({ mutateAsync: vi.fn() }),
  useCreateKnowledgeWithAttachment: () => ({ mutateAsync: vi.fn() }),
  useDeleteKnowledge: () => ({ mutate: vi.fn() }),
  useDeleteKnowledgeAttachment: () => ({ mutateAsync: vi.fn() }),
  useReplaceKnowledgeAttachment: () => ({ mutateAsync: vi.fn() }),
  useUpdateKnowledge: () => ({ mutate: vi.fn(), mutateAsync: vi.fn() }),
}))

vi.mock('../api/client', () => ({ api: { get: vi.fn() } }))

describe('company knowledge access', () => {
  beforeEach(() => {
    useAuthStore.setState({ actor: { id: 7, email: 'member@example.com', employee_id: 7, locale: 'mn', roles: ['member'] } })
  })

  it('shows knowledge to members without exposing management actions', () => {
    render(<KnowledgePage />)

    expect(screen.getByText('Leave policy')).toBeInTheDocument()
    expect(screen.getByText('Ask HR before taking leave.')).toBeInTheDocument()
    expect(screen.getByText('Та компаний өгөгдлийн санг зөвхөн харах эрхтэй.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '+ Мэдээлэл нэмэх' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Засах' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Устгах' })).not.toBeInTheDocument()
  })
})
