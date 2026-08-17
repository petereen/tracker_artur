import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import '../i18n'
import { EnterpriseShell } from './EnterpriseShell'

vi.mock('../api/enterprise', () => ({
  useActor: () => ({ data: { name: 'Manager', email: 'manager@example.com', roles: ['manager'], locale: 'mn', avatar_url: null } }),
  useBrandingSettings: () => ({ data: {} }),
  useERPMetadata: () => ({ data: { modules: {}, module_labels: {}, document_modules: {}, actions: [], currency: 'MNT', custom_fields: [], roles: [], module_visibility_is_not_authorization: true }, isLoading: false }),
  useEnterpriseLogout: () => ({ mutate: vi.fn() }),
  useWorkerDirectory: () => ({ data: [] }),
  useWorkerPerformance: () => ({ data: {} }),
  useWorkerProfile: () => ({ data: null, isLoading: false }),
  useGlobalSearch: () => ({ data: undefined, isFetching: false }),
}))
vi.mock('./NotificationCenter', () => ({ NotificationCenter: () => null }))
vi.mock('./OyunsAssistant', () => ({ OyunsAssistant: () => null }))
vi.mock('./Loading', () => ({ WorkspaceSkeleton: () => null }))

describe('enterprise sidebar', () => {
  it('places company files immediately above the profile and logout controls', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { container } = render(<QueryClientProvider client={client}><MemoryRouter><Routes><Route element={<EnterpriseShell />}><Route index element={<div>Today</div>} /></Route></Routes></MemoryRouter></QueryClientProvider>)
    const link = screen.getByRole('link', { name: 'Компаний файлууд' })
    const profile = container.querySelector('.sidebar-profile')
    expect(profile).not.toBeNull()
    expect(link.compareDocumentPosition(profile as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(link.parentElement).toHaveClass('sidebar-footer')
  })
})
