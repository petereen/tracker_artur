import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../store/auth'

const mocks = vi.hoisted(() => ({ refresh: vi.fn() }))

vi.mock('./client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./client')>()),
  refreshAccessToken: mocks.refresh,
}))

import { bootstrapSession } from './enterprise'

const reject = (status?: number) => Object.assign(new Error('refresh failed'), status ? { response: { status } } : {})

describe('bootstrapSession', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    mocks.refresh.mockReset()
    useAuthStore.setState({ token: 'old', initialized: false, bootstrapFailed: false })
  })
  afterEach(() => vi.useRealTimers())

  it('restores the stored session', async () => {
    mocks.refresh.mockResolvedValue('new')
    await bootstrapSession()
    expect(useAuthStore.getState()).toMatchObject({ initialized: true, bootstrapFailed: false })
  })

  it('shows the login screen only when the server refuses the session', async () => {
    mocks.refresh.mockRejectedValue(reject(401))
    await bootstrapSession()
    expect(mocks.refresh).toHaveBeenCalledTimes(1)
    expect(useAuthStore.getState()).toMatchObject({ token: null, initialized: true, bootstrapFailed: false })
  })

  it('retries a missing connection instead of dropping to the login screen', async () => {
    mocks.refresh.mockRejectedValueOnce(reject()).mockResolvedValue('new')
    const done = bootstrapSession()
    await vi.runAllTimersAsync()
    await done
    expect(mocks.refresh).toHaveBeenCalledTimes(2)
    expect(useAuthStore.getState()).toMatchObject({ initialized: true, bootstrapFailed: false })
  })

  it('offers a retry when the server stays unreachable', async () => {
    mocks.refresh.mockRejectedValue(reject(503))
    const done = bootstrapSession()
    await vi.runAllTimersAsync()
    await done
    expect(mocks.refresh).toHaveBeenCalledTimes(4)
    expect(useAuthStore.getState()).toMatchObject({ token: null, initialized: true, bootstrapFailed: true })
  })
})
