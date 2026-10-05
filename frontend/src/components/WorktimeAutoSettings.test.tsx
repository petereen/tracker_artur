import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../store/auth'
import { WorktimeAutoSettings } from './WorktimeAutoSettings'

const mocks = vi.hoisted(() => ({
  update: vi.fn(),
  settings: {
    isError: false,
    data: {
      auto_geofence_mode: 'off', exit_grace_minutes: 10, min_accuracy_meters: 100, geo_retention_days: 90,
      employer_disclaimer_ack: null as null | Record<string, unknown>, policy_version: '2026-10-02',
    },
  },
  sites: { isError: false, isLoading: false, data: [] as Record<string, unknown>[] },
}))

vi.mock('../api/worktimeAuto', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/worktimeAuto')>()),
  useAutoWorktimeSettings: () => mocks.settings,
  useUpdateAutoWorktimeSettings: () => ({ mutateAsync: mocks.update, isPending: false }),
  useWorktimeSites: () => mocks.sites,
  useSaveWorktimeSite: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteWorktimeSite: () => ({ mutate: vi.fn(), isPending: false }),
}))
vi.mock('./WorktimeLocationLog', () => ({ WorktimeLocationLog: () => null }))
vi.mock('./WorktimeMapPicker', () => ({ WorktimeMapPicker: () => null }))

function signIn(roles: string[]) {
  useAuthStore.setState({ actor: { roles } } as never)
}

describe('WorktimeAutoSettings', () => {
  beforeEach(() => {
    // jsdom has no <dialog> modal API.
    HTMLDialogElement.prototype.showModal ??= function showModal(this: HTMLDialogElement) { this.setAttribute('open', '') }
    HTMLDialogElement.prototype.close ??= function close(this: HTMLDialogElement) { this.removeAttribute('open') }
    mocks.update.mockReset().mockResolvedValue({})
    mocks.settings.data = { auto_geofence_mode: 'off', exit_grace_minutes: 10, min_accuracy_meters: 100, geo_retention_days: 90, employer_disclaimer_ack: null, policy_version: '2026-10-02' }
    mocks.sites.data = []
    signIn(['admin'])
  })

  it('asks for the employer acknowledgement before switching anything on', async () => {
    render(<WorktimeAutoSettings />)
    expect(screen.getByText(/Дор хаяж нэг оффисын бүс нэмэх хүртэл/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('switch', { name: /Байршлаар автомат цаг бүртгэх/ }))
    expect(mocks.update).not.toHaveBeenCalled()
    expect(await screen.findByText('Ажил олгогчийн хариуцлага')).toBeInTheDocument()
    const confirm = screen.getByRole('button', { name: 'Баталгаажуулж асаах' })
    expect(confirm).toBeDisabled()
    fireEvent.click(screen.getByLabelText('Байгууллагын нэрийн өмнөөс дээрхийг хүлээн зөвшөөрч байна'))
    fireEvent.click(confirm)
    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith({ auto_geofence_mode: 'on', acknowledge_employer_disclaimer: true }))
  })

  it('changes the mode directly once the current notice is acknowledged', async () => {
    mocks.settings.data = { ...mocks.settings.data, auto_geofence_mode: 'shadow', employer_disclaimer_ack: { account_id: 1, email: 'admin@oyuns.mn', acknowledged_at: '2026-10-02T03:00:00Z', policy_version: '2026-10-02' } }
    render(<WorktimeAutoSettings />)
    expect(screen.getByText(/admin@oyuns.mn/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('radio', { name: 'Асаалттай' }))
    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith({ auto_geofence_mode: 'on', acknowledge_employer_disclaimer: undefined }))
    expect(screen.queryByText('Ажил олгогчийн хариуцлага')).not.toBeInTheDocument()
  })

  it('turns tracking off with the switch without asking again', async () => {
    mocks.settings.data = { ...mocks.settings.data, auto_geofence_mode: 'on', employer_disclaimer_ack: { account_id: 1, email: 'admin@oyuns.mn', acknowledged_at: '2026-10-02T03:00:00Z', policy_version: '2026-10-02' } }
    render(<WorktimeAutoSettings />)
    fireEvent.click(screen.getByRole('switch', { name: /Байршлаар автомат цаг бүртгэх/ }))
    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith({ auto_geofence_mode: 'off', acknowledge_employer_disclaimer: undefined }))
  })

  it('warns when the notice changed after it was acknowledged', () => {
    mocks.settings.data = { ...mocks.settings.data, auto_geofence_mode: 'on', employer_disclaimer_ack: { account_id: 1, email: 'admin@oyuns.mn', acknowledged_at: '2026-01-01T00:00:00Z', policy_version: '2025-01-01' } }
    render(<WorktimeAutoSettings />)
    expect(screen.getByText('Дахин баталгаажуулах шаардлагатай')).toBeInTheDocument()
  })

  it('is read-only for managers', () => {
    signIn(['manager'])
    render(<WorktimeAutoSettings />)
    expect(screen.getByText('Зөвхөн админ өөрчилнө')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Бүс нэмэх/ })).not.toBeInTheDocument()
    expect(screen.getByRole('switch', { name: /Байршлаар автомат цаг бүртгэх/ })).toBeDisabled()
    expect(screen.queryByText('Ажил олгогчийн хариуцлага')).not.toBeInTheDocument()
  })
})
