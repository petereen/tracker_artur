import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TwoFactorGate } from './TwoFactorGate'
import { TwoFactorSettings } from './TwoFactorSettings'
import { useAuthStore } from '../store/auth'

const mocks = vi.hoisted(() => ({
  enable: vi.fn(),
  verify: vi.fn(),
  update: vi.fn(),
  reset: vi.fn(),
  logout: vi.fn(),
}))

vi.mock('../api/twoFactor', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/twoFactor')>()),
  useTwoFactorEnrolment: () => ({ isError: false, data: { secret: 'ABCDEFGHIJKLMNOP', otpauth_uri: 'otpauth://totp/Acme:bat?secret=ABCDEFGHIJKLMNOP', issuer: 'Acme', account: 'bat' } }),
  useTwoFactorCode: (step: 'enable' | 'verify') => ({ mutateAsync: mocks[step], isPending: false }),
  useTwoFactorSettings: () => ({ isError: false, data: { required: false, accounts: 4, enrolled: 1 } }),
  useUpdateTwoFactorSettings: () => ({ mutateAsync: mocks.update, isPending: false }),
  useResetAccountTwoFactor: () => ({ mutate: mocks.reset, isPending: false }),
}))

vi.mock('../api/enterprise', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/enterprise')>()),
  useEnterpriseLogout: () => ({ mutate: mocks.logout, isPending: false }),
  useManagedAccounts: () => ({ data: [{ id: 7, email: 'bat', two_factor_enabled: true }, { id: 8, email: 'bold', two_factor_enabled: false }] }),
}))

vi.mock('../api/tenancy', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/tenancy')>()),
  useTenantBranding: () => ({ data: { name: 'Acme' } }),
}))

describe('TwoFactorGate', () => {
  beforeEach(() => {
    Object.values(mocks).forEach((mock) => mock.mockReset())
    HTMLDialogElement.prototype.showModal ??= function showModal(this: HTMLDialogElement) { this.setAttribute('open', '') }
    HTMLDialogElement.prototype.close ??= function close(this: HTMLDialogElement) { this.removeAttribute('open') }
  })

  it('enrols an authenticator app and keeps the recovery codes up until they are saved', async () => {
    mocks.enable.mockResolvedValue({ access_token: 't', expires_in: 900, recovery_codes: ['aaaaa-bbbbb', 'ccccc-ddddd'] })
    const onDone = vi.fn()
    render(<TwoFactorGate enrolled={false} onDone={onDone} />)
    expect(screen.getByText('2 шатлалт нэвтрэлт тохируулах')).toBeInTheDocument()
    expect(screen.getByText('ABCD EFGH IJKL MNOP')).toBeInTheDocument()
    const submit = screen.getByRole('button', { name: 'Баталгаажуулж идэвхжүүлэх' })
    expect(submit).toBeDisabled()
    fireEvent.change(screen.getByLabelText(/Баталгаажуулах код/), { target: { value: '123 456' } })
    fireEvent.click(submit)
    await waitFor(() => expect(mocks.enable).toHaveBeenCalledWith('123456'))
    expect(await screen.findByText('aaaaa-bbbbb')).toBeInTheDocument()
    const proceed = screen.getByRole('button', { name: 'Үргэлжлүүлэх' })
    expect(proceed).toBeDisabled()
    expect(onDone).not.toHaveBeenCalled()
    fireEvent.click(screen.getByLabelText('Нөөц кодуудаа аюулгүй газар хадгаллаа'))
    fireEvent.click(proceed)
    expect(onDone).toHaveBeenCalled()
  })

  it('asks an enrolled account for a code, or a recovery code, and lets it sign out', async () => {
    mocks.verify.mockResolvedValue({ access_token: 't', expires_in: 900, recovery_codes_left: 9 })
    const onDone = vi.fn()
    render(<TwoFactorGate enrolled onDone={onDone} />)
    expect(screen.getByText('2 шатлалт баталгаажуулалт')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Нөөц код ашиглах' }))
    fireEvent.change(screen.getByLabelText(/Нөөц код/), { target: { value: 'aaaaa-bbbbb' } })
    fireEvent.click(screen.getByRole('button', { name: 'Баталгаажуулах' }))
    await waitFor(() => expect(onDone).toHaveBeenCalled())
    expect(mocks.verify).toHaveBeenCalledWith('aaaaa-bbbbb')
    fireEvent.click(screen.getByRole('button', { name: 'Гарах' }))
    expect(mocks.logout).toHaveBeenCalled()
  })
})

describe('TwoFactorSettings', () => {
  beforeEach(() => {
    Object.values(mocks).forEach((mock) => mock.mockReset())
    useAuthStore.setState({ actor: { id: 1, email: 'admin', employee_id: null, locale: 'mn', roles: ['admin'] } })
  })

  it('switches the requirement on and resets an enrolled account', async () => {
    mocks.update.mockResolvedValue({ required: true, accounts: 4, enrolled: 1 })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<TwoFactorSettings />)
    expect(screen.getByText('Идэвхтэй 4 хэрэглэгчээс 1 нь тохируулсан')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('switch', { name: /Бүх хэрэглэгчээс 2 шатлалт нэвтрэлт шаардах/ }))
    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith(true))
    // Only enrolled accounts are listed for a reset.
    expect(screen.queryByText('bold')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'bat-ийн 2 шатлалт нэвтрэлтийг шинэчлэх' }))
    expect(mocks.reset).toHaveBeenCalledWith(7, expect.anything())
  })

  it('is read-only for non-admins', () => {
    useAuthStore.setState({ actor: { id: 2, email: 'm', employee_id: null, locale: 'mn', roles: ['manager'] } })
    render(<TwoFactorSettings />)
    expect(screen.getByText('Зөвхөн админ өөрчилнө')).toBeInTheDocument()
    expect(screen.queryByRole('switch')).not.toBeInTheDocument()
  })
})
