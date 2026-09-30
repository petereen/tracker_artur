import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TenantDomainSettings } from './TenantDomainSettings'

const mocks = vi.hoisted(() => ({
  add: vi.fn(),
  refresh: vi.fn(),
  remove: vi.fn(),
  domains: {
    isLoading: false,
    isError: false,
    data: {
      available: true,
      cname_target: 'customers.oyunserp.com',
      limit: 3,
      platform_url: 'https://acme.oyunserp.com',
      domains: [{
        id: 1, hostname: 'erp.acme.mn', provider: 'cloudflare', status: 'pending', ssl_status: 'pending_validation', verified_at: null,
        dns_records: [
          { type: 'CNAME', name: 'erp.acme.mn', value: 'customers.oyunserp.com', purpose: 'routing' },
          { type: 'TXT', name: '_cf-custom-hostname.erp.acme.mn', value: 'uuid-1', purpose: 'ownership' },
        ],
        last_error: null, last_checked_at: null, created_at: '2026-09-30T00:00:00Z', url: 'https://erp.acme.mn',
      }],
    } as Record<string, unknown>,
  },
}))

vi.mock('../api/tenancy', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/tenancy')>()),
  useTenantDomains: () => mocks.domains,
  useAddTenantDomain: () => ({ mutateAsync: mocks.add, isPending: false }),
  useRefreshTenantDomain: () => ({ mutateAsync: mocks.refresh, isPending: false }),
  useRemoveTenantDomain: () => ({ mutateAsync: mocks.remove, isPending: false }),
}))

describe('TenantDomainSettings', () => {
  beforeEach(() => { mocks.add.mockReset().mockResolvedValue({}); mocks.refresh.mockReset().mockResolvedValue({ status: 'pending' }); mocks.remove.mockReset() })

  it('lists the DNS records a pending domain still needs', () => {
    render(<TenantDomainSettings />)
    expect(screen.getByText('erp.acme.mn', { selector: 'span, p, strong' })).toBeInTheDocument()
    expect(screen.getAllByText(/DNS \/ SSL хүлээж байна/).length).toBeGreaterThan(0)
    expect(screen.getAllByText('customers.oyunserp.com').length).toBeGreaterThan(0)
    expect(screen.getByText('_cf-custom-hostname.erp.acme.mn')).toBeInTheDocument()
    expect(screen.getByText('Эзэмшил баталгаажуулах')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Шалгах/ }))
    expect(mocks.refresh).toHaveBeenCalledWith(1)
  })

  it('normalizes the hostname before adding it', async () => {
    render(<TenantDomainSettings />)
    fireEvent.change(screen.getByLabelText('Домэйн'), { target: { value: ' https://ERP2.Acme.mn/login ' } })
    fireEvent.click(screen.getByRole('button', { name: /Нэмэх/ }))
    await waitFor(() => expect(mocks.add).toHaveBeenCalledWith('erp2.acme.mn'))
  })

  it('stays read-only when the platform has no Cloudflare setup', () => {
    mocks.domains.data = { ...mocks.domains.data, available: false, domains: [] }
    render(<TenantDomainSettings />)
    expect(screen.getByText('Өөрийн домэйн холбох үйлчилгээ идэвхгүй')).toBeInTheDocument()
    expect((screen.getByRole('button', { name: /Нэмэх/ }) as HTMLButtonElement).disabled || screen.getByRole('button', { name: /Нэмэх/ }).getAttribute('aria-disabled') === 'true').toBe(true)
  })
})
