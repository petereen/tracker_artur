import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { WorkedHoursInfo } from './WorkedHoursInfo'

const row = {
  id: 1, employee_id: 7, status: 'draft', warnings: [], approved_at: null, approved_by_account_id: null,
  identity: { name: 'Бат' }, profile: {},
  result: { planned_hours: '176', planned_days: 22 },
  inputs: {
    worked_normal_hours: '16', overtime_hours: { weekday: '2' }, missing_dates: ['2026-09-03'],
    approved_leave_days: [{ date: '2026-09-04', fraction: '1', leave_ids: [3] }],
    _source_snapshot: { worked_normal_hours: '16' },
    day_lines: [
      { date: '2026-09-01', day_type: 'working', hours: '10', normal_hours: '8', overtime_hours: { weekday: '2' }, source: 'attendance' },
      { date: '2026-09-02', day_type: 'working', hours: '8', normal_hours: '8', overtime_hours: {}, source: 'worktime' },
    ],
  },
} as any

describe('WorkedHoursInfo', () => {
  it('opens the per-day worked-hours breakdown on click', () => {
    render(<WorkedHoursInfo row={row} isFinal cutoff={null}>16</WorkedHoursInfo>)
    fireEvent.click(screen.getByRole('button', { name: 'Ажилласан цагийн задаргаа харах' }))
    expect(screen.getByRole('heading', { name: 'Ажилласан цагийн задаргаа' })).toBeInTheDocument()
    expect(screen.getByText('HR ирц')).toBeInTheDocument()
    expect(screen.getByText('Цаг бүртгэл')).toBeInTheDocument()
    expect(screen.getByText(/Чөлөө: 1 өдөр/)).toBeInTheDocument()
    expect(screen.getByText(/Бүртгэлгүй ажлын өдөр: 1/)).toBeInTheDocument()
    expect(screen.getByText(/Нийт 18 ц = ердийн 16 ц \+ илүү 2 ц/)).toBeInTheDocument()
  })
})
