import { beforeEach, describe, expect, it, vi } from 'vitest'

const state = vi.hoisted(() => ({ native: false }))
const values = vi.hoisted(() => new Map<string, string>())
const storage = vi.hoisted(() => ({
  setKeyPrefix: vi.fn(async () => undefined),
  setSynchronize: vi.fn(async () => undefined),
  setDefaultKeychainAccess: vi.fn(async () => undefined),
  getItem: vi.fn(async (key: string) => values.get(key) ?? null),
  setItem: vi.fn(async (key: string, value: string) => { values.set(key, value) }),
  removeItem: vi.fn(async (key: string) => { values.delete(key) }),
}))

vi.mock('@capacitor/core', () => ({ Capacitor: { isNativePlatform: () => state.native, getPlatform: () => state.native ? 'ios' : 'web' } }))
vi.mock('@aparajita/capacitor-secure-storage', () => ({
  SecureStorage: storage,
  KeychainAccess: { afterFirstUnlockThisDeviceOnly: 3 },
}))

describe('native secure session', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.clearAllMocks()
    values.clear()
    state.native = false
  })

  it('never stores web sessions in the native plugin', async () => {
    const session = await import('./secure-session')
    await session.setNativeRefreshToken('web-token')
    expect(await session.getNativeRefreshToken()).toBeNull()
    expect(storage.setItem).not.toHaveBeenCalled()
  })

  it('round-trips and removes a native refresh token', async () => {
    state.native = true
    const session = await import('./secure-session')
    await session.setNativeRefreshToken('native-token')
    expect(await session.getNativeRefreshToken()).toBe('native-token')
    await session.clearNativeRefreshToken()
    expect(await session.getNativeRefreshToken()).toBeNull()
    expect(storage.setKeyPrefix).toHaveBeenCalledWith('mn.oyuns.workspace.')
    expect(storage.setSynchronize).toHaveBeenCalledWith(false)
  })
})
