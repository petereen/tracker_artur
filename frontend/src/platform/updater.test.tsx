import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const state = vi.hoisted(() => ({ native: false }))
const updater = vi.hoisted(() => ({
  addListener: vi.fn(async () => ({ remove: vi.fn() })),
  notifyAppReady: vi.fn(async () => ({ bundle: null })),
  current: vi.fn(async () => ({ bundle: { version: 'builtin' }, native: '1.0.0' })),
  download: vi.fn(async () => ({ id: 'bundle-1', version: '1.0.1' })),
  next: vi.fn(async () => ({ id: 'bundle-1', version: '1.0.1' })),
}))

vi.mock('@capacitor/core', () => ({ Capacitor: { isNativePlatform: () => state.native, getPlatform: () => state.native ? 'ios' : 'web' } }))
vi.mock('@capgo/capacitor-updater', () => ({ CapacitorUpdater: updater }))
vi.mock('@capacitor/app', () => ({ App: { addListener: vi.fn(async () => ({ remove: vi.fn() })) } }))
vi.mock('@sentry/react', () => ({ addBreadcrumb: vi.fn(), captureException: vi.fn() }))

describe('Capgo boot safety boundary', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.clearAllMocks()
    state.native = false
  })

  it('does not initialize the updater on web', async () => {
    const { NativeBootBoundary } = await import('./updater')
    render(<NativeBootBoundary><span>ready</span></NativeBootBoundary>)
    expect(screen.getByText('ready')).toBeInTheDocument()
    expect(updater.notifyAppReady).not.toHaveBeenCalled()
  })

  it('signals readiness after a native React commit', async () => {
    state.native = true
    const { NativeBootBoundary } = await import('./updater')
    render(<NativeBootBoundary><span>native ready</span></NativeBootBoundary>)
    expect(screen.getByText('native ready')).toBeInTheDocument()
    await waitFor(() => expect(updater.notifyAppReady).toHaveBeenCalledTimes(1))
    expect(updater.addListener).toHaveBeenCalledTimes(7)
  })
})
