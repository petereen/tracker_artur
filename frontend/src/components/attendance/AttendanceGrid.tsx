import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent, MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent } from 'react'
import { createPortal } from 'react-dom'
import { useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Check, ChevronLeft, ChevronRight, Clock3, Download, Laptop, RotateCcw, Thermometer, TreePalm, X } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Badge } from '@astryxdesign/core/Badge'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { CheckboxInput } from '@astryxdesign/core/CheckboxInput'
import { EmptyState } from '@astryxdesign/core/EmptyState'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { SegmentedControl, SegmentedControlItem } from '@astryxdesign/core/SegmentedControl'
import { Selector } from '@astryxdesign/core/Selector'
import { Skeleton } from '@astryxdesign/core/Skeleton'
import { Text } from '@astryxdesign/core/Text'
import { TextInput } from '@astryxdesign/core/TextInput'
import { VStack } from '@astryxdesign/core/VStack'
import { saveCompanyBlob, useBulkUpdateHRAttendance, useHRAttendance, useResetHRAttendance, useUpdateHRAttendance } from '../../api/enterprise'
import type { HRAttendanceItem, HRAttendanceStatus } from '../../api/enterprise'
import {
  ALL_DEPARTMENTS, EDITABLE_STATUSES, NO_DEPARTMENT, STATUS_LABELS, WEEKDAYS,
  buildCsv, buildRows, cellKey, chunk, filterRows, periodDates, periodLabel, periodRange, rectKeys, rowSelection, shiftPeriod, toISODate, toggleKeys, weekdayIndex,
} from './attendanceModel'
import type { CellKind, GridCell, GridRow, PeriodMode, Point } from './attendanceModel'
import './AttendanceGrid.css'

const PERIOD_STORAGE_KEY = 'oyuns.attendance.period'
const VIRTUALIZE_AT = 50
const OVERSCAN = 8
const ROW_HEIGHT: Record<PeriodMode, number> = { week: 52, month: 44 }
const BULK_LIMIT = 500

const STATUS_ICONS: Record<CellKind, LucideIcon | null> = { present: Check, remote: Laptop, late: Clock3, absent: X, leave: TreePalm, sick: Thermometer, weekend_off: null, pending: null }
const longDate = new Intl.DateTimeFormat('mn-MN', { weekday: 'long', month: 'long', day: 'numeric' })
const formatLongDate = (value: string) => longDate.format(new Date(`${value}T12:00:00`))
const formatTime = (value: string | null) => value ? new Date(value).toLocaleTimeString('mn-MN', { hour: '2-digit', minute: '2-digit' }) : null
const formatMinutes = (minutes: number) => `${Math.floor(minutes / 60)}ц ${minutes % 60}м`

const readPeriod = (): PeriodMode => { try { return window.localStorage.getItem(PERIOD_STORAGE_KEY) === 'month' ? 'month' : 'week' } catch { return 'week' } }
const writePeriod = (mode: PeriodMode) => { try { window.localStorage.setItem(PERIOD_STORAGE_KEY, mode) } catch { /* storage unavailable */ } }

const errorText = (error: unknown) => {
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } })?.response
  if (response?.status === 409) return 'Энэ өдрийн ирцийг өөр хэрэглэгч өөрчилсөн байна. Мэдээллийг шинэчиллээ.'
  return typeof response?.data?.detail === 'string' ? response.data.detail : 'Ирц хадгалж чадсангүй'
}

const describeCell = (cell: GridCell) => cell.overtime ? `${STATUS_LABELS[cell.kind]} · амралтын өдөр ажилласан` : cell.kind === 'weekend_off' && cell.item.non_working_day_name ? cell.item.non_working_day_name : STATUS_LABELS[cell.kind]

function StatusBadge({ kind, confirmed, overtime, compact }: { kind: CellKind; confirmed: boolean; overtime: boolean; compact: boolean }) {
  if (kind === 'weekend_off') return null
  const Icon = STATUS_ICONS[kind]
  const suggested = !confirmed && kind !== 'leave' && kind !== 'sick'
  return <span className={`att-badge att-badge--${kind}${suggested ? ' is-suggested' : ''}${overtime ? ' is-overtime' : ''}`} aria-hidden="true">
    {Icon && <Icon size={13} strokeWidth={2.4} />}
    {!compact && kind !== 'pending' && <span className="att-badge-label">{STATUS_LABELS[kind]}</span>}
    {overtime && <span className="att-badge-ot">+</span>}
  </span>
}

interface CellProps { r: number; c: number; cell: GridCell; rowName: string; selected: boolean; tabbable: boolean; compact: boolean; weekend: boolean; today: boolean }

const Cell = memo(function Cell({ r, c, cell, rowName, selected, tabbable, compact, weekend, today }: CellProps) {
  const className = ['att-cell', weekend && 'is-weekend', today && 'is-today', cell.kind === 'weekend_off' && 'is-off', selected && 'is-selected', !cell.editable && 'is-readonly'].filter(Boolean).join(' ')
  return <td role="gridcell" className={className} data-cell={`${r}:${c}`} tabIndex={tabbable ? 0 : -1} aria-selected={selected} aria-label={`${rowName}, ${formatLongDate(cell.item.attendance_date)}: ${describeCell(cell)}`} title={cell.kind === 'weekend_off' ? cell.item.non_working_day_name ?? undefined : undefined}>
    <StatusBadge kind={cell.kind} confirmed={cell.item.confirmed} overtime={cell.overtime} compact={compact} />
  </td>
})

interface RowProps { row: GridRow; r: number; selected: ReadonlySet<string>; active: Point | null; canEdit: boolean; compact: boolean; weekendCols: boolean[]; todayCol: number; onToggleRow: (row: GridRow, on: boolean) => void }

const Row = memo(function Row({ row, r, selected, active, canEdit, compact, weekendCols, todayCol, onToggleRow }: RowProps) {
  const rowState = canEdit ? rowSelection(row, selected) : false
  const hasSelectable = row.cells.some((cell) => cell.selectable)
  return <tr role="row" aria-rowindex={r + 2} className={rowState ? 'is-row-selected' : undefined}>
    <th role="rowheader" scope="row" className="att-sticky att-name-cell"><span className="att-name-inner">
      <span className="att-row-index">{r + 1}</span>
      {canEdit && <span className="att-row-check"><CheckboxInput label={`${row.name}: мөрийн бүх өдрийг сонгох`} isLabelHidden size="sm" value={rowState} isDisabled={!hasSelectable} onChange={(checked) => onToggleRow(row, checked)} /></span>}
      <span className="att-person"><strong>{row.name}</strong>{row.departmentName && <small>{row.departmentName}</small>}</span>
    </span></th>
    {row.cells.map((cell, c) => <Cell key={cell.key} r={r} c={c} cell={cell} rowName={row.name} selected={selected.has(cell.key)} tabbable={active ? active.r === r && active.c === c : r === 0 && c === 0} compact={compact} weekend={weekendCols[c]} today={todayCol === c} />)}
  </tr>
})

interface EditorProps { cell: GridCell; rowName: string; anchor: HTMLElement; canEdit: boolean; onPick: (status: HRAttendanceStatus) => void; onReset: () => void; onClose: (restoreFocus: boolean) => void; onOpenLeave?: () => void }

function CellEditor({ cell, rowName, anchor, canEdit, onPick, onReset, onClose, onOpenLeave }: EditorProps) {
  const ref = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null)
  const { item } = cell
  const weekendOff = cell.kind === 'weekend_off'
  const future = !cell.editable && canEdit && !item.on_leave
  const options: HRAttendanceStatus[] = weekendOff ? ['present', 'remote'] : EDITABLE_STATUSES

  useLayoutEffect(() => {
    const surface = ref.current
    if (!surface) return
    const rect = anchor.getBoundingClientRect()
    const { offsetWidth: width, offsetHeight: height } = surface
    const gutter = 8
    const below = rect.bottom + 6
    const top = below + height > window.innerHeight - gutter && rect.top - height - 6 > gutter ? rect.top - height - 6 : Math.min(below, window.innerHeight - height - gutter)
    setPosition({ top: Math.max(gutter, top), left: Math.min(Math.max(gutter, rect.left), window.innerWidth - width - gutter) })
  }, [anchor])

  useEffect(() => {
    const first = ref.current?.querySelector<HTMLElement>('[aria-checked="true"]') ?? ref.current?.querySelector<HTMLElement>('[role^="menuitem"]')
    ;(first ?? ref.current)?.focus()
  }, [])

  useEffect(() => {
    const onPointer = (event: PointerEvent) => { const target = event.target as Node; if (!ref.current?.contains(target) && !anchor.contains(target)) onClose(false) }
    const onResize = () => onClose(false)
    document.addEventListener('pointerdown', onPointer, true)
    window.addEventListener('resize', onResize)
    return () => { document.removeEventListener('pointerdown', onPointer, true); window.removeEventListener('resize', onResize) }
  }, [anchor, onClose])

  const onKeyDown = (event: ReactKeyboardEvent) => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); onClose(true); return }
    if (event.key === 'Tab') { onClose(true); return }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
    event.preventDefault()
    const items = [...(ref.current?.querySelectorAll<HTMLElement>('[role^="menuitem"]') ?? [])]
    const index = items.indexOf(document.activeElement as HTMLElement)
    items[(index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus()
  }

  const times = [formatTime(item.first_started_at), formatTime(item.last_ended_at)].filter(Boolean).join(' – ')
  const source = item.on_leave ? 'Батлагдсан чөлөөний хүсэлт' : item.confirmed ? 'Баталгаажсан' : item.source === 'worktime' ? 'Ажлын цагаас автоматаар' : cell.kind === 'pending' || weekendOff ? null : 'Автомат санал'

  return createPortal(<div ref={ref} className="att-editor" role="dialog" tabIndex={-1} aria-label={`${rowName} · ${formatLongDate(item.attendance_date)}`} onKeyDown={onKeyDown} style={{ top: position?.top ?? -9999, left: position?.left ?? -9999 }}>
    <header>
      <strong>{rowName}</strong>
      <span>{formatLongDate(item.attendance_date)}{item.non_working_day_name ? ` · ${item.non_working_day_name}` : ''}</span>
      {(item.worked_minutes > 0 || source) && <small>{[item.worked_minutes > 0 ? `Ажилласан ${formatMinutes(item.worked_minutes)}` : null, times || null, source].filter(Boolean).join(' · ')}</small>}
    </header>
    {item.on_leave ? <div className="att-editor-note">
      <p>{cell.kind === 'sick' ? 'Өвчний' : 'Батлагдсан'} чөлөө энэ өдрийг хамарна. Ирцийг чөлөөний хүсэлтээс засна.</p>
      {onOpenLeave && <button type="button" role="menuitem" className="att-editor-link" onClick={() => { onClose(false); onOpenLeave() }}>Чөлөөний хүсэлт рүү очих</button>}
    </div> : future ? <p className="att-editor-note">Ирээдүйн өдрийн ирцийг бүртгэх боломжгүй.</p>
      : !cell.editable ? null
      : <>
        {weekendOff && <p className="att-editor-note">Амралтын өдөр. Ажилласан бол илүү цагаар тэмдэглэнэ.</p>}
        <div role="menu" aria-label="Ирцийн төлөв" className="att-editor-options">
          {options.map((status) => { const Icon = STATUS_ICONS[status]!; const current = item.confirmed && item.status === status; return <button key={status} type="button" role="menuitemradio" aria-checked={current} className={`att-editor-option att-editor-option--${status}`} onClick={() => onPick(status)}>
            <span className={`att-badge att-badge--${status}`} aria-hidden="true"><Icon size={13} strokeWidth={2.4} /></span>
            <span>{STATUS_LABELS[status]}{weekendOff ? ' (илүү цаг)' : ''}</span>
            {current && <Check size={14} className="att-editor-current" aria-hidden="true" />}
          </button> })}
          {item.confirmed && <button type="button" role="menuitem" className="att-editor-option att-editor-reset" onClick={onReset}><RotateCcw size={14} aria-hidden="true" /><span>{item.is_non_working_day ? 'Амралтын өдөр болгох' : 'Автомат төлөвт буцаах'}</span></button>}
        </div>
      </>}
  </div>, document.body)
}

function Legend() {
  return <HStack gap={3} wrap="wrap" vAlign="center">
    {(['present', 'remote', 'late', 'absent', 'leave', 'sick'] as const).map((kind) => <span key={kind} className="att-legend-item"><StatusBadge kind={kind} confirmed overtime={false} compact /><Text type="supporting">{STATUS_LABELS[kind]}</Text></span>)}
    <span className="att-legend-item"><StatusBadge kind="present" confirmed overtime compact /><Text type="supporting">Амралтын өдөр ажилласан</Text></span>
    <span className="att-legend-item"><StatusBadge kind="present" confirmed={false} overtime={false} compact /><Text type="supporting">Баталгаажаагүй (автомат)</Text></span>
    <span className="att-legend-item"><span className="att-legend-off" aria-hidden="true" /><Text type="supporting">Амралтын өдөр</Text></span>
  </HStack>
}

export function AttendanceGrid({ canEdit, onOpenLeave }: { canEdit: boolean; onOpenLeave?: () => void }) {
  const today = toISODate(new Date())
  const [mode, setMode] = useState<PeriodMode>(readPeriod)
  const [anchorDate, setAnchorDate] = useState(today)
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [department, setDepartment] = useState(ALL_DEPARTMENTS)
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set())
  const [active, setActive] = useState<Point | null>(null)
  const [editor, setEditor] = useState<Point | null>(null)
  const [scrollTop, setScrollTop] = useState(0)
  const [viewportHeight, setViewportHeight] = useState(600)
  const scrollRef = useRef<HTMLDivElement>(null)
  const headRef = useRef<HTMLTableSectionElement>(null)
  const selectionAnchor = useRef<Point | null>(null)
  const drag = useRef<{ start: Point; moved: boolean } | null>(null)
  const suppressClick = useRef(false)
  const pendingFocus = useRef(false)

  const { start, end } = periodRange(mode, anchorDate)
  const dates = useMemo(() => periodDates(start, end), [start, end])
  const attendance = useHRAttendance(start, end)
  const update = useUpdateHRAttendance()
  const bulk = useBulkUpdateHRAttendance()
  const reset = useResetHRAttendance()
  const queryClient = useQueryClient()

  const rows = useMemo(() => buildRows(attendance.data?.items ?? [], dates, canEdit, today), [attendance.data, dates, canEdit, today])
  const visibleRows = useMemo(() => filterRows(rows, search, department), [rows, search, department])
  const departments = useMemo(() => {
    const seen = new Map<string, string>()
    rows.forEach((row) => seen.set(row.departmentId === null ? NO_DEPARTMENT : String(row.departmentId), row.departmentName ?? 'Хэлтэсгүй'))
    return [{ value: ALL_DEPARTMENTS, label: 'Бүх алба/нэгж' }, ...[...seen.entries()].sort((a, b) => a[1].localeCompare(b[1], 'mn')).map(([value, label]) => ({ value, label }))]
  }, [rows])
  const weekendCols = useMemo(() => dates.map((date) => weekdayIndex(date) >= 5), [dates])
  const holidayCols = useMemo(() => dates.map((date) => visibleRows[0]?.cells.find((cell) => cell.item.attendance_date === date)?.item.non_working_day_name ?? null), [dates, visibleRows])
  const offCols = useMemo(() => dates.map((_, c) => weekendCols[c] || Boolean(visibleRows[0]?.cells[c]?.item.is_non_working_day)), [dates, weekendCols, visibleRows])
  const todayCol = dates.indexOf(today)
  const selectedCells = useMemo(() => visibleRows.flatMap((row) => row.cells.filter((cell) => cell.selectable && selected.has(cell.key))), [visibleRows, selected])
  const unconfirmed = useMemo(() => visibleRows.reduce((sum, row) => sum + row.cells.filter((cell) => cell.selectable && !cell.item.confirmed).length, 0), [visibleRows])
  const busy = update.isPending || bulk.isPending || reset.isPending
  const compact = mode === 'month'

  useEffect(() => { const timer = window.setTimeout(() => setSearch(searchInput), 200); return () => window.clearTimeout(timer) }, [searchInput])
  // A selection only means something for the rows and dates currently on screen.
  useEffect(() => { setSelected(new Set()); setEditor(null); setActive(null); selectionAnchor.current = null }, [start, end, search, department])

  // Row windowing keeps month view responsive for large teams.
  const virtual = visibleRows.length > VIRTUALIZE_AT
  const rowHeight = ROW_HEIGHT[mode]
  const headHeight = headRef.current?.offsetHeight ?? 48
  const firstRow = virtual ? Math.max(0, Math.floor((scrollTop - headHeight) / rowHeight) - OVERSCAN) : 0
  const lastRow = virtual ? Math.min(visibleRows.length, Math.ceil((scrollTop - headHeight + viewportHeight) / rowHeight) + OVERSCAN) : visibleRows.length

  useEffect(() => {
    const node = scrollRef.current
    if (!node || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => setViewportHeight(node.clientHeight))
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  const onScroll = useCallback(() => { setScrollTop(scrollRef.current?.scrollTop ?? 0); setEditor(null) }, [])

  const cellAt = (point: Point | null) => (point ? visibleRows[point.r]?.cells[point.c] : undefined)
  const pointFrom = (target: EventTarget | null): Point | null => {
    const value = (target as HTMLElement | null)?.closest?.('[data-cell]')?.getAttribute('data-cell')
    if (!value) return null
    const [r, c] = value.split(':').map(Number)
    return { r, c }
  }

  const focusCell = useCallback((point: Point) => {
    const node = scrollRef.current
    if (!node) return
    const target = node.querySelector<HTMLElement>(`[data-cell="${point.r}:${point.c}"]`)
    if (target) { target.focus({ preventScroll: true }); target.scrollIntoView?.({ block: 'nearest', inline: 'nearest' }); return }
    // Row is windowed out: scroll it in and focus after the next render.
    node.scrollTop = headHeight + point.r * rowHeight - node.clientHeight / 2
    pendingFocus.current = true
  }, [headHeight, rowHeight])

  useEffect(() => {
    if (!active || !pendingFocus.current) return
    const target = scrollRef.current?.querySelector<HTMLElement>(`[data-cell="${active.r}:${active.c}"]`)
    if (target) { pendingFocus.current = false; target.focus({ preventScroll: true }); target.scrollIntoView?.({ block: 'nearest', inline: 'nearest' }) }
  })

  const moveTo = (point: Point, extend: boolean) => {
    const next = { r: Math.max(0, Math.min(visibleRows.length - 1, point.r)), c: Math.max(0, Math.min(dates.length - 1, point.c)) }
    if (extend && canEdit) {
      selectionAnchor.current ??= active ?? next
      setSelected(new Set(rectKeys(visibleRows, selectionAnchor.current, next)))
    } else if (!extend) {
      selectionAnchor.current = next
    }
    setActive(next)
    pendingFocus.current = true
    focusCell(next)
  }

  const patchCache = (keys: ReadonlySet<string>, patch: (item: HRAttendanceItem) => HRAttendanceItem) => {
    queryClient.setQueryData<{ items: HRAttendanceItem[] }>(['v1', 'hr', 'attendance', start, end, undefined], (old) => old && { ...old, items: old.items.map((item) => keys.has(cellKey(item.employee_id, item.attendance_date)) ? patch(item) : item) })
  }

  const applyStatus = async (targets: GridCell[], status: HRAttendanceStatus) => {
    const cells = targets.filter((cell) => cell.editable)
    if (!cells.length) return false
    const payload = cells.map((cell) => ({ employee_id: cell.item.employee_id, attendance_date: cell.item.attendance_date, status, version: cell.item.version ?? undefined }))
    patchCache(new Set(cells.map((cell) => cell.key)), (item) => ({ ...item, id: item.id ?? -1, status, confirmed: true, source: 'manual' }))
    try {
      if (payload.length === 1) await update.mutateAsync(payload[0])
      else for (const part of chunk(payload, BULK_LIMIT)) await bulk.mutateAsync(part)
      return true
    } catch (error) {
      toast.error(errorText(error))
      queryClient.invalidateQueries({ queryKey: ['v1', 'hr', 'attendance'] })
      return false
    }
  }

  const closeEditor = useCallback((restoreFocus: boolean) => {
    setEditor((current) => { if (restoreFocus && current) window.requestAnimationFrame(() => focusCell(current)); return null })
  }, [focusCell])

  const pickStatus = async (status: HRAttendanceStatus) => {
    const point = editor
    const cell = cellAt(point)
    closeEditor(true)
    if (cell) await applyStatus([cell], status)
  }

  const resetCell = async () => {
    const cell = cellAt(editor)
    closeEditor(true)
    if (!cell) return
    try { await reset.mutateAsync({ employee_id: cell.item.employee_id, attendance_date: cell.item.attendance_date, version: cell.item.version ?? undefined }) } catch (error) { toast.error(errorText(error)); queryClient.invalidateQueries({ queryKey: ['v1', 'hr', 'attendance'] }) }
  }

  const batch = async (status: HRAttendanceStatus) => {
    const count = selectedCells.length
    if (await applyStatus(selectedCells, status)) { setSelected(new Set()); toast.success(`${count} өдрийн ирц шинэчлэгдлээ`) }
  }

  const toggleRow = useCallback((row: GridRow, on: boolean) => setSelected((current) => toggleKeys(current, row.cells.filter((cell) => cell.selectable).map((cell) => cell.key), on)), [])
  const allSelectable = useMemo(() => visibleRows.flatMap((row) => row.cells.filter((cell) => cell.selectable).map((cell) => cell.key)), [visibleRows])
  const allState: boolean | 'indeterminate' = !selectedCells.length ? false : selectedCells.length === allSelectable.length ? true : 'indeterminate'

  const onPointerDown = (event: ReactPointerEvent) => {
    suppressClick.current = false
    const point = pointFrom(event.target)
    if (!point || event.button !== 0) return
    if (event.shiftKey && canEdit) {
      event.preventDefault()
      suppressClick.current = true
      const origin = selectionAnchor.current ?? active ?? point
      setSelected((current) => toggleKeys(current, rectKeys(visibleRows, origin, point), true))
      setActive(point)
      return
    }
    if ((event.metaKey || event.ctrlKey) && canEdit) {
      event.preventDefault()
      suppressClick.current = true
      const cell = cellAt(point)
      if (cell?.selectable) setSelected((current) => toggleKeys(current, [cell.key], !current.has(cell.key)))
      selectionAnchor.current = point
      setActive(point)
      return
    }
    if (canEdit && event.pointerType === 'mouse') { event.preventDefault(); drag.current = { start: point, moved: false } }
  }

  const onPointerOver = (event: ReactPointerEvent) => {
    const state = drag.current
    if (!state || !(event.buttons & 1)) return
    const point = pointFrom(event.target)
    if (!point || (!state.moved && point.r === state.start.r && point.c === state.start.c)) return
    state.moved = true
    setEditor(null)
    setSelected(new Set(rectKeys(visibleRows, state.start, point)))
    selectionAnchor.current = state.start
    setActive(point)
  }

  useEffect(() => {
    const finish = () => { if (drag.current?.moved) suppressClick.current = true; drag.current = null }
    window.addEventListener('pointerup', finish)
    return () => window.removeEventListener('pointerup', finish)
  }, [])

  const onClick = (event: ReactMouseEvent) => {
    const point = pointFrom(event.target)
    if (suppressClick.current) { suppressClick.current = false; return }
    if (!point) return
    selectionAnchor.current = point
    setActive(point)
    ;(event.target as HTMLElement).closest<HTMLElement>('[data-cell]')?.focus({ preventScroll: true })
    setEditor(point)
  }

  const onKeyDown = (event: ReactKeyboardEvent) => {
    const point = pointFrom(event.target)
    if (!point) return
    const moves: Record<string, Point> = {
      ArrowUp: { r: point.r - 1, c: point.c }, ArrowDown: { r: point.r + 1, c: point.c }, ArrowLeft: { r: point.r, c: point.c - 1 }, ArrowRight: { r: point.r, c: point.c + 1 },
      Home: { r: event.ctrlKey ? 0 : point.r, c: 0 }, End: { r: event.ctrlKey ? visibleRows.length - 1 : point.r, c: dates.length - 1 },
      PageUp: { r: point.r - 10, c: point.c }, PageDown: { r: point.r + 10, c: point.c },
    }
    if (moves[event.key]) { event.preventDefault(); moveTo(moves[event.key], event.shiftKey); return }
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setActive(point); setEditor(point); return }
    if (event.key === 'Escape' && selected.size) { event.preventDefault(); setSelected(new Set()) }
  }

  const exportCsv = () => saveCompanyBlob(new Blob([buildCsv(visibleRows, dates)], { type: 'text/csv;charset=utf-8' }), `ирц-${mode === 'month' ? start.slice(0, 7) : `${start}_${end}`}.csv`)

  const editorCell = cellAt(editor)
  const editorAnchor = editor ? scrollRef.current?.querySelector<HTMLElement>(`[data-cell="${editor.r}:${editor.c}"]`) : null
  const count = selectedCells.length

  return <VStack gap={3}>
    <HStack gap={2} hAlign="between" vAlign="center" wrap="wrap">
      <VStack gap={0.5}>
        <Heading level={2}>Ирцийн бүртгэл</Heading>
        <Text type="supporting">{visibleRows.length} ажилтан{canEdit ? ` · ${unconfirmed} баталгаажаагүй ажлын өдөр` : ''}</Text>
      </VStack>
      <SegmentedControl label="Хугацааны харагдац" size="sm" value={mode} onChange={(value) => { const next = value === 'month' ? 'month' : 'week'; setMode(next); writePeriod(next) }}>
        <SegmentedControlItem value="week" label="7 хоног" />
        <SegmentedControlItem value="month" label="Сар" />
      </SegmentedControl>
    </HStack>

    <HStack gap={2} hAlign="between" vAlign="center" wrap="wrap">
      <HStack gap={1} vAlign="center">
        <Button label={mode === 'week' ? 'Өмнөх 7 хоног' : 'Өмнөх сар'} isIconOnly icon={<ChevronLeft size={16} />} size="sm" variant="ghost" onClick={() => setAnchorDate(shiftPeriod(mode, anchorDate, -1))} />
        <Text weight="semibold" hasTabularNumbers>{periodLabel(mode, start, end)}</Text>
        <Button label={mode === 'week' ? 'Дараагийн 7 хоног' : 'Дараагийн сар'} isIconOnly icon={<ChevronRight size={16} />} size="sm" variant="ghost" onClick={() => setAnchorDate(shiftPeriod(mode, anchorDate, 1))} />
        <Button label={mode === 'week' ? 'Энэ 7 хоног' : 'Энэ сар'} size="sm" isDisabled={today >= start && today <= end} onClick={() => setAnchorDate(today)} />
      </HStack>
      <HStack gap={2} vAlign="center" wrap="wrap">
        <TextInput label="Ажилтан хайх" isLabelHidden size="sm" placeholder="Нэр эсвэл ID…" value={searchInput} onChange={setSearchInput} hasClear width={220} />
        <Selector label="Алба/нэгж" isLabelHidden size="sm" options={departments} value={department} onChange={(value) => setDepartment(value ?? ALL_DEPARTMENTS)} width={200} />
        <Button label="CSV" size="sm" icon={<Download size={14} />} isDisabled={!visibleRows.length} onClick={exportCsv} tooltip="Шүүсэн жагсаалтыг татах" />
      </HStack>
    </HStack>

    {canEdit && <HStack gap={2} vAlign="center" wrap="wrap">
      <Button label="Сонгосныг ирсэн болгох" size="sm" variant="primary" icon={<Check size={14} />} isDisabled={!count || busy} endContent={count ? <Badge label={count} /> : undefined} clickAction={() => batch('present')} />
      <Button label="Сонгосныг remote болгох" size="sm" icon={<Laptop size={14} />} isDisabled={!count || busy} endContent={count ? <Badge label={count} /> : undefined} clickAction={() => batch('remote')} />
      {count > 0 && <Button label="Сонголтыг цуцлах" size="sm" variant="ghost" onClick={() => setSelected(new Set())} />}
      <Text type="supporting">Shift/Ctrl + товших эсвэл чирч олон нүд сонгоно</Text>
    </HStack>}

    {attendance.isError ? <Banner status="error" title="Ирцийн мэдээлэл ачаалж чадсангүй" description="Сүлжээ эсвэл эрхээ шалгаад дахин оролдоно уу." collapsible={false} />
      : attendance.isLoading ? <Skeleton height={320} />
      : !visibleRows.length ? <EmptyState title="Ажилтан олдсонгүй" description={rows.length ? 'Хайлт эсвэл алба/нэгжийн шүүлтүүрийг өөрчилнө үү.' : 'Энэ хугацаанд ирц бүртгэх ажилтан алга.'} isCompact />
      : <div ref={scrollRef} className={`att-scroll${attendance.isFetching ? ' is-fetching' : ''}`} onScroll={onScroll}>
        <table className={`att-grid att-grid--${mode}`} role="grid" aria-label={`Ирц · ${periodLabel(mode, start, end)}`} aria-rowcount={visibleRows.length + 1} aria-colcount={dates.length + 1} aria-multiselectable={canEdit || undefined}>
          <colgroup><col className="att-col-name" />{dates.map((date) => <col key={date} className="att-col-day" />)}</colgroup>
          <thead ref={headRef}>
            <tr role="row" aria-rowindex={1}>
              <th role="columnheader" scope="col" className="att-sticky att-corner"><span className="att-name-inner">
                <span className="att-row-index">#</span>
                {canEdit && <span className="att-row-check"><CheckboxInput label="Харагдаж буй бүх ажлын өдрийг сонгох" isLabelHidden size="sm" value={allState} isDisabled={!allSelectable.length} onChange={(checked) => setSelected(checked ? new Set(allSelectable) : new Set())} /></span>}
                <span className="att-person"><strong>Нэр</strong></span>
              </span></th>
              {dates.map((date, c) => <th key={date} role="columnheader" scope="col" className={['att-day-head', offCols[c] && 'is-weekend', c === todayCol && 'is-today'].filter(Boolean).join(' ')} title={holidayCols[c] ?? undefined}>
                <span>{WEEKDAYS[weekdayIndex(date)]}</span><strong>{Number(date.slice(8))}</strong>
              </th>)}
            </tr>
          </thead>
          <tbody onPointerDown={onPointerDown} onPointerOver={onPointerOver} onClick={onClick} onKeyDown={onKeyDown}>
            {virtual && firstRow > 0 && <tr aria-hidden="true" className="att-spacer" style={{ height: firstRow * rowHeight }} />}
            {visibleRows.slice(firstRow, lastRow).map((row, index) => <Row key={row.employeeId} row={row} r={firstRow + index} selected={selected} active={active} canEdit={canEdit} compact={compact} weekendCols={offCols} todayCol={todayCol} onToggleRow={toggleRow} />)}
            {virtual && lastRow < visibleRows.length && <tr aria-hidden="true" className="att-spacer" style={{ height: (visibleRows.length - lastRow) * rowHeight }} />}
          </tbody>
        </table>
      </div>}

    <Legend />
    {editor && editorCell && editorAnchor && <CellEditor cell={editorCell} rowName={visibleRows[editor.r].name} anchor={editorAnchor} canEdit={canEdit} onPick={pickStatus} onReset={resetCell} onClose={closeEditor} onOpenLeave={onOpenLeave} />}
  </VStack>
}

export default AttendanceGrid
