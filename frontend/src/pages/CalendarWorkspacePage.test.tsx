import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CalendarWorkspacePage, GoogleCalendarSyncControl } from './CalendarWorkspacePage'

const state = vi.hoisted(() => ({
  status: { data: { status: 'disconnected', configured: true, provider: 'google', sync_mode: 'outbound' as const } as any, isLoading: false, refetch: vi.fn() },
  connect: { isPending: false, mutateAsync: vi.fn() },
  sync: { isPending: false, mutate: vi.fn() },
  disconnect: { isPending: false, mutate: vi.fn() },
  calendars: { data: { items: [], selected_id: '' } as any, isLoading: false },
  select: { isPending: false, mutate: vi.fn() },
  events: { tasks: [] as any[], projects: [] as any[], plans: [] as any[], entries: [] as any[], holidays: [] as any[], time_blocks: [] as any[] },
}))

vi.mock('../api/enterprise', () => ({
  useGoogleCalendarStatus: () => state.status,
  useGoogleCalendarConnect: () => state.connect,
  useGoogleCalendarSync: () => state.sync,
  useGoogleCalendarDisconnect: () => state.disconnect,
  useGoogleCalendarList: () => state.calendars,
  useGoogleCalendarSelect: () => state.select,
  useCalendarEvents: () => ({ data: state.events, isLoading: false, isFetching: false, isError: false }),
  useCreateCalendarEntry: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useCreateEnterpriseTask: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useUpdateCalendarEntry: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useDeleteCalendarEntry: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useUpdateEnterpriseTask: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useDeleteEnterpriseTask: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useWorkerDirectory: () => ({ data: [] }),
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
    state.events = { tasks: [], projects: [], plans: [], entries: [], holidays: [], time_blocks: [] }
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

  it('renders a compact mobile month and selected-day agenda for multi-day items', () => {
    const now = new Date()
    const day = (value: number) => `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(value).padStart(2, '0')}`
    state.events.tasks = [{ id: 44, title: 'Олон өдрийн ажил', start_at: day(17), deadline_at: day(19), primary_owner_name: 'Test' }]
    state.events.entries = [{ id: 45, kind: 'event', title: 'Уулзалт', starts_at: day(18), ends_at: day(18) }]
    const { container } = render(<CalendarWorkspacePage />)
    expect(container.querySelector('.mobile-calendar')).toBeInTheDocument()
    expect(container.querySelectorAll('.mobile-calendar-grid button')).toHaveLength(42)
    const eventDay = container.querySelector<HTMLButtonElement>('.mobile-calendar-grid button[aria-label*="18"]')
    expect(eventDay).not.toBeNull()
    fireEvent.click(eventDay as HTMLButtonElement)
    expect(container.querySelectorAll('.mobile-calendar-agenda-item').length).toBeGreaterThanOrEqual(2)
    expect(container.querySelector('.mobile-calendar-agenda-item')?.textContent).toContain('Олон өдрийн ажил')
    const selected = container.querySelector<HTMLButtonElement>('.mobile-calendar-grid button[aria-pressed="true"]')
    expect(selected).not.toBeNull()
    const targetDay = container.querySelector<HTMLButtonElement>('.mobile-calendar-grid button[aria-label*="17"]')
    expect(targetDay).not.toBeNull()
    fireEvent.click(targetDay as HTMLButtonElement)
    expect(targetDay).toHaveAttribute('aria-pressed', 'true')
    expect(container.querySelector('.mobile-calendar-agenda')?.textContent).toContain('Олон өдрийн ажил')
  })
})
