import { afterEach, describe, expect, it } from 'vitest'
import { useAuthStore } from './auth'

describe('auth session state', () => {
  const originalState = useAuthStore.getState()

  afterEach(() => useAuthStore.setState(originalState, true))

  it('clears the actor and advances the session identity on login or refresh', () => {
    const before = useAuthStore.getState().sessionVersion
    useAuthStore.getState().setActor({ id: 1, email: 'old@example.com', employee_id: 1, locale: 'mn', roles: ['admin'] })

    useAuthStore.getState().setSession('new-session-token', 900)

    expect(useAuthStore.getState().actor).toBeNull()
    expect(useAuthStore.getState().sessionVersion).toBe(before + 1)
  })
})
