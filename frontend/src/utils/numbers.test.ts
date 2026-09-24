import { describe, expect, it } from 'vitest'
import { plainNumber } from './numbers'

describe('plainNumber', () => {
  it('drops Numeric column padding', () => {
    expect(plainNumber('4000000.0000')).toBe('4000000')
    expect(plainNumber('8.50')).toBe('8.5')
    expect(plainNumber('0.0050')).toBe('0.005')
    expect(plainNumber('25000')).toBe('25000')
  })

  it('passes through empty and non-numeric values', () => {
    expect(plainNumber(null)).toBe('')
    expect(plainNumber(undefined)).toBe('')
    expect(plainNumber('12.')).toBe('12.')
    expect(plainNumber('abc')).toBe('abc')
  })
})
