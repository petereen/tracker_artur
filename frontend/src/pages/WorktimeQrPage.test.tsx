import { forwardRef } from 'react'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { WorktimeQrPage } from './WorktimeQrPage'

const mocks = vi.hoisted(() => ({ display: {} as Record<string, unknown> }))

vi.mock('../api/enterprise', () => ({
  usePairWorktimeQrKiosk: () => ({ mutateAsync: vi.fn(), isPending: false, isError: false }),
  useWorktimeQrDisplayToken: () => mocks.display,
}))

vi.mock('qrcode.react', () => ({
  QRCodeCanvas: forwardRef<HTMLDivElement, { value: string }>(({ value }, ref) => <div ref={ref} data-testid="qr-code">{value}</div>),
}))

describe('Worktime QR display pairing state', () => {
  beforeEach(() => {
    mocks.display = { isError: false, isFetching: false }
  })

  it('shows pairing immediately after the server revokes a cookie, even with cached QR data', () => {
    mocks.display = {
      data: {
        token: 'previous-qr-token',
        issued_at: new Date().toISOString(),
        expires_at: new Date(Date.now() + 20_000).toISOString(),
        server_time: new Date().toISOString(),
        location_id: 'main_office',
        display_name: 'Main office',
      },
      error: { response: { status: 401, data: { detail: { code: 'kiosk_revoked' } } } },
      isError: true,
      isFetching: true,
    }

    render(<WorktimeQrPage />)

    expect(screen.getByRole('heading', { name: 'Дэлгэц холбох' })).toBeInTheDocument()
    expect(screen.getByLabelText('Pairing код')).toBeInTheDocument()
    expect(screen.queryByTestId('qr-code')).not.toBeInTheDocument()
  })

  it('keeps the display paired during a network error instead of prompting to pair again', () => {
    mocks.display = {
      data: {
        token: 'still-valid-qr-token',
        issued_at: new Date().toISOString(),
        expires_at: new Date(Date.now() + 20_000).toISOString(),
        server_time: new Date().toISOString(),
        location_id: 'main_office',
        display_name: 'Main office',
      },
      error: { message: 'Network unavailable' },
      isError: true,
      isFetching: false,
    }

    render(<WorktimeQrPage />)

    expect(screen.getByText('Offline')).toBeInTheDocument()
    expect(screen.getByTestId('qr-code')).toHaveTextContent('still-valid-qr-token')
    expect(screen.queryByRole('heading', { name: 'Дэлгэц холбох' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Pairing код')).not.toBeInTheDocument()
  })
})
