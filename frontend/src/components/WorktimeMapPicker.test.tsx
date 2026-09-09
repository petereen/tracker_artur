import { fireEvent, render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { WorktimeMapPicker } from './WorktimeMapPicker'

describe('WorktimeMapPicker', () => {
  it('selects a coordinate when the map is clicked', () => {
    const onChange = vi.fn()
    const { getByRole } = render(<WorktimeMapPicker latitude={47.9184} longitude={106.9177} radiusMeters={150} onChange={onChange} />)

    fireEvent.click(getByRole('application'), { clientX: 360, clientY: 160 })

    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange.mock.calls[0][0].latitude).toBeCloseTo(47.9184, 2)
    expect(onChange.mock.calls[0][0].longitude).toBeGreaterThan(106.9177)
  })
})

