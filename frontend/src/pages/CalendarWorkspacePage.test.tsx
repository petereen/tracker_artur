import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { GoogleCalendarSyncControl } from './CalendarWorkspacePage'

const state = vi.hoisted(() => ({
  status: { data: { status: 'disconnected', configured: true, provider: 'google', sync_mode: 'outbound' as const } as any, isLoading: false, refetch: vi.fn() },
  connect: { isPending: false, mutateAsync: vi.fn() },
  sync: { isPending: false, mutate: vi.fn() },
  disconnect: { isPending: false, mutate: vi.fn() },
  calendars: { data: { items: [], selected_id: '' } as any, isLoading: false },
  select: { isPending: false, mutate: vi.fn() },
}))

vi.mock('../api/enterprise', () => ({
  useGoogleCalendarStatus: () => state.status,
  useGoogleCalendarConnect: () => state.connect,
  useGoogleCalendarSync: () => state.sync,
  useGoogleCalendarDisconnect: () => state.disconnect,
  useGoogleCalendarList: () => state.calendars,
  useGoogleCalendarSelect: () => state.select,
  useCalendarEvents: () => ({ data: { tasks: [], projects: [], plans: [], entries: [], holidays: [], time_blocks: [] }, isLoading: false, isFetching: false, isError: false }),
  useCreateCalendarEntry: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useCreateEnterpriseTask: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useHolidaySettings: () => ({ data: { country: 'MN', countries: [] } }),
  useSetHolidayCountry: () => ({ isPending: false, mutate: vi.fn() }),
}))

describe('GoogleCalendarSyncControl', () => {
  beforeEach(() => {
    state.status.data = { status: 'disconnected', configured: true, provider: 'google', sync_mode: 'outbound' } as any
    state.status.isLoading = false
    state.connect.mutateAsync.mockReset()
    state.sync.mutate.mockReset()
    state.disconnect.mutate.mockReset()
    vi.restoreAllMocks()
  })

  it('opens OAuth from the disconnected state', async () => {
    state.connect.mutateAsync.mockResolvedValue({ authorization_url: 'https://accounts.google.com/authorize' })
    vi.spyOn(window, 'open').mockReturnValue({ focus: vi.fn() } as unknown as Window)
    render(<GoogleCalendarSyncControl />)
    fireEvent.click(screen.getByRole('button', { name: /Google Calendar холбох/i }))
    await waitFor(() => expect(window.open).toHaveBeenCalled())
  })

  it('shows connected account actions and triggers manual sync', () => {
    state.status.data = { status: 'active', configured: true, provider: 'google', sync_mode: 'outbound', account_email: 'calendar@example.com', calendar_id: 'primary', last_synced_at: new Date().toISOString() } as any
    state.calendars.data = { items: [{ id: 'primary', name: 'Primary', primary: true }], selected_id: 'primary' } as any
    render(<GoogleCalendarSyncControl />)
    expect(screen.getByText(/calendar@example.com/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Sync Google Calendar now' }))
    expect(state.sync.mutate).toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /Manage/i }))
    expect(screen.getByRole('menu')).toBeInTheDocument()
  })
})
