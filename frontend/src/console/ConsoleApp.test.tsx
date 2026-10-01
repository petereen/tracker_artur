import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import ConsoleApp from './ConsoleApp'
import { useConsoleSession } from './consoleApi'

const mocks = vi.hoisted(() => ({ login: vi.fn(), code: vi.fn() }))

const operator = { id: 1, email: 'ops@oyuns.mn', display_name: null, role: 'superadmin', status: 'active', last_login_at: null, two_factor_enabled: true }
const enrolment = { secret: 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP', otpauth_uri: 'otpauth://totp/OYUNS%20ERP%20Console%3Aops%40oyuns.mn?secret=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP&issuer=OYUNS+ERP+Console', issuer: 'OYUNS ERP Console', account: 'ops@oyuns.mn', digits: 6, period: 30 }

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
  useTwoFactorEnrolment: () => ({ data: enrolment, isError: false, error: null }),
  useTwoFactorCode: (step: string) => ({ mutateAsync: (input: unknown) => mocks.code(step, input), isPending: false }),
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
  afterEach(() => { useConsoleSession.getState().logout(); mocks.login.mockReset(); mocks.code.mockReset() })

  it('requires an operator login separate from workspace accounts', async () => {
    mocks.login.mockResolvedValue({})
    renderConsole()
    expect(screen.getByText('OYUNS ERP · Операторын консол')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText(/И-мэйл/), { target: { value: 'ops@oyuns.mn' } })
    fireEvent.change(screen.getByLabelText(/Нууц үг/), { target: { value: 'operator-password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Нэвтрэх' }))
    await vi.waitFor(() => expect(mocks.login).toHaveBeenCalledWith({ email: 'ops@oyuns.mn', password: 'operator-password' }))
  })

  const signIn = async () => {
    renderConsole()
    fireEvent.change(screen.getByLabelText(/И-мэйл/), { target: { value: 'ops@oyuns.mn' } })
    fireEvent.change(screen.getByLabelText(/Нууц үг/), { target: { value: 'operator-password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Нэвтрэх' }))
  }

  it('walks a first login through authenticator setup and recovery codes', async () => {
    mocks.login.mockResolvedValue({ two_factor: 'setup', mfa_token: 'pending-token', expires_in: 600 })
    mocks.code.mockResolvedValue({ access_token: 'operator-token', expires_in: 600, operator, recovery_codes: ['abcde-fghjk', 'mnpqr-stuvw'] })
    await signIn()
    expect(await screen.findByRole('heading', { name: '2 шатлалт нэвтрэлт тохируулах' })).toBeInTheDocument()
    expect(screen.getByText(/Google Authenticator, Microsoft Authenticator/)).toBeInTheDocument()
    expect(screen.getByTitle('2 шатлалт нэвтрэлтийн QR код')).toBeInTheDocument()
    expect(screen.getByText('JBSW Y3DP EHPK 3PXP JBSW Y3DP EHPK 3PXP')).toBeInTheDocument()
    const enable = screen.getByRole('button', { name: 'Баталгаажуулж идэвхжүүлэх' })
    expect(enable).toBeDisabled()
    fireEvent.change(screen.getByLabelText(/Баталгаажуулах код/), { target: { value: '123 456' } })
    fireEvent.click(enable)
    await vi.waitFor(() => expect(mocks.code).toHaveBeenCalledWith('enable', { mfa_token: 'pending-token', code: '123456' }))
    // The session opens only after the recovery codes are acknowledged.
    expect(await screen.findByText('abcde-fghjk')).toBeInTheDocument()
    expect(useConsoleSession.getState().token).toBeNull()
    const enter = screen.getByRole('button', { name: 'Консол руу орох' })
    expect(enter).toBeDisabled()
    fireEvent.click(screen.getByLabelText('Нөөц кодуудаа аюулгүй газар хадгаллаа'))
    fireEvent.click(enter)
    expect(useConsoleSession.getState().token).toBe('operator-token')
    expect(await screen.findByRole('heading', { name: 'Байгууллагууд' })).toBeInTheDocument()
  })

  it('asks an enrolled operator for a code, or a recovery code', async () => {
    mocks.login.mockResolvedValue({ two_factor: 'verify', mfa_token: 'pending-token', expires_in: 600 })
    mocks.code.mockResolvedValue({ access_token: 'operator-token', expires_in: 600, operator, recovery_codes_left: 9 })
    await signIn()
    expect(await screen.findByRole('heading', { name: '2 шатлалт баталгаажуулалт' })).toBeInTheDocument()
    expect(useConsoleSession.getState().token).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Нөөц код ашиглах' }))
    fireEvent.change(screen.getByLabelText(/Нөөц код/), { target: { value: 'abcde-fghjk' } })
    fireEvent.click(screen.getByRole('button', { name: 'Баталгаажуулах' }))
    await vi.waitFor(() => expect(mocks.code).toHaveBeenCalledWith('verify', { mfa_token: 'pending-token', code: 'abcde-fghjk' }))
    await vi.waitFor(() => expect(useConsoleSession.getState().token).toBe('operator-token'))
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
