import { beforeEach, describe, expect, it, vi } from 'vitest'

const state = vi.hoisted(() => ({ native: false, platform: 'web' }))
const updater = vi.hoisted(() => ({
  current: vi.fn(async () => ({ bundle: { version: '1.0.0' }, native: '1.0.0' })),
  download: vi.fn(async () => ({ id: 'bundle-2', version: '1.0.1' })),
  next: vi.fn(async () => ({ id: 'bundle-2', version: '1.0.1' })),
}))

vi.mock('@capacitor/core', () => ({
  Capacitor: {
    isNativePlatform: () => state.native,
    getPlatform: () => state.platform,
  },
}))
vi.mock('@capgo/capacitor-updater', () => ({ CapacitorUpdater: updater }))
vi.mock('@sentry/react', () => ({ addBreadcrumb: vi.fn(), captureException: vi.fn() }))

describe('self-hosted OTA client', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.clearAllMocks()
    state.native = false
    state.platform = 'web'
    vi.stubGlobal('fetch', vi.fn())
  })

  it('does nothing in the browser', async () => {
    const { checkSelfHostedUpdate } = await import('./self-hosted-updater')
    await checkSelfHostedUpdate()
    expect(fetch).not.toHaveBeenCalled()
    expect(updater.current).not.toHaveBeenCalled()
  })

  it('downloads and queues a trusted native bundle', async () => {
    state.native = true
    state.platform = 'android'
    vi.stubEnv('PROD', true)
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      update: {
        version: '1.0.1',
        url: 'https://erp.oyuns.mn/api/v1/mobile-updates/bundles/1.0.1',
        checksum: 'a'.repeat(64),
        size: 123,
        channel: 'production',
      },
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })))

    const { checkSelfHostedUpdate } = await import('./self-hosted-updater')
    await checkSelfHostedUpdate()

    expect(updater.download).toHaveBeenCalledWith(expect.objectContaining({
      version: '1.0.1',
      checksum: 'a'.repeat(64),
      url: expect.stringContaining('/bundles/1.0.1'),
    }))
    expect(updater.next).toHaveBeenCalledWith({ id: 'bundle-2' })
  })
})
