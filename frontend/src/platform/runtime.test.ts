import { beforeEach, describe, expect, it, vi } from 'vitest'

const capacitor = vi.hoisted(() => ({ native: false, platform: 'web' }))

vi.mock('@capacitor/core', () => ({
  Capacitor: {
    isNativePlatform: () => capacitor.native,
    getPlatform: () => capacitor.platform,
  },
}))

import { getApiBaseUrl, getRealtimeUrl, initializeRuntimeClass, nativePlatform, safeStorage } from './runtime'

describe('platform runtime', () => {
  beforeEach(() => {
    capacitor.native = false
    capacitor.platform = 'web'
    document.documentElement.className = ''
  })

  it('keeps browser API and WebSocket routing on the Vite proxy', () => {
    expect(getApiBaseUrl()).toBe('/api')
    expect(getRealtimeUrl()).toMatch(/^ws:\/\/localhost(?::\d+)?\/api\/v1\/realtime$/)
    initializeRuntimeClass()
    expect(document.documentElement.classList.contains('capacitor-native')).toBe(false)
  })

  it('marks iOS and Android runtimes without treating web as native', () => {
    capacitor.native = true
    capacitor.platform = 'ios'
    initializeRuntimeClass()
    expect(nativePlatform()).toBe('ios')
    expect(document.documentElement.classList.contains('capacitor-native')).toBe(true)
  })

  it('fails closed when browser storage throws', () => {
    const storage = {
      getItem: () => { throw new Error('blocked') },
      setItem: () => { throw new Error('blocked') },
      removeItem: () => { throw new Error('blocked') },
    } as unknown as Storage
    const safe = safeStorage(storage)
    expect(safe.get('key')).toBeNull()
    expect(safe.set('key', 'value')).toBe(false)
    expect(() => safe.remove('key')).not.toThrow()
  })
})
