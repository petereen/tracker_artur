import { describe, expect, it } from 'vitest'
import { actorQueryKey } from './enterprise'

describe('actor query identity', () => {
  it('separates actor authorization data by authenticated session', () => {
    expect(actorQueryKey(4)).toEqual(['v1', 'actor', 4])
    expect(actorQueryKey(4)).not.toEqual(actorQueryKey(5))
  })
})
