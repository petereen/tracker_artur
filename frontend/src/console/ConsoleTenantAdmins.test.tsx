import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AdminsCard } from './ConsoleTenants'

const mocks = vi.hoisted(() => ({ recover: vi.fn(), issue: vi.fn() }))

vi.mock('./consoleApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./consoleApi')>()),
  useRecoverTenantAdmin: () => ({ mutateAsync: mocks.recover, isPending: false }),
  useIssueTenantAdmin: () => ({ mutateAsync: mocks.issue, isPending: false }),
}))

const admins = [
  { id: 7, email: 'bat', status: 'active', last_login_at: null, two_factor_enabled: true, locked: true },
  { id: 8, email: 'bold', status: 'active', last_login_at: null, two_factor_enabled: false, locked: false },
]

describe('AdminsCard', () => {
  beforeEach(() => {
    mocks.recover.mockReset().mockResolvedValue({})
    mocks.issue.mockReset().mockResolvedValue({})
    HTMLDialogElement.prototype.showModal ??= function showModal(this: HTMLDialogElement) { this.setAttribute('open', '') }
    HTMLDialogElement.prototype.close ??= function close(this: HTMLDialogElement) { this.removeAttribute('open') }
  })

  it('removes the 2FA of a locked-out admin after a confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<AdminsCard tenantId={3} admins={admins} twoFactorRequired canEdit />)
    expect(screen.getByText('Түгжигдсэн')).toBeInTheDocument()
    // Only an enrolled admin has something to remove.
    expect(screen.queryByRole('button', { name: 'bold-ийн 2FA арилгах' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'bat-ийн 2FA арилгах' }))
    await waitFor(() => expect(mocks.recover).toHaveBeenCalledWith({ tenantId: 3, accountId: 7, reset_two_factor: true }))
  })

  it('re-issues a password and issues a new admin account', async () => {
    render(<AdminsCard tenantId={3} admins={admins} twoFactorRequired={false} canEdit />)
    fireEvent.click(screen.getByRole('button', { name: 'bat-д нууц үг дахин олгох' }))
    fireEvent.change(screen.getByLabelText(/Түр нууц үг/), { target: { value: 'temporary-pass-1' } })
    fireEvent.click(screen.getByLabelText('2 шатлалт нэвтрэлтийг мөн арилгах'))
    fireEvent.click(screen.getByRole('button', { name: 'Олгох' }))
    await waitFor(() => expect(mocks.recover).toHaveBeenCalledWith({ tenantId: 3, accountId: 7, password: 'temporary-pass-1', reset_two_factor: true }))

    fireEvent.click(screen.getByRole('button', { name: 'Шинэ админ олгох' }))
    fireEvent.change(await screen.findByLabelText(/Нэвтрэх нэр/), { target: { value: ' new-admin ' } })
    fireEvent.change(screen.getByLabelText(/Түр нууц үг/), { target: { value: 'temporary-pass-2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Олгох' }))
    await waitFor(() => expect(mocks.issue).toHaveBeenCalledWith({ tenantId: 3, email: 'new-admin', password: 'temporary-pass-2' }))
  })

  it('is read-only for support operators', () => {
    render(<AdminsCard tenantId={3} admins={admins} twoFactorRequired={false} canEdit={false} />)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})
