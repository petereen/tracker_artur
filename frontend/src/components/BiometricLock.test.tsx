import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BiometricLockCard, BiometricLockGate } from './BiometricLock'

const mocks = vi.hoisted(() => ({
  native: true,
  enabled: true,
  availability: { available: true, deviceSecure: true, biometryType: 'fingerprint' },
  authenticate: vi.fn(async () => false),
  setEnabled: vi.fn(),
  stateListener: null as null | ((state: { isActive: boolean }) => void),
}))

vi.mock('@capacitor/app', () => ({
  App: { addListener: vi.fn(async (_event: string, listener: (state: { isActive: boolean }) => void) => { mocks.stateListener = listener; return { remove: vi.fn() } }) },
}))
vi.mock('../platform/runtime', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../platform/runtime')>()),
  isNativePlatform: () => mocks.native,
}))
vi.mock('../platform/biometric', () => ({
  biometricAvailability: async () => mocks.availability,
  authenticateBiometric: mocks.authenticate,
  isBiometricLockEnabled: () => mocks.enabled,
  setBiometricLockEnabled: (value: boolean) => { mocks.enabled = value; mocks.setEnabled(value) },
}))
vi.mock('../api/enterprise', () => ({ useEnterpriseLogout: () => ({ mutate: vi.fn(), isPending: false }) }))
vi.mock('./Loading', () => ({ InitialWorkspaceSkeleton: () => null }))

describe('BiometricLockGate', () => {
  beforeEach(() => {
    // jsdom has no <dialog> modal API.
    HTMLDialogElement.prototype.showModal ??= function showModal(this: HTMLDialogElement) { this.setAttribute('open', '') }
    HTMLDialogElement.prototype.close ??= function close(this: HTMLDialogElement) { this.removeAttribute('open') }
    mocks.native = true
    mocks.enabled = true
    mocks.availability = { available: true, deviceSecure: true, biometryType: 'fingerprint' }
    mocks.authenticate.mockReset().mockResolvedValue(false)
    mocks.setEnabled.mockReset()
    mocks.stateListener = null
  })

  it('never locks the web app', () => {
    mocks.native = false
    render(<BiometricLockGate><p>workspace</p></BiometricLockGate>)
    expect(screen.getByText('workspace')).toBeInTheDocument()
    expect(mocks.authenticate).not.toHaveBeenCalled()
  })

  it('does not put the login screen behind the lock while signed out', () => {
    render(<BiometricLockGate active={false}><p>login</p></BiometricLockGate>)
    expect(screen.getByText('login')).toBeInTheDocument()
    expect(mocks.authenticate).not.toHaveBeenCalled()
  })

  it('hides the workspace until the owner is confirmed', async () => {
    render(<BiometricLockGate><p>workspace</p></BiometricLockGate>)
    expect(screen.queryByText('workspace')).not.toBeInTheDocument()
    expect(await screen.findByText('OYUNS түгжээтэй')).toBeInTheDocument()
    await waitFor(() => expect(mocks.authenticate).toHaveBeenCalledTimes(1))
    expect(screen.queryByText('workspace')).not.toBeInTheDocument()
    mocks.authenticate.mockResolvedValue(true)
    fireEvent.click(screen.getByRole('button', { name: 'Түгжээ тайлах' }))
    expect(await screen.findByText('workspace')).toBeInTheDocument()
  })

  it('locks again after a minute in the background, not after a glance away', async () => {
    mocks.authenticate.mockResolvedValue(true)
    render(<BiometricLockGate><p>workspace</p></BiometricLockGate>)
    expect(await screen.findByText('workspace')).toBeInTheDocument()
    await waitFor(() => expect(mocks.stateListener).not.toBeNull())
    const now = vi.spyOn(Date, 'now')
    now.mockReturnValue(1_000_000)
    mocks.stateListener?.({ isActive: false })
    now.mockReturnValue(1_000_000 + 5_000)
    mocks.stateListener?.({ isActive: true })
    expect(screen.getByText('workspace')).toBeInTheDocument()
    mocks.authenticate.mockResolvedValue(false)
    mocks.stateListener?.({ isActive: false })
    now.mockReturnValue(1_000_000 + 5_000 + 61_000)
    mocks.stateListener?.({ isActive: true })
    await waitFor(() => expect(screen.queryByText('workspace')).not.toBeInTheDocument())
    now.mockRestore()
  })

  it('does not trap the user when the phone lost its screen lock', async () => {
    mocks.availability = { available: false, deviceSecure: false, biometryType: 'none' }
    render(<BiometricLockGate><p>workspace</p></BiometricLockGate>)
    expect(await screen.findByText('workspace')).toBeInTheDocument()
    expect(mocks.setEnabled).toHaveBeenCalledWith(false)
    expect(mocks.authenticate).not.toHaveBeenCalled()
  })
})

describe('BiometricLockCard', () => {
  beforeEach(() => {
    mocks.native = true
    mocks.enabled = false
    mocks.availability = { available: true, deviceSecure: true, biometryType: 'fingerprint' }
    mocks.authenticate.mockReset()
    mocks.setEnabled.mockReset()
  })

  it('is not offered on the web', () => {
    mocks.native = false
    const { container } = render(<BiometricLockCard />)
    expect(container).toBeEmptyDOMElement()
  })

  it('switches on only after the owner is confirmed', async () => {
    mocks.authenticate.mockResolvedValue(false)
    render(<BiometricLockCard />)
    const toggle = await screen.findByRole('switch', { name: 'Face ID / хурууны хээгээр түгжих' })
    fireEvent.click(toggle)
    await waitFor(() => expect(mocks.authenticate).toHaveBeenCalledTimes(1))
    expect(mocks.setEnabled).not.toHaveBeenCalled()
    mocks.authenticate.mockResolvedValue(true)
    fireEvent.click(toggle)
    await waitFor(() => expect(mocks.setEnabled).toHaveBeenCalledWith(true))
  })
})
