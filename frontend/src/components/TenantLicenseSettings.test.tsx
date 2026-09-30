import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TenantLicenseSettings } from './TenantLicenseSettings'

const mocks = vi.hoisted(() => ({
  verify: vi.fn(),
  activate: vi.fn(),
  overview: {
    isLoading: false,
    isError: false,
    data: {
      tenant: { slug: 'acme', name: 'Acme LLC', status: 'pending_activation', public_id: 'p-1' },
      license: { required: true, state: 'missing', expires_at: null, grace_ends_at: null, days_left: null },
      active: null,
      history: [],
      seats: { used: 3, limit: 3, available: 0, unlimited: false },
      features: [
        { code: 'crm', label: 'CRM', enabled: true, primary_only: false },
        { code: 'payroll', label: 'Цалин', enabled: false, primary_only: false },
      ],
      plan_code: 'professional',
      billing_cycle: 'monthly',
    },
  },
}))

vi.mock('../api/tenancy', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/tenancy')>()),
  useTenantLicense: () => mocks.overview,
  useVerifyLicense: () => ({ mutateAsync: mocks.verify, isPending: false }),
  useActivateLicense: () => ({ mutateAsync: mocks.activate, isPending: false }),
}))

describe('TenantLicenseSettings', () => {
  afterEach(() => { mocks.verify.mockReset(); mocks.activate.mockReset() })

  it('shows license state, a full seat meter and licensed modules', () => {
    render(<TenantLicenseSettings />)
    expect(screen.getAllByText('Идэвхжүүлээгүй').length).toBeGreaterThan(0)
    expect(screen.getByText('Хүчинтэй лиценз алга')).toBeInTheDocument()
    expect(screen.getByText(/Бүх эрх ашиглагдсан/)).toBeInTheDocument()
    expect(screen.getByText('Багцад орсон')).toBeInTheDocument()
    expect(screen.getByText('Ороогүй')).toBeInTheDocument()
  })

  it('verifies a key before activating it', async () => {
    mocks.verify.mockResolvedValue({
      valid: true,
      claims: { seats: 5, valid_from: '2026-09-29T00:00:00Z', expires_at: '2027-09-29T00:00:00Z', features: ['crm'] },
      seats: { used: 3, limit: 3, available: 0, unlimited: false },
      fits_current_usage: true,
      feature_labels: { crm: 'CRM' },
    })
    mocks.activate.mockResolvedValue({})
    render(<TenantLicenseSettings />)
    fireEvent.change(screen.getByLabelText('Идэвхжүүлэх түлхүүр'), { target: { value: '  header.claims.signature  ' } })
    fireEvent.click(screen.getByRole('button', { name: /Шалгах/ }))
    expect(await screen.findByText('Түлхүүр хүчинтэй')).toBeInTheDocument()
    expect(mocks.verify).toHaveBeenCalledWith('header.claims.signature')
    fireEvent.click(screen.getByRole('button', { name: /Идэвхжүүлэх/ }))
    await vi.waitFor(() => expect(mocks.activate).toHaveBeenCalledWith('header.claims.signature'))
  })

  it('blocks activation when the key has fewer seats than active users', async () => {
    mocks.verify.mockResolvedValue({
      valid: true,
      claims: { seats: 2, valid_from: '2026-09-29T00:00:00Z', expires_at: '2027-09-29T00:00:00Z', features: [] },
      seats: { used: 3, limit: 3, available: 0, unlimited: false },
      fits_current_usage: false,
      feature_labels: {},
    })
    render(<TenantLicenseSettings />)
    fireEvent.change(screen.getByLabelText('Идэвхжүүлэх түлхүүр'), { target: { value: 'a.b.c' } })
    fireEvent.click(screen.getByRole('button', { name: /Шалгах/ }))
    expect(await screen.findByText('Хэрэглэгчийн тоо лицензээс их байна')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Идэвхжүүлэх/ })).toBeDisabled()
  })
})
