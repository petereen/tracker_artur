import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
  workers: [] as any[],
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
  useWorkerDirectory: () => ({ data: [{ id: 7, name: 'Батаа', job_title: 'Дизайнер' }] }),
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
    state.workers.length = 0
    window.localStorage.clear()
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

  it('renders every calendar type in collision-free spanning lanes and slices week wraps', () => {
    const now = new Date()
    const day = (value: number) => {
      const date = new Date(now.getFullYear(), now.getMonth(), value)
      return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
    }
    const saturday = Array.from({ length: 14 }, (_, index) => index + 15).find((value) => new Date(now.getFullYear(), now.getMonth(), value).getDay() === 6) as number
    state.events.tasks = [{ id: 50, kind: 'task', title: 'Замын ажил', start_at: day(17), deadline_at: day(19) }]
    state.events.entries = [
      { id: 51, kind: 'event', title: 'Олон өдрийн үйл явдал', starts_at: day(17), ends_at: day(19) },
      { id: 52, kind: 'reminder', title: 'Давхцсан сануулга', starts_at: day(18), ends_at: day(18) },
      { id: 53, kind: 'event', title: 'Долоо хоног дамнасан үйл явдал', starts_at: day(saturday), ends_at: day(saturday + 2) },
    ]
    state.events.holidays = [{ id: 54, kind: 'holiday', title: 'Нийтийн амралт', holiday_date: day(18) }]

    const { container } = render(<CalendarWorkspacePage />)
    const calendar = container.querySelector('.planning-calendar')
    const bars = [...(calendar?.querySelectorAll('.calendar-range') ?? [])]
    expect(bars.map((bar) => bar.querySelector('strong')?.textContent)).toEqual(expect.arrayContaining(['Замын ажил', 'Олон өдрийн үйл явдал', 'Давхцсан сануулга', 'Нийтийн амралт']))

    const reminder = calendar?.querySelector<HTMLElement>('.calendar-item.reminder')
    expect(Number(reminder?.style.getPropertyValue('--range-lane'))).toBeGreaterThan(0)

    const wrapped = bars.filter((bar) => bar.querySelector('strong')?.textContent === 'Долоо хоног дамнасан үйл явдал')
    expect(wrapped).toHaveLength(2)
    expect(wrapped[0]).toHaveClass('range-start')
    expect(wrapped[1]).toHaveClass('range-end')
    expect(wrapped[0].getAttribute('style')).toContain('grid-column: 6 / 8')
    expect(wrapped[1].getAttribute('style')).toContain('grid-column: 1 / 2')
  })

  it('opens a worker availability popover from the creation sheet', () => {
    const now = new Date()
    const day = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-18`
    state.workers.push({ id: 7, name: 'Батаа', job_title: 'Дизайнер' })
    state.events.entries = [{ id: 70, kind: 'event', title: 'Батаагийн уулзалт', starts_at: `${day}T10:00:00Z`, ends_at: `${day}T11:00:00Z` }]
    const { container } = render(<CalendarWorkspacePage />)

    fireEvent.click(screen.getByRole('button', { name: 'Үүсгэх' }))
    fireEvent.click(screen.getByRole('button', { name: 'Батаа-ийн хуваарь' }))

    const dialog = screen.getByRole('dialog', { name: 'Батаа-ийн хуваарь' })
    expect(dialog).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Дараагийн сар' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Шинээр үүсгэх' })).toBeInTheDocument()
    expect(within(dialog).getByText('Батаагийн уулзалт')).toBeInTheDocument()
  })

  it('filters calendar types and persists the selected view', () => {
    const now = new Date()
    const day = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-18`
    state.events.tasks = [{ id: 80, kind: 'task', title: 'Шүүлтүүрийн даалгавар', start_at: day, deadline_at: day }]
    state.events.entries = [{ id: 81, kind: 'event', title: 'Шүүлтүүрийн уулзалт', starts_at: day, ends_at: day }]
    const { container } = render(<CalendarWorkspacePage />)

    expect(container.querySelector('.calendar-item.task')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Даалгавар' }))

    expect(container.querySelector('.calendar-item.task')).not.toBeInTheDocument()
    expect(window.localStorage.getItem('oyuns-calendar-type-filters')).toContain('"task":false')
    expect(screen.getByRole('button', { name: 'Даалгавар' })).toHaveAttribute('aria-pressed', 'false')
  })
})
