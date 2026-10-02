import { beforeEach, describe, expect, it, vi } from 'vitest'

const state = vi.hoisted(() => ({ native: false, plugin: null as null | (() => Promise<Record<string, unknown>>) }))

vi.mock('@capacitor/core', () => ({
  Capacitor: { isNativePlatform: () => state.native, getPlatform: () => state.native ? 'android' : 'web' },
  registerPlugin: () => ({
    getNativeCapabilities: () => state.plugin ? state.plugin() : Promise.reject(new Error('"NativeCapabilities" plugin is not implemented on android')),
  }),
}))
vi.mock('@sentry/react', () => ({ addBreadcrumb: vi.fn(), captureException: vi.fn() }))

describe('native capabilities', () => {
  beforeEach(() => {
    vi.resetModules()
    state.native = false
    state.plugin = null
  })

  it('reports nothing native in the browser', async () => {
    const { getNativeCapabilities } = await import('./native-capabilities')
    expect(await getNativeCapabilities()).toEqual({ nativeVersion: 0, geofence: 0, biometric: 0 })
    const { geofenceSupported } = await import('./geofence')
    expect(await geofenceSupported()).toBe(false)
  })

  it('treats a binary without the plugin as build 1 and hides the features', async () => {
    state.native = true
    const { getNativeCapabilities } = await import('./native-capabilities')
    expect(await getNativeCapabilities()).toEqual({ nativeVersion: 1, geofence: 0, biometric: 0 })
    const { geofenceSupported, getGeofenceStatus, refreshGeofence, disableGeofence } = await import('./geofence')
    expect(await geofenceSupported()).toBe(false)
    // A newer bundle on an older binary must not call the missing plugin.
    expect(await getGeofenceStatus()).toBeNull()
    expect(await refreshGeofence()).toBeNull()
    expect(await disableGeofence()).toBeNull()
    const { biometricAvailability } = await import('./biometric')
    expect(await biometricAvailability()).toEqual({ available: false, deviceSecure: false, biometryType: 'none' })
  })

  it('reads what a newer binary offers, once', async () => {
    state.native = true
    state.plugin = vi.fn(async () => ({ nativeVersion: 2, geofence: 1, biometric: 1 }))
    const { getNativeCapabilities } = await import('./native-capabilities')
    expect(await getNativeCapabilities()).toEqual({ nativeVersion: 2, geofence: 1, biometric: 1 })
    await getNativeCapabilities()
    expect(state.plugin).toHaveBeenCalledTimes(1)
    const { geofenceSupported } = await import('./geofence')
    expect(await geofenceSupported()).toBe(true)
  })

  it('maps the phone state to what the server stores', async () => {
    const { deviceState } = await import('./geofence')
    const status = { enrolled: true, permission: 'prompt', accuracy: 'approximate', monitoring: false, regions: 0, pendingEvents: 0, batteryUnrestricted: false, mode: 'on', lastUploadAt: null, lastError: null } as const
    expect(deviceState(status)).toEqual({ location_permission: 'denied', location_accuracy: 'approximate', battery_unrestricted: false })
  })
})
