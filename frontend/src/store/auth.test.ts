import { afterEach, describe, expect, it } from 'vitest'
import { useAuthStore } from './auth'

describe('auth session state', () => {
  const originalState = useAuthStore.getState()

  afterEach(() => useAuthStore.setState(originalState, true))

  it('clears the actor and advances the session identity on account replacement', () => {
    const before = useAuthStore.getState().sessionVersion
    useAuthStore.getState().setActor({ id: 1, email: 'old@example.com', employee_id: 1, locale: 'mn', roles: ['admin'] })

    useAuthStore.getState().setSession('new-session-token', 900)

    expect(useAuthStore.getState().actor).toBeNull()
    expect(useAuthStore.getState().sessionVersion).toBe(before + 1)
  })

  it('rotates credentials without clearing the actor identity', () => {
    useAuthStore.getState().setActor({ id: 1, email: 'old@example.com', employee_id: 1, locale: 'mn', roles: ['admin'] })
    const before = useAuthStore.getState().sessionVersion
    useAuthStore.getState().setSession('initial-token', 900)
    useAuthStore.getState().setActor({ id: 1, email: 'old@example.com', employee_id: 1, locale: 'mn', roles: ['admin'] })
    useAuthStore.getState().setRefreshedSession('rotated-token', 900)

    expect(useAuthStore.getState().actor?.id).toBe(1)
    expect(useAuthStore.getState().token).toBe('rotated-token')
    expect(useAuthStore.getState().sessionVersion).toBe(before + 1)
  })
})
