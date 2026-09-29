import { describe, expect, it } from 'vitest'
import type { HRAttendanceItem } from '../../api/enterprise'
import { ALL_DEPARTMENTS, NO_DEPARTMENT, buildCsv, buildRows, classifyCell, filterRows, periodDates, periodRange, rectKeys, rowSelection, shiftPeriod } from './attendanceModel'

const TODAY = '2026-10-01'
const item = (date: string, patch: Partial<HRAttendanceItem> = {}): HRAttendanceItem => {
  const weekend = [0, 6].includes(new Date(`${date}T12:00:00`).getDay())
  return { id: null, employee_id: 1, employee_name: 'Бат', department_id: 1, department_name: 'Санхүү', attendance_date: date, status: null, suggested_status: null, on_leave: false, leave_type: null, source: 'derived', worked_minutes: 0, first_started_at: null, last_ended_at: null, confirmed: false, version: null, is_non_working_day: weekend, non_working_day_name: weekend ? 'Амралтын өдөр' : null, ...patch }
}

describe('periods', () => {
  it('starts weeks on Monday, including from a Sunday', () => {
    expect(periodRange('week', '2026-10-04')).toEqual({ start: '2026-09-28', end: '2026-10-04' })
    expect(periodRange('week', '2026-09-28')).toEqual({ start: '2026-09-28', end: '2026-10-04' })
  })

  it('covers whole months and steps across year ends', () => {
    expect(periodRange('month', '2026-02-14')).toEqual({ start: '2026-02-01', end: '2026-02-28' })
    expect(periodDates('2026-09-01', '2026-09-30')).toHaveLength(30)
    expect(shiftPeriod('month', '2026-01-31', 1)).toBe('2026-02-01')
    expect(shiftPeriod('month', '2026-12-05', 1)).toBe('2027-01-01')
    expect(shiftPeriod('week', '2026-12-29', 1)).toBe('2027-01-05')
  })
})

describe('classifyCell', () => {
  it('shows approved sick leave as locked sick', () => {
    expect(classifyCell(item('2026-09-29', { on_leave: true, leave_type: 'sick' }), true, TODAY)).toMatchObject({ kind: 'sick', editable: false, selectable: false })
    expect(classifyCell(item('2026-09-29', { on_leave: true, leave_type: 'annual' }), true, TODAY).kind).toBe('leave')
  })

  it('treats an unrecorded weekend as a day off even when absence is suggested', () => {
    expect(classifyCell(item('2026-09-27', { status: 'absent', suggested_status: 'absent' }), true, TODAY)).toMatchObject({ kind: 'weekend_off', editable: true, selectable: false })
  })

  it('flags weekend work as overtime and keeps it out of batch selection', () => {
    expect(classifyCell(item('2026-09-27', { status: 'present', worked_minutes: 90 }), true, TODAY)).toMatchObject({ kind: 'present', overtime: true, selectable: false })
  })

  it('makes future days read-only and past working days selectable', () => {
    expect(classifyCell(item('2026-10-02'), true, TODAY)).toMatchObject({ kind: 'pending', editable: false, selectable: false })
    expect(classifyCell(item('2026-09-30', { status: 'absent' }), true, TODAY)).toMatchObject({ kind: 'absent', editable: true, selectable: true })
    expect(classifyCell(item('2026-09-30', { status: 'absent' }), false, TODAY).editable).toBe(false)
  })
})

describe('selection and export', () => {
  const dates = periodDates('2026-09-28', '2026-10-04')
  const items = [
    ...dates.map((date) => item(date, { status: date === '2026-09-29' ? 'remote' : 'present', worked_minutes: date === '2026-10-04' ? 120 : 0 })),
    ...dates.map((date) => item(date, { employee_id: 2, employee_name: 'Анар, "Ахлах"', department_id: null, department_name: null, status: 'absent' })),
  ]
  const rows = buildRows(items, dates, true, TODAY)

  it('sorts rows and selects only eligible cells in a rectangle', () => {
    expect(rows.map((row) => row.name)).toEqual(['Анар, "Ахлах"', 'Бат'])
    // Mon..Sun across both rows: weekends and days after Oct 1 are skipped.
    expect(rectKeys(rows, { r: 0, c: 0 }, { r: 1, c: 6 })).toEqual(['2|2026-09-28', '2|2026-09-29', '2|2026-09-30', '2|2026-10-01', '1|2026-09-28', '1|2026-09-29', '1|2026-09-30', '1|2026-10-01'])
    expect(rowSelection(rows[1], new Set(['1|2026-09-28']))).toBe('indeterminate')
    expect(rowSelection(rows[1], new Set(rectKeys(rows, { r: 1, c: 0 }, { r: 1, c: 6 })))).toBe(true)
  })

  it('filters by name, id and missing department', () => {
    expect(filterRows(rows, 'бат', ALL_DEPARTMENTS).map((row) => row.employeeId)).toEqual([1])
    expect(filterRows(rows, '2', ALL_DEPARTMENTS).map((row) => row.employeeId)).toEqual([2])
    expect(filterRows(rows, '', NO_DEPARTMENT).map((row) => row.employeeId)).toEqual([2])
    expect(filterRows(rows, '', '1').map((row) => row.employeeId)).toEqual([1])
  })

  it('exports a wide CSV with weekend work counted separately', () => {
    const csv = buildCsv(rows, dates)
    const [header, anar, bat] = csv.replace('﻿', '').split('\n')
    expect(header.split(',')).toHaveLength(2 + 7 + 8)
    expect(anar.startsWith('"Анар, ""Ахлах""",,Ирээгүй')).toBe(true)
    // Бат: 4 present + 1 remote on weekdays; Sat is off, Sun worked 2h.
    expect(bat.endsWith(',4,1,0,0,0,0,1,2.0')).toBe(true)
    expect(bat).toContain('Ирсэн (амралтын өдөр)')
  })
})
