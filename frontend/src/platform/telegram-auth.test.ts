import { afterEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ post: vi.fn() }))

vi.mock('@capacitor/core', () => ({ Capacitor: { isNativePlatform: () => true, getPlatform: () => 'android' } }))
vi.mock('@capacitor/app', () => ({ App: { addListener: vi.fn(), getLaunchUrl: vi.fn() } }))
vi.mock('../api/client', () => ({ api: { post: mocks.post }, acceptSession: vi.fn() }))

import { isNativeTelegramCallbackUrl, startNativeTelegramLogin } from './telegram-auth'

describe('native Telegram callback allowlist', () => {
  it('accepts only the exact HTTPS callback host and path', () => {
    expect(isNativeTelegramCallbackUrl('https://erp.oyuns.mn/mobile-auth/telegram/callback?code=x&state=y')).toBe(true)
    expect(isNativeTelegramCallbackUrl('https://erp.oyuns.mn/mobile-auth/telegram/callback/extra?code=x&state=y')).toBe(false)
    expect(isNativeTelegramCallbackUrl('http://erp.oyuns.mn/mobile-auth/telegram/callback?code=x&state=y')).toBe(false)
    expect(isNativeTelegramCallbackUrl('https://evil.example/mobile-auth/telegram/callback?code=x&state=y')).toBe(false)
  })
})

describe('native Telegram sign-in', () => {
  const original = window.location
  afterEach(() => { Object.defineProperty(window, 'location', { value: original, writable: true, configurable: true }) })

  it('hands the authorization URL to the system instead of an in-app browser', async () => {
    const assign = vi.fn()
    Object.defineProperty(window, 'location', { value: { ...original, assign }, writable: true, configurable: true })
    mocks.post.mockResolvedValue({ data: { authorization_url: 'https://oauth.telegram.org/auth?client_id=1' } })
    await startNativeTelegramLogin()
    expect(mocks.post).toHaveBeenCalledWith('/v1/auth/telegram-native/start', { platform: 'android' })
    expect(assign).toHaveBeenCalledWith('https://oauth.telegram.org/auth?client_id=1')
  })
})
