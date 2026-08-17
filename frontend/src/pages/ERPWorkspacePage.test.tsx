import { describe, expect, it } from 'vitest'
import { lineTotal } from './ERPWorkspacePage'

describe('ERP document line calculations', () => {
  it('applies percentage discount before VAT', () => {
    expect(lineTotal({ description: 'Widget', quantity: 2, rate: 100, discount_percent: 10, tax_rate: 10 })).toBe(198)
  })

  it('supports a fixed discount and never produces a negative net amount', () => {
    expect(lineTotal({ description: 'Widget', quantity: 1, rate: 25, discount_amount: 40, tax_rate: 10 })).toBe(0)
  })
})
