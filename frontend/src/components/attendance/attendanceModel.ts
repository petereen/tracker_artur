import type { HRAttendanceItem, HRAttendanceStatus } from '../../api/enterprise'

export type PeriodMode = 'week' | 'month'
/** What a grid cell shows. Leave/sick come from approved leave requests; the rest from attendance. */
export type CellKind = HRAttendanceStatus | 'leave' | 'sick' | 'weekend_off' | 'pending'

export interface GridCell {
  key: string
  item: HRAttendanceItem
  kind: CellKind
  /** Worked on a weekend or public holiday. */
  overtime: boolean
  /** Opens the status editor. */
  editable: boolean
  /** Can join a batch update: editable, a working day, and not in the future. */
  selectable: boolean
}

export interface GridRow {
  employeeId: number
  name: string
  departmentId: number | null
  departmentName: string | null
  cells: GridCell[]
}

export const EDITABLE_STATUSES: HRAttendanceStatus[] = ['present', 'remote', 'late', 'absent']
export const STATUS_LABELS: Record<CellKind, string> = {
  present: 'Ирсэн',
  remote: 'Remote',
  late: 'Хоцорсон',
  absent: 'Ирээгүй',
  leave: 'Чөлөө',
  sick: 'Өвчтэй',
  weekend_off: 'Амралтын өдөр',
  pending: 'Бүртгэлгүй',
}
export const WEEKDAYS = ['Да', 'Мя', 'Лх', 'Пү', 'Ба', 'Бя', 'Ня']

export const toISODate = (value: Date) => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`
const parse = (value: string) => new Date(`${value}T12:00:00`)
export const addDays = (value: string, days: number) => { const date = parse(value); date.setDate(date.getDate() + days); return toISODate(date) }
export const weekdayIndex = (value: string) => (parse(value).getDay() + 6) % 7
export const cellKey = (employeeId: number, date: string) => `${employeeId}|${date}`

export function periodRange(mode: PeriodMode, anchor: string): { start: string; end: string } {
  if (mode === 'week') { const start = addDays(anchor, -weekdayIndex(anchor)); return { start, end: addDays(start, 6) } }
  const date = parse(anchor)
  return { start: toISODate(new Date(date.getFullYear(), date.getMonth(), 1, 12)), end: toISODate(new Date(date.getFullYear(), date.getMonth() + 1, 0, 12)) }
}

export function shiftPeriod(mode: PeriodMode, anchor: string, step: number): string {
  if (mode === 'week') return addDays(anchor, step * 7)
  const date = parse(anchor)
  return toISODate(new Date(date.getFullYear(), date.getMonth() + step, 1, 12))
}

export function periodDates(start: string, end: string): string[] {
  const dates: string[] = []
  for (let current = start; current <= end; current = addDays(current, 1)) dates.push(current)
  return dates
}

export function periodLabel(mode: PeriodMode, start: string, end: string): string {
  if (mode === 'month') return new Intl.DateTimeFormat('mn-MN', { year: 'numeric', month: 'long' }).format(parse(start))
  const short = new Intl.DateTimeFormat('mn-MN', { month: 'short', day: 'numeric' })
  const long = new Intl.DateTimeFormat('mn-MN', { month: 'short', day: 'numeric', year: 'numeric' })
  return `${short.format(parse(start))} – ${long.format(parse(end))}`
}

export function classifyCell(item: HRAttendanceItem, canEdit: boolean, today: string): GridCell {
  const key = cellKey(item.employee_id, item.attendance_date)
  const future = item.attendance_date > today
  if (item.on_leave) return { key, item, kind: item.leave_type === 'sick' ? 'sick' : 'leave', overtime: false, editable: false, selectable: false }
  const editable = canEdit && !future
  // The backend suggests "absent" for any scheduled past day, weekends included;
  // an unrecorded, unworked weekend is simply a day off.
  if (item.is_non_working_day && item.id === null && !item.worked_minutes) return { key, item, kind: 'weekend_off', overtime: false, editable, selectable: false }
  const kind: CellKind = item.status ?? 'pending'
  const overtime = item.is_non_working_day && (kind === 'present' || kind === 'remote' || kind === 'late')
  return { key, item, kind, overtime, editable, selectable: editable && !item.is_non_working_day }
}

export function buildRows(items: HRAttendanceItem[], dates: string[], canEdit: boolean, today: string): GridRow[] {
  const byEmployee = new Map<number, Map<string, HRAttendanceItem>>()
  const rows: GridRow[] = []
  for (const item of items) {
    let days = byEmployee.get(item.employee_id)
    if (!days) {
      days = new Map()
      byEmployee.set(item.employee_id, days)
      rows.push({ employeeId: item.employee_id, name: item.employee_name, departmentId: item.department_id ?? null, departmentName: item.department_name ?? null, cells: [] })
    }
    days.set(item.attendance_date, item)
  }
  for (const row of rows) {
    const days = byEmployee.get(row.employeeId)!
    row.cells = dates.map((date) => {
      const item = days.get(date) ?? { id: null, employee_id: row.employeeId, employee_name: row.name, attendance_date: date, status: null, suggested_status: null, on_leave: false, source: 'derived', worked_minutes: 0, first_started_at: null, last_ended_at: null, confirmed: false, version: null, is_non_working_day: weekdayIndex(date) >= 5, non_working_day_name: null }
      return classifyCell(item, canEdit, today)
    })
  }
  return rows.sort((a, b) => a.name.localeCompare(b.name, 'mn'))
}

export const ALL_DEPARTMENTS = 'all'
export const NO_DEPARTMENT = 'none'

export function filterRows(rows: GridRow[], search: string, department: string): GridRow[] {
  const query = search.trim().toLowerCase()
  const inDepartment = (row: GridRow) => department === ALL_DEPARTMENTS || (department === NO_DEPARTMENT ? row.departmentId === null : String(row.departmentId) === department)
  return rows.filter((row) => inDepartment(row) && (!query || row.name.toLowerCase().includes(query) || String(row.employeeId) === query))
}

export interface Point { r: number; c: number }

/** Selectable cell keys inside the rectangle spanned by two grid points. */
export function rectKeys(rows: GridRow[], a: Point, b: Point): string[] {
  const keys: string[] = []
  for (let r = Math.min(a.r, b.r); r <= Math.max(a.r, b.r); r += 1) {
    const cells = rows[r]?.cells ?? []
    for (let c = Math.min(a.c, b.c); c <= Math.max(a.c, b.c); c += 1) if (cells[c]?.selectable) keys.push(cells[c].key)
  }
  return keys
}

export function rowSelection(row: GridRow, selected: ReadonlySet<string>): boolean | 'indeterminate' {
  const keys = row.cells.filter((cell) => cell.selectable).map((cell) => cell.key)
  const count = keys.filter((key) => selected.has(key)).length
  return count === 0 ? false : count === keys.length ? true : 'indeterminate'
}

export function toggleKeys(selected: ReadonlySet<string>, keys: string[], on: boolean): Set<string> {
  const next = new Set(selected)
  keys.forEach((key) => (on ? next.add(key) : next.delete(key)))
  return next
}

const csvCell = (value: string | number) => { const text = String(value); return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text }

export function buildCsv(rows: GridRow[], dates: string[]): string {
  const header = ['Ажилтан', 'Хэлтэс', ...dates, 'Ирсэн', 'Remote', 'Хоцорсон', 'Ирээгүй', 'Чөлөө', 'Өвчтэй', 'Амралтын өдөр ажилласан', 'Ажилласан цаг']
  const lines = [header]
  for (const row of rows) {
    const counts: Record<CellKind, number> = { present: 0, remote: 0, late: 0, absent: 0, leave: 0, sick: 0, weekend_off: 0, pending: 0 }
    let overtime = 0
    let minutes = 0
    const days = row.cells.map((cell) => {
      if (cell.overtime) overtime += 1
      else counts[cell.kind] += 1
      minutes += cell.item.worked_minutes || 0
      if (cell.kind === 'weekend_off' || cell.kind === 'pending') return ''
      return cell.overtime ? `${STATUS_LABELS[cell.kind]} (амралтын өдөр)` : STATUS_LABELS[cell.kind]
    })
    lines.push([row.name, row.departmentName ?? '', ...days, String(counts.present), String(counts.remote), String(counts.late), String(counts.absent), String(counts.leave), String(counts.sick), String(overtime), (minutes / 60).toFixed(1)])
  }
  return '﻿' + lines.map((line) => line.map(csvCell).join(',')).join('\n')
}

export function chunk<T>(items: T[], size: number): T[][] {
  const chunks: T[][] = []
  for (let index = 0; index < items.length; index += size) chunks.push(items.slice(index, index + size))
  return chunks
}
