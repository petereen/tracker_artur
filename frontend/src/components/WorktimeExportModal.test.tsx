import { describe, expect, it } from 'vitest'
import { presetRange } from './WorktimeExportModal'

describe('worktime report date presets', () => {
  it('selects the current month', () => {
    expect(presetRange('month', new Date(2026, 7, 21))).toEqual({ from: '2026-08-01', to: '2026-08-31' })
  })

  it('selects the current or previous 5th–15th period', () => {
    expect(presetRange('five_to_fifteen', new Date(2026, 7, 10))).toEqual({ from: '2026-08-05', to: '2026-08-15' })
    expect(presetRange('five_to_fifteen', new Date(2026, 7, 2))).toEqual({ from: '2026-07-05', to: '2026-07-15' })
  })

  it('selects the containing or most recent 15th–5th period', () => {
    expect(presetRange('fifteen_to_five', new Date(2026, 7, 21))).toEqual({ from: '2026-08-15', to: '2026-09-05' })
    expect(presetRange('fifteen_to_five', new Date(2026, 7, 10))).toEqual({ from: '2026-07-15', to: '2026-08-05' })
  })
})

