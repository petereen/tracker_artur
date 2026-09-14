import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import { clearAuthenticatedQueryCache } from './client'

describe('authenticated query cache', () => {
  it('removes account data at the session boundary', async () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(['v1', 'actor'], { id: 1, roles: ['admin'] })
    queryClient.setQueryData(['v1', 'erp', 'meta'], { modules: { payroll: true } })

    await clearAuthenticatedQueryCache(queryClient)

    expect(queryClient.getQueryData(['v1', 'actor'])).toBeUndefined()
    expect(queryClient.getQueryData(['v1', 'erp', 'meta'])).toBeUndefined()
  })
})
