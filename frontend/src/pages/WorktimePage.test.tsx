import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { WorktimePage } from './WorktimePage'

const mocks = vi.hoisted(() => ({ methods: { qr_enabled: true, location_enabled: true }, clockAction: vi.fn(), decode: vi.fn() }))

vi.mock('@zxing/browser', () => ({
  BrowserQRCodeReader: class { decodeFromConstraints = mocks.decode },
}))

vi.mock('../api/enterprise', () => ({
  useClock: () => ({ isLoading: false, data: { active: null, today_entries: [], timezone: 'Asia/Ulaanbaatar', server_time: new Date().toISOString() } }),
  useWorktimeMethods: () => ({ isLoading: false, isSuccess: true, data: mocks.methods }),
  useWorktimeQrClock: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useClockAction: () => ({ mutate: mocks.clockAction, isPending: false }),
}))

vi.mock('../components/AutoWorktimeCard', () => ({ AutoWorktimeCard: () => <div data-testid="auto-worktime-card" /> }))

const renderPage = () => render(<MemoryRouter><WorktimePage /></MemoryRouter>)

describe('WorktimePage check-in methods', () => {
  beforeEach(() => { mocks.clockAction.mockClear(); mocks.decode.mockReset().mockResolvedValue({ stop: vi.fn() }) })

  it('shows the QR scanner first, then today entries, then the automatic tracking card', () => {
    mocks.methods = { qr_enabled: true, location_enabled: true }
    renderPage()
    const scanner = screen.getByRole('heading', { name: 'Оффисын QR уншуулах' })
    const entries = screen.getByRole('heading', { name: 'Өнөөдрийн бүртгэл' })
    const auto = screen.getByTestId('auto-worktime-card')
    expect(scanner.compareDocumentPosition(entries) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(entries.compareDocumentPosition(auto) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('offers the automatic location tracking switch on the worktime page', () => {
    renderPage()
    expect(screen.getByTestId('auto-worktime-card')).toBeInTheDocument()
  })

  it('opens the camera by itself, with no button to press', async () => {
    mocks.methods = { qr_enabled: true, location_enabled: true }
    renderPage()
    await waitFor(() => expect(mocks.decode).toHaveBeenCalledTimes(1))
    expect(screen.queryByRole('button', { name: /Камер нээх/ })).not.toBeInTheDocument()
  })

  it('does not open the camera when QR check-in is switched off', () => {
    mocks.methods = { qr_enabled: false, location_enabled: true }
    renderPage()
    expect(mocks.decode).not.toHaveBeenCalled()
  })

  it('hides the QR scanner when QR check-in is switched off', () => {
    mocks.methods = { qr_enabled: false, location_enabled: true }
    renderPage()
    expect(screen.queryByRole('heading', { name: 'Оффисын QR уншуулах' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'QR уншуулах' })).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Өнөөдрийн бүртгэл' })).toBeInTheDocument()
  })

  it('offers only the scanner when location check-in is off', () => {
    mocks.methods = { qr_enabled: true, location_enabled: false }
    renderPage()
    expect(screen.getByRole('heading', { name: 'Оффисын QR уншуулах' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Байршлаар эхлэх/ })).not.toBeInTheDocument()
  })
})
