import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AutoWorktimeCard, geoResultKey } from './AutoWorktimeCard'

const NATIVE_STATUS = { enrolled: false, permission: 'prompt', accuracy: 'precise', monitoring: false, regions: 0, pendingEvents: 0, batteryUnrestricted: false, mode: 'on', lastUploadAt: null, lastError: null }

const mocks = vi.hoisted(() => ({
  status: { data: null as null | Record<string, unknown>, refetch: vi.fn(async () => ({})) },
  accept: vi.fn(),
  enroll: vi.fn(),
  revoke: vi.fn(),
  supported: false,
  native: null as null | Record<string, unknown>,
  permissions: vi.fn(),
  enrollGeofence: vi.fn(),
  disableGeofence: vi.fn(async () => null),
  battery: vi.fn(),
  authenticate: vi.fn(async () => true),
}))

vi.mock('../api/worktimeAuto', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/worktimeAuto')>()),
  useAutoWorktimeStatus: () => mocks.status,
  useConsentText: () => ({ isError: false, isLoading: false, data: { policy_version: '2026-10-02', locale: 'mn', text: 'Автомат цаг бүртгэл\n\nТаны газарзүйн координат хадгалагдахгүй.', text_sha256: 'a'.repeat(64) } }),
  useAcceptConsent: () => ({ mutateAsync: mocks.accept, isPending: false }),
  useEnrollDevice: () => ({ mutateAsync: mocks.enroll, isPending: false }),
  useRevokeConsent: () => ({ mutateAsync: mocks.revoke, isPending: false }),
  updateDeviceState: vi.fn(async () => ({})),
}))
vi.mock('../platform/geofence', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../platform/geofence')>()),
  geofenceSupported: async () => mocks.supported,
  getGeofenceStatus: async () => mocks.native,
  geofencePlatform: () => mocks.supported ? 'android' : null,
  requestGeofencePermissions: mocks.permissions,
  enrollGeofence: mocks.enrollGeofence,
  disableGeofence: mocks.disableGeofence,
  requestBatteryExemption: mocks.battery,
}))
vi.mock('../platform/biometric', () => ({
  biometricAvailability: async () => ({ available: true, deviceSecure: true, biometryType: 'fingerprint' }),
  authenticateBiometric: mocks.authenticate,
}))
vi.mock('../platform/runtime', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../platform/runtime')>()),
  isNativePlatform: () => mocks.supported,
}))

const STATUS = { mode: 'on', available: true, employee_linked: true, policy_version: '2026-10-02', consent: null, device: null, site_count: 1, geo_retention_days: 90, recent_events: [] }

describe('AutoWorktimeCard', () => {
  beforeEach(() => {
    // jsdom has no <dialog> modal API.
    HTMLDialogElement.prototype.showModal ??= function showModal(this: HTMLDialogElement) { this.setAttribute('open', '') }
    HTMLDialogElement.prototype.close ??= function close(this: HTMLDialogElement) { this.removeAttribute('open') }
    mocks.status.data = { ...STATUS }
    mocks.supported = false
    mocks.native = null
    for (const mock of [mocks.accept, mocks.enroll, mocks.revoke, mocks.permissions, mocks.enrollGeofence, mocks.battery]) mock.mockReset()
    mocks.authenticate.mockReset().mockResolvedValue(true)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  it('stays out of the way while the organization has it off', () => {
    mocks.status.data = { ...STATUS, mode: 'off' }
    const { container } = render(<AutoWorktimeCard />)
    expect(container).toBeEmptyDOMElement()
  })

  it('points to the mobile app on the web and still lets consent be withdrawn there', async () => {
    mocks.status.data = { ...STATUS, consent: { id: 4, policy_version: '2026-10-02', accepted_at: '2026-10-02T03:00:00Z', locale: 'mn' } }
    mocks.revoke.mockResolvedValue({ revoked: 1, devices_revoked: 1 })
    render(<AutoWorktimeCard />)
    expect(await screen.findByText('Гар утасны апп шаардлагатай')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Асаах' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Зөвшөөрлөө цуцлах' }))
    await waitFor(() => expect(mocks.revoke).toHaveBeenCalled())
    expect(mocks.disableGeofence).toHaveBeenCalled()
  })

  it('takes consent, confirms it is the owner, then enrolls the phone', async () => {
    mocks.supported = true
    mocks.native = { ...NATIVE_STATUS }
    mocks.accept.mockResolvedValue({})
    mocks.permissions.mockResolvedValue({ ...NATIVE_STATUS, permission: 'always' })
    mocks.enroll.mockResolvedValue({ credential: 'device-id.secret' })
    mocks.enrollGeofence.mockResolvedValue({ ...NATIVE_STATUS, enrolled: true, permission: 'always', batteryUnrestricted: false })
    mocks.battery.mockResolvedValue({ ...NATIVE_STATUS, enrolled: true, permission: 'always', batteryUnrestricted: true })
    render(<AutoWorktimeCard />)
    fireEvent.click(await screen.findByRole('button', { name: 'Асаах' }))
    // Nothing is requested from the phone before the disclaimer is accepted.
    expect(mocks.permissions).not.toHaveBeenCalled()
    expect(await screen.findByText('Таны газарзүйн координат хадгалагдахгүй.')).toBeInTheDocument()
    const agree = screen.getByRole('button', { name: 'Зөвшөөрч байна' })
    expect(agree).toBeDisabled()
    fireEvent.click(screen.getByLabelText('Би дээрхийг уншиж, ойлголоо'))
    fireEvent.click(agree)
    await waitFor(() => expect(mocks.enrollGeofence).toHaveBeenCalledWith('device-id.secret'))
    expect(mocks.authenticate).toHaveBeenCalled()
    expect(mocks.accept).toHaveBeenCalledWith(expect.objectContaining({ app_platform: 'android' }))
    expect(mocks.enroll).toHaveBeenCalledWith({ platform: 'android', location_permission: 'always', location_accuracy: 'precise', battery_unrestricted: false })
    // Android: ask to be exempt from battery optimisation right away.
    await waitFor(() => expect(mocks.battery).toHaveBeenCalled())
  })

  it('does not record consent when the owner check fails', async () => {
    mocks.supported = true
    mocks.native = { ...NATIVE_STATUS }
    mocks.authenticate.mockResolvedValue(false)
    render(<AutoWorktimeCard />)
    fireEvent.click(await screen.findByRole('button', { name: 'Асаах' }))
    fireEvent.click(await screen.findByLabelText('Би дээрхийг уншиж, ойлголоо'))
    fireEvent.click(screen.getByRole('button', { name: 'Зөвшөөрч байна' }))
    await waitFor(() => expect(mocks.authenticate).toHaveBeenCalled())
    expect(mocks.accept).not.toHaveBeenCalled()
    expect(mocks.enroll).not.toHaveBeenCalled()
  })

  it('does not enroll without the "always" location permission', async () => {
    mocks.supported = true
    mocks.native = { ...NATIVE_STATUS }
    mocks.status.data = { ...STATUS, consent: { id: 4, policy_version: '2026-10-02', accepted_at: '2026-10-02T03:00:00Z', locale: 'mn' } }
    mocks.permissions.mockResolvedValue({ ...NATIVE_STATUS, permission: 'when_in_use' })
    render(<AutoWorktimeCard />)
    fireEvent.click(await screen.findByRole('button', { name: 'Асаах' }))
    await waitFor(() => expect(mocks.permissions).toHaveBeenCalled())
    expect(mocks.enroll).not.toHaveBeenCalled()
  })

  it('names every rule outcome', () => {
    expect(geoResultKey('started')).toBe('wta.result.started')
    expect(geoResultKey('ignored:mock_location')).toBe('wta.result.mock')
    expect(geoResultKey('ignored:something_new')).toBe('wta.result.ignored')
  })
})
