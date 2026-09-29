import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { HRAttendanceItem } from '../../api/enterprise'
import { AttendanceGrid } from './AttendanceGrid'
import { periodDates } from './attendanceModel'

const mocks = vi.hoisted(() => ({ update: vi.fn(), bulk: vi.fn(), reset: vi.fn(), save: vi.fn(), range: [] as string[] }))

const people = [{ id: 1, name: 'Бат' }, { id: 2, name: 'Сараа' }]
// Thursday 2026-10-01 is "today"; the week is Sep 28 – Oct 4.
const overrides: Record<string, Partial<HRAttendanceItem>> = {
  '1|2026-09-28': { id: 11, status: 'present', confirmed: true, source: 'manual', version: 3 },
  '1|2026-09-29': { status: 'remote', source: 'worktime', worked_minutes: 420 },
  '1|2026-09-30': { on_leave: true, leave_type: 'sick' },
  '1|2026-10-04': { status: 'present', worked_minutes: 120 },
  '2|2026-09-28': { status: 'absent' },
  '2|2026-09-27': { status: 'absent' },
}
const makeItems = (start: string, end: string): HRAttendanceItem[] => periodDates(start, end).flatMap((date) => people.map((person) => {
  const weekend = [0, 6].includes(new Date(`${date}T12:00:00`).getDay())
  return { id: null, employee_id: person.id, employee_name: person.name, department_id: person.id, department_name: person.id === 1 ? 'Санхүү' : 'Борлуулалт', attendance_date: date, status: weekend ? 'absent' : null, suggested_status: null, on_leave: false, leave_type: null, source: 'derived', worked_minutes: 0, first_started_at: null, last_ended_at: null, confirmed: false, version: null, is_non_working_day: weekend, non_working_day_name: weekend ? 'Амралтын өдөр' : null, ...overrides[`${person.id}|${date}`] }
}))

vi.mock('../../api/enterprise', () => ({
  useHRAttendance: (start: string, end: string) => { mocks.range = [start, end]; return { data: { items: makeItems(start, end) }, isLoading: false, isError: false, isFetching: false } },
  useUpdateHRAttendance: () => ({ mutateAsync: mocks.update, isPending: false }),
  useBulkUpdateHRAttendance: () => ({ mutateAsync: mocks.bulk, isPending: false }),
  useResetHRAttendance: () => ({ mutateAsync: mocks.reset, isPending: false }),
  saveCompanyBlob: mocks.save,
}))

vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() }))

const renderGrid = (canEdit = true) => render(<QueryClientProvider client={new QueryClient()}><AttendanceGrid canEdit={canEdit} /></QueryClientProvider>)
const WEEK = periodDates('2026-09-28', '2026-10-04')
const ROW: Record<string, number> = { Бат: 0, Сараа: 1 }
const cell = (name: string, date: string) => document.querySelector<HTMLElement>(`[data-cell="${ROW[name]}:${WEEK.indexOf(date)}"]`)!
const batchButton = () => screen.getByRole('button', { name: /Сонгосныг ирсэн болгох/ })

describe('AttendanceGrid', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-10-01T10:00:00'))
    Object.values(mocks).forEach((mock) => typeof mock === 'function' && mock.mockReset().mockResolvedValue({}))
    try { window.localStorage.clear() } catch { /* ignore */ }
  })
  afterEach(() => vi.useRealTimers())

  it('renders an employee × weekday grid with statuses, leave and weekends', () => {
    renderGrid()
    expect(mocks.range).toEqual(['2026-09-28', '2026-10-04'])
    expect(screen.getAllByRole('columnheader')).toHaveLength(8)
    expect(screen.getAllByRole('row')).toHaveLength(3)
    expect(cell('Бат', '2026-09-28').getAttribute('aria-label')).toMatch(/Ирсэн$/)
    expect(cell('Бат', '2026-09-30').getAttribute('aria-label')).toMatch(/Өвчтэй$/)
    // Suggested weekend absence without a record is shown as a day off; weekend work as overtime.
    expect(cell('Сараа', '2026-10-03').getAttribute('aria-label')).toMatch(/Амралтын өдөр$/)
    expect(cell('Бат', '2026-10-04').getAttribute('aria-label')).toMatch(/амралтын өдөр ажилласан$/)
  })

  it('keeps batch actions disabled until cells are selected, then sends eligible days only', async () => {
    renderGrid()
    expect(batchButton()).toBeDisabled()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Сараа: мөрийн бүх өдрийг сонгох' }))
    expect(batchButton()).toBeEnabled()
    expect(batchButton()).toHaveTextContent('4')
    fireEvent.click(batchButton())
    await waitFor(() => expect(mocks.bulk).toHaveBeenCalledTimes(1))
    // Mon–Thu only: the weekend and Friday (future) are not part of a batch.
    expect(mocks.bulk.mock.calls[0][0].map((row: { attendance_date: string }) => row.attendance_date)).toEqual(['2026-09-28', '2026-09-29', '2026-09-30', '2026-10-01'])
    expect(mocks.bulk.mock.calls[0][0][0]).toMatchObject({ employee_id: 2, status: 'present' })
    await waitFor(() => expect(batchButton()).toBeDisabled())
  })

  it('edits one cell from its popover and sends the known version', async () => {
    renderGrid()
    fireEvent.click(cell('Бат', '2026-09-28'))
    const editor = screen.getByRole('dialog', { name: /Бат/ })
    expect(within(editor).getByRole('menuitemradio', { name: /Ирсэн/ })).toHaveAttribute('aria-checked', 'true')
    fireEvent.click(within(editor).getByRole('menuitemradio', { name: /Remote/ }))
    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith({ employee_id: 1, attendance_date: '2026-09-28', status: 'remote', version: 3 }))
    expect(screen.queryByRole('dialog', { name: /Бат/ })).not.toBeInTheDocument()
  })

  it('offers weekend work as overtime and resets a confirmed day', async () => {
    vi.setSystemTime(new Date('2026-10-04T20:00:00'))
    renderGrid()
    fireEvent.click(cell('Сараа', '2026-10-03'))
    const weekend = screen.getByRole('dialog', { name: /Сараа/ })
    expect(within(weekend).getAllByRole('menuitemradio').map((node) => node.textContent)).toEqual(['Ирсэн (илүү цаг)', 'Remote (илүү цаг)'])
    fireEvent.keyDown(weekend, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    fireEvent.click(cell('Бат', '2026-09-28'))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Автомат төлөвт буцаах' }))
    await waitFor(() => expect(mocks.reset).toHaveBeenCalledWith({ employee_id: 1, attendance_date: '2026-09-28', version: 3 }))
  })

  it('locks approved leave and future days', () => {
    renderGrid()
    fireEvent.click(cell('Бат', '2026-09-30'))
    expect(screen.queryByRole('menuitemradio')).not.toBeInTheDocument()
    expect(screen.getByText(/Ирцийг чөлөөний хүсэлтээс засна/)).toBeInTheDocument()
    fireEvent.click(cell('Бат', '2026-10-02'))
    expect(screen.getByText('Ирээдүйн өдрийн ирцийг бүртгэх боломжгүй.')).toBeInTheDocument()
  })

  it('moves focus with arrow keys and opens the editor with Enter', () => {
    renderGrid()
    const first = cell('Бат', '2026-09-28')
    first.focus()
    fireEvent.keyDown(first, { key: 'ArrowDown' })
    expect(document.activeElement).toBe(cell('Сараа', '2026-09-28'))
    fireEvent.keyDown(document.activeElement!, { key: 'ArrowRight' })
    expect(document.activeElement).toBe(cell('Сараа', '2026-09-29'))
    fireEvent.keyDown(document.activeElement!, { key: 'Enter' })
    expect(screen.getByRole('dialog', { name: /Сараа/ })).toBeInTheDocument()
  })

  it('switches to a month of columns and filters rows by search', async () => {
    renderGrid()
    fireEvent.click(screen.getByRole('radio', { name: 'Сар' }))
    expect(mocks.range).toEqual(['2026-10-01', '2026-10-31'])
    expect(screen.getAllByRole('columnheader')).toHaveLength(32)
    fireEvent.change(screen.getByRole('textbox', { name: 'Ажилтан хайх' }), { target: { value: 'сар' } })
    await waitFor(() => expect(screen.getAllByRole('row')).toHaveLength(2))
    fireEvent.click(screen.getByRole('button', { name: /CSV/ }))
    expect(mocks.save).toHaveBeenCalledWith(expect.any(Blob), 'ирц-2026-10.csv')
  })

  it('is read-only without manager rights', () => {
    renderGrid(false)
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Сонгосныг/ })).not.toBeInTheDocument()
    fireEvent.click(cell('Бат', '2026-09-28'))
    expect(screen.queryByRole('menuitemradio')).not.toBeInTheDocument()
  })
})
