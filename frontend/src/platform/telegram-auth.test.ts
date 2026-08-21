import { describe, expect, it } from 'vitest'
import { isNativeTelegramCallbackUrl } from './telegram-auth'

describe('native Telegram callback allowlist', () => {
  it('accepts only the exact HTTPS callback host and path', () => {
    expect(isNativeTelegramCallbackUrl('https://erp.oyuns.mn/mobile-auth/telegram/callback?code=x&state=y')).toBe(true)
    expect(isNativeTelegramCallbackUrl('https://erp.oyuns.mn/mobile-auth/telegram/callback/extra?code=x&state=y')).toBe(false)
    expect(isNativeTelegramCallbackUrl('http://erp.oyuns.mn/mobile-auth/telegram/callback?code=x&state=y')).toBe(false)
    expect(isNativeTelegramCallbackUrl('https://evil.example/mobile-auth/telegram/callback?code=x&state=y')).toBe(false)
  })
})
