import { beforeEach, describe, expect, it, vi } from 'vitest'

const state = vi.hoisted(() => ({ native: false, platform: 'web', permission: 'prompt' as string }))
const push = vi.hoisted(() => ({
  callbacks: new Map<string, (value: any) => void>(),
  checkPermissions: vi.fn(async () => ({ receive: state.permission })),
  requestPermissions: vi.fn(async () => ({ receive: state.permission })),
  register: vi.fn(async () => undefined),
  unregister: vi.fn(async () => undefined),
  createChannel: vi.fn(async () => undefined),
  addListener: vi.fn(async (name: string, callback: (value: any) => void) => {
    push.callbacks.set(name, callback)
    return { remove: vi.fn() }
  }),
}))
const api = vi.hoisted(() => ({ put: vi.fn(async () => undefined), delete: vi.fn(async () => undefined) }))
const secure = vi.hoisted(() => new Map<string, string>())

vi.mock('@capacitor/core', () => ({
  Capacitor: { isNativePlatform: () => state.native, getPlatform: () => state.platform },
}))
vi.mock('@capacitor/push-notifications', () => ({ PushNotifications: push }))
vi.mock('../api/client', () => ({ api }))
vi.mock('./secure-session', () => ({
  readSecureValue: vi.fn(async (key: string) => secure.get(key) ?? null),
  writeSecureValue: vi.fn(async (key: string, value: string) => { secure.set(key, value) }),
  removeSecureValue: vi.fn(async (key: string) => { secure.delete(key) }),
}))
vi.mock('@sentry/react', () => ({ addBreadcrumb: vi.fn() }))

describe('native notification service', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.clearAllMocks()
    push.callbacks.clear()
    secure.clear()
    state.native = false
    state.platform = 'web'
    state.permission = 'prompt'
  })

  it('is a strict no-op in web browsers', async () => {
    const { notificationService } = await import('./notifications')
    expect(await notificationService.getPermissionState()).toBe('unsupported')
    expect(await notificationService.requestPermissionAndRegister()).toBe('unsupported')
    expect(push.checkPermissions).not.toHaveBeenCalled()
    expect(push.requestPermissions).not.toHaveBeenCalled()
    expect(push.register).not.toHaveBeenCalled()
  })

  it('maps an iOS registration to APNs', async () => {
    state.native = true
    state.platform = 'ios'
    state.permission = 'granted'
    const { notificationService } = await import('./notifications')
    await notificationService.syncExistingRegistration()
    push.callbacks.get('registration')?.({ value: 'a'.repeat(64) })
    await vi.waitFor(() => expect(api.put).toHaveBeenCalledWith('/v1/mobile/push-registration', {
      platform: 'ios', provider: 'apns', token: 'a'.repeat(64),
    }))
  })

  it('maps an Android registration to FCM and creates the default channel', async () => {
    state.native = true
    state.platform = 'android'
    state.permission = 'granted'
    const { notificationService } = await import('./notifications')
    await notificationService.syncExistingRegistration()
    push.callbacks.get('registration')?.({ value: 'b'.repeat(64) })
    await vi.waitFor(() => expect(api.put).toHaveBeenCalledWith('/v1/mobile/push-registration', {
      platform: 'android', provider: 'fcm', token: 'b'.repeat(64),
    }))
    expect(push.createChannel).toHaveBeenCalledWith(expect.objectContaining({ id: 'oyuns-default' }))
  })
})
