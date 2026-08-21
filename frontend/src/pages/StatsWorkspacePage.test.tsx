import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { StatsWorkspacePage } from './StatsWorkspacePage'

const mocks = vi.hoisted(() => ({ roles: [] as string[], employeeId: 42 }))

vi.mock('../api/enterprise', () => ({
  useDailyAnalytics: () => ({ data: { days: [] }, isLoading: false, isFetching: false }),
  useEnterpriseSummary: () => ({ data: { completion_rate: 0 }, isLoading: false, isFetching: false }),
  useWorkerDirectory: () => ({ data: [{ id: 42, name: 'HR ажилтан' }] }),
}))

vi.mock('../store/auth', () => ({
  EMPTY_ROLES: [],
  useAuthStore: (selector: (state: unknown) => unknown) => selector({ actor: { employee_id: mocks.employeeId, roles: mocks.roles } }),
}))

vi.mock('../components/WorktimeExportModal', () => ({ WorktimeExportModal: () => <div role="dialog">Worktime export modal</div> }))
vi.mock('../components/WorkHourHierarchyChart', () => ({ WorkHourHierarchyChart: () => <div /> }))
vi.mock('../components/KpiDrilldownCard', () => ({ KpiDrilldownCard: () => <div /> }))
vi.mock('../components/HeatmapCalendar', () => ({ HeatmapCalendar: () => <div /> }))
vi.mock('../components/TimePeriodFilter', () => ({ TimePeriodFilter: () => <div /> }))

describe('Stats worktime export access', () => {
  beforeEach(() => { mocks.roles = [] })

  it.each(['hr', 'manager', 'admin', 'team_lead'])('places export beside the org selector for %s', (role) => {
    mocks.roles = [role]
    render(<StatsWorkspacePage />)
    expect(screen.getByRole('button', { name: /Ажилтан сонгох/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Export Worktime/i })).toBeInTheDocument()
  })

  it('hides the control and org selector for ordinary workers', () => {
    mocks.roles = ['member']
    render(<StatsWorkspacePage />)
    expect(screen.queryByRole('button', { name: /Ажилтан сонгох/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Export Worktime/i })).not.toBeInTheDocument()
  })

  it('defaults non-admin reviewers to their own stats while keeping organization total available', () => {
    mocks.roles = ['hr']
    render(<StatsWorkspacePage />)
    const selector = screen.getByRole('button', { name: /Ажилтан сонгох/i })

    expect(selector).toHaveTextContent('HR ажилтан')
    fireEvent.click(selector)
    expect(screen.getByRole('option', { name: 'Байгууллагын нийлбэр' })).toBeInTheDocument()
  })

  it('defaults administrators to organization total', () => {
    mocks.roles = ['admin']
    render(<StatsWorkspacePage />)
    expect(screen.getByRole('button', { name: /Ажилтан сонгох/i })).toHaveTextContent('Байгууллагын нийлбэр')
  })
})
