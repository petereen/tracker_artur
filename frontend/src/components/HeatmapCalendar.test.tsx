import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import { HeatmapCalendar } from './HeatmapCalendar'

test('merges duplicate worktime dates and exposes an accessible tooltip', () => {
  render(<HeatmapCalendar endDate={new Date('2026-08-06T12:00:00')} rangeDays={7} data={[{ date: '2026-08-06', value: 60 }, { date: '2026-08-06', value: 30 }]} />)
  expect(screen.getByRole('button', { name: /1.5 цаг/ })).toBeInTheDocument()
})
