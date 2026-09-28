import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { WorktimePage } from './WorktimePage'

const mocks = vi.hoisted(() => ({ methods: { qr_enabled: true, location_enabled: true }, clockAction: vi.fn() }))

vi.mock('../api/enterprise', () => ({
  useClock: () => ({ isLoading: false, data: { active: null, today_entries: [], timezone: 'Asia/Ulaanbaatar', server_time: new Date().toISOString() } }),
  useWorktimeMethods: () => ({ isLoading: false, isSuccess: true, data: mocks.methods }),
  useWorktimeQrClock: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useClockAction: () => ({ mutate: mocks.clockAction, isPending: false }),
}))

const renderPage = () => render(<MemoryRouter><WorktimePage /></MemoryRouter>)

describe('WorktimePage check-in methods', () => {
  beforeEach(() => { mocks.clockAction.mockClear() })

  it('shows the QR scanner and the location start when both methods are on', () => {
    mocks.methods = { qr_enabled: true, location_enabled: true }
    renderPage()
    expect(screen.getByRole('heading', { name: 'Оффисын QR уншуулах' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Байршлаар эхлэх/ })).toBeInTheDocument()
  })

  it('hides the QR scanner when QR check-in is switched off', () => {
    mocks.methods = { qr_enabled: false, location_enabled: true }
    renderPage()
    expect(screen.queryByRole('heading', { name: 'Оффисын QR уншуулах' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'QR уншуулах' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Байршлаар эхлэх/ })).toBeInTheDocument()
  })

  it('offers only the scanner when location check-in is off', () => {
    mocks.methods = { qr_enabled: true, location_enabled: false }
    renderPage()
    expect(screen.getByRole('heading', { name: 'Оффисын QR уншуулах' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Байршлаар эхлэх/ })).not.toBeInTheDocument()
  })

  it('falls back to a plain start without location when both methods are off', () => {
    mocks.methods = { qr_enabled: false, location_enabled: false }
    renderPage()
    screen.getByRole('button', { name: /Ажил эхлүүлэх/ }).click()
    expect(mocks.clockAction).toHaveBeenCalledWith({ action: 'start', mode: 'in_person' })
  })
})
