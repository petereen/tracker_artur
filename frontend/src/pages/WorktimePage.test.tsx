import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { WorktimePage } from './WorktimePage'

const mocks = vi.hoisted(() => ({ roles: [] as string[] }))

vi.mock('../api/enterprise', () => ({
  useClock: () => ({ data: { active: null, today_entries: [], timezone: 'Asia/Ulaanbaatar' }, isLoading: false }),
  useWorktimeQrClock: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
}))

vi.mock('../store/auth', () => ({
  EMPTY_ROLES: [],
  useAuthStore: (selector: (state: unknown) => unknown) => selector({ actor: { roles: mocks.roles } }),
}))

describe('Worktime export access', () => {
  beforeEach(() => { mocks.roles = [] })

  it.each(['team_lead', 'hr', 'manager', 'admin'])('shows export for %s', (role) => {
    mocks.roles = [role]
    render(<WorktimePage />)
    expect(screen.getByRole('button', { name: /Export Worktime/i })).toBeInTheDocument()
  })

  it('hides export for ordinary workers', () => {
    mocks.roles = ['member']
    render(<WorktimePage />)
    expect(screen.queryByRole('button', { name: /Export Worktime/i })).not.toBeInTheDocument()
  })
})

