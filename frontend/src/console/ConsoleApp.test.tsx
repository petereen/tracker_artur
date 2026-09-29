import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import ConsoleApp from './ConsoleApp'
import { useConsoleSession } from './consoleApi'

const mocks = vi.hoisted(() => ({ login: vi.fn() }))

const tenant = {
  id: 2, public_id: 'p-2', slug: 'acme', name: 'Acme LLC', status: 'active', status_reason: null, is_primary: false,
  plan_code: 'professional', billing_cycle: 'monthly', seat_limit: 10, seats_used: 4, features: ['crm'],
  license: { required: true, state: 'valid', expires_at: '2027-01-31T00:00:00Z', grace_ends_at: null, days_left: 120 },
  license_required: true, contact_email: null, branding: {}, hosts: ['acme.oyunserp.com'], created_at: '2026-09-29T00:00:00Z',
  suspended_at: null, terminated_at: null,
}

vi.mock('./consoleApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./consoleApi')>()),
  useOperatorLogin: () => ({ mutateAsync: mocks.login, isPending: false }),
  useConsoleTenants: () => ({ isLoading: false, isError: false, data: [tenant] }),
  usePlans: () => ({ isLoading: false, data: [] }),
  useFeatureCatalog: () => ({ data: [{ code: 'crm', label: 'CRM' }] }),
}))

function renderConsole() {
  return render(<QueryClientProvider client={new QueryClient()}>
    <MemoryRouter initialEntries={['/platform']}>
      <Routes><Route path="/platform/*" element={<ConsoleApp />} /></Routes>
    </MemoryRouter>
  </QueryClientProvider>)
}

describe('Operator console', () => {
  beforeAll(() => {
    // AppShell reads the viewport breakpoint; jsdom has no matchMedia.
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: (query: string) => ({ matches: false, media: query, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false }),
    })
  })
  afterEach(() => { useConsoleSession.getState().logout(); mocks.login.mockReset() })

  it('requires an operator login separate from workspace accounts', async () => {
    mocks.login.mockResolvedValue({})
    renderConsole()
    expect(screen.getByText('OYUNS ERP · Операторын консол')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText(/И-мэйл/), { target: { value: 'ops@oyuns.mn' } })
    fireEvent.change(screen.getByLabelText(/Нууц үг/), { target: { value: 'operator-password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Нэвтрэх' }))
    await vi.waitFor(() => expect(mocks.login).toHaveBeenCalledWith({ email: 'ops@oyuns.mn', password: 'operator-password' }))
  })

  it('lists tenants with status, seats and license for a signed-in operator', () => {
    useConsoleSession.getState().setSession('operator-token', { id: 1, email: 'ops@oyuns.mn', display_name: null, role: 'support', status: 'active', last_login_at: null }, 600)
    renderConsole()
    expect(screen.getByRole('heading', { name: 'Байгууллагууд' })).toBeInTheDocument()
    expect(screen.getByText('Acme LLC')).toBeInTheDocument()
    expect(screen.getByText('4 / 10')).toBeInTheDocument()
    // Support operators are read-only: no create button and no operator admin.
    expect(screen.queryByRole('button', { name: /Шинэ байгууллага/ })).toBeNull()
    expect(screen.queryByText('Операторууд')).toBeNull()
  })
})
