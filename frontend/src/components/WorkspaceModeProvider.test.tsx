import { act, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../store/auth'
import { useWorkspaceModeStore, workspaceModeHeader } from '../store/workspaceMode'
import { useWorkspaceMode, WorkspaceModeProvider } from './WorkspaceModeProvider'

const mocks = vi.hoisted(() => ({ preference: { data: { mode: 'member' as const }, isLoading: false, isError: false }, update: vi.fn(async () => ({ mode: 'manager' })) }))

vi.mock('../api/enterprise', () => ({
  useWorkspaceModePreferences: () => mocks.preference,
  useUpdateWorkspaceModePreferences: () => ({ mutateAsync: mocks.update, isPending: false }),
}))

function Probe() {
  const mode = useWorkspaceMode()
  return <div>{mode.isEligible ? 'toggle-on' : 'toggle-off'}:{mode.mode}<button onClick={() => void mode.setMode('manager')}>manager</button></div>
}

function renderProvider(client: QueryClient) {
  return render(<QueryClientProvider client={client}><WorkspaceModeProvider><Probe /></WorkspaceModeProvider></QueryClientProvider>)
}

describe('WorkspaceModeProvider', () => {
  afterEach(() => {
    useAuthStore.setState({ token: null, actor: null })
    useWorkspaceModeStore.getState().reset()
  })

  it('keeps the toggle for a manager whose effective roles are narrowed in member mode', () => {
    useAuthStore.setState({ token: 't', actor: { id: 1, email: 'm@test', employee_id: 2, locale: 'mn', roles: ['member'], account_roles: ['manager'] } })
    renderProvider(new QueryClient())
    expect(screen.getByText(/toggle-on:member/)).toBeInTheDocument()
    expect(workspaceModeHeader()).toBe('member')
  })

  it('refetches every scoped query when the mode changes', async () => {
    useAuthStore.setState({ token: 't', actor: { id: 1, email: 'm@test', employee_id: 2, locale: 'mn', roles: ['member'], account_roles: ['manager'] } })
    // The browser remembered the personal view, matching the saved preference.
    useWorkspaceModeStore.getState().setMode('member')
    const client = new QueryClient()
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    renderProvider(client)
    expect(invalidate).not.toHaveBeenCalled()
    await act(async () => { screen.getByRole('button', { name: 'manager' }).click() })
    expect(mocks.update).toHaveBeenCalledWith({ mode: 'manager' })
    expect(workspaceModeHeader()).toBe('manager')
    expect(invalidate).toHaveBeenCalledTimes(1)
  })

  it('treats workers without a management grant as members', () => {
    useAuthStore.setState({ token: 't', actor: { id: 3, email: 'w@test', employee_id: 4, locale: 'mn', roles: ['member'], account_roles: ['member'] } })
    renderProvider(new QueryClient())
    expect(screen.getByText(/toggle-off:member/)).toBeInTheDocument()
  })
})
