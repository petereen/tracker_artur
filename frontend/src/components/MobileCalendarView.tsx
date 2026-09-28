import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { ChevronDown, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, EllipsisVertical, ListFilter, Plus, Zap } from 'lucide-react'

export type MobileCalendarViewMode = 'month' | 'week' | 'day'

const VIEW_STORAGE_KEY = 'oyuns-mobile-calendar-view'
const HOUR_HEIGHT = 52
const WEEKDAYS = ['Да', 'Мя', 'Лх', 'Пү', 'Ба', 'Бя', 'Ня']
const VIEW_LABELS: Record<MobileCalendarViewMode, string> = { month: 'Сар', week: '7 хоног', day: 'Өдөр' }
const TIMED_KINDS = new Set(['task', 'event', 'reminder', 'time_block'])

function localDate(value: Date) { const offset = value.getTimezoneOffset() * 60_000; return new Date(value.getTime() - offset).toISOString().slice(0, 10) }
function addDays(value: Date, amount: number) { const next = new Date(value); next.setDate(next.getDate() + amount); return next }
function startOfWeek(value: Date) { const start = new Date(value.getFullYear(), value.getMonth(), value.getDate()); return addDays(start, -((start.getDay() + 6) % 7)) }
function monthGrid(value: Date) { const first = startOfWeek(new Date(value.getFullYear(), value.getMonth(), 1)); return Array.from({ length: 42 }, (_, index) => addDays(first, index)) }
function shiftMonth(value: Date, amount: number) { const target = new Date(value.getFullYear(), value.getMonth() + amount, 1); const lastDay = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate(); target.setDate(Math.min(value.getDate(), lastDay)); return target }
function itemKey(item: any) { return `${item.kind}-${item.id ?? item.project_id ?? item.plan_id ?? item.title}` }
function hourLabel(hour: number) { return `${String(hour).padStart(2, '0')}:00` }
function timeLabel(value: Date) { return `${String(value.getHours()).padStart(2, '0')}:${String(value.getMinutes()).padStart(2, '0')}` }

function readStoredView(): MobileCalendarViewMode {
  try {
    const saved = window.localStorage.getItem(VIEW_STORAGE_KEY)
    return saved === 'week' || saved === 'day' ? saved : 'month'
  } catch {
    return 'month'
  }
}

/** Same-day items with a real start time go on the hour grid; everything else is an all-day chip. */
function timedSpan(item: any) {
  if (!TIMED_KINDS.has(item.kind)) return null
  const startValue = item.start_at || item.starts_at
  const endValue = item.kind === 'task' ? item.deadline_at : item.ends_at
  if (typeof startValue !== 'string' || !startValue.includes('T')) return null
  const start = new Date(startValue)
  if (Number.isNaN(start.getTime())) return null
  let end = typeof endValue === 'string' && endValue.includes('T') ? new Date(endValue) : new Date(start.getTime() + 30 * 60_000)
  if (Number.isNaN(end.getTime()) || end <= start) end = new Date(start.getTime() + 30 * 60_000)
  if (end.getTime() - start.getTime() >= 23 * 3_600_000 || localDate(start) !== localDate(new Date(end.getTime() - 1))) return null
  return { start, end }
}

type TimedBlock = { item: any; start: Date; end: Date; top: number; height: number; column: number; columns: number }

function layoutTimed(items: any[]): TimedBlock[] {
  const spans = items.flatMap((item) => { const span = timedSpan(item); return span ? [{ item, ...span }] : [] }).sort((a, b) => a.start.getTime() - b.start.getTime() || b.end.getTime() - a.end.getTime())
  const blocks: TimedBlock[] = []
  let cluster: TimedBlock[] = []
  let columnEnds: number[] = []
  let clusterEnd = 0
  const closeCluster = () => { cluster.forEach((block) => { block.columns = columnEnds.length }); cluster = []; columnEnds = [] }
  spans.forEach(({ item, start, end }) => {
    if (cluster.length && start.getTime() >= clusterEnd) closeCluster()
    let column = columnEnds.findIndex((columnEnd) => columnEnd <= start.getTime())
    if (column < 0) { column = columnEnds.length; columnEnds.push(end.getTime()) } else columnEnds[column] = end.getTime()
    clusterEnd = Math.max(cluster.length ? clusterEnd : 0, end.getTime())
    const minutes = start.getHours() * 60 + start.getMinutes()
    const block = { item, start, end, top: (minutes / 60) * HOUR_HEIGHT, height: Math.max(22, ((end.getTime() - start.getTime()) / 3_600_000) * HOUR_HEIGHT - 2), column, columns: 1 }
    cluster.push(block); blocks.push(block)
  })
  closeCluster()
  return blocks
}

function useNow() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => { const timer = window.setInterval(() => setNow(new Date()), 60_000); return () => window.clearInterval(timer) }, [])
  return now
}

type MobileCalendarViewProps = {
  itemsByDate: Map<string, any[]>
  holidayKeys: Set<string>
  onSelectItem: (item: any) => void
  onCreate: (day: Date, hour?: number) => void
  onMonthChange: (month: Date) => void
  filters: ReactNode
  menu: ReactNode
}

export function MobileCalendarView({ itemsByDate, holidayKeys, onSelectItem, onCreate, onMonthChange, filters, menu }: MobileCalendarViewProps) {
  const [view, setView] = useState<MobileCalendarViewMode>(readStoredView)
  const [focus, setFocus] = useState(() => new Date())
  const [popover, setPopover] = useState<'filters' | 'menu' | null>(null)
  const now = useNow()
  const todayKey = localDate(now)
  const focusMonth = `${focus.getFullYear()}-${focus.getMonth()}`

  useEffect(() => { try { window.localStorage.setItem(VIEW_STORAGE_KEY, view) } catch { /* per-viewer convenience only */ } }, [view])
  // The page loads events around its month anchor, so follow the month being viewed.
  useEffect(() => { onMonthChange(new Date(focus.getFullYear(), focus.getMonth(), 1)) }, [focusMonth]) // eslint-disable-line react-hooks/exhaustive-deps

  const days = useMemo(() => view === 'month' ? monthGrid(focus) : view === 'week' ? Array.from({ length: 7 }, (_, index) => addDays(startOfWeek(focus), index)) : [new Date(focus.getFullYear(), focus.getMonth(), focus.getDate())], [focus, view])
  const visibleDays = view === 'month' ? days.filter((day) => day.getMonth() === focus.getMonth()) : days
  const hasItems = visibleDays.some((day) => (itemsByDate.get(localDate(day))?.length ?? 0) > 0)
  const isRedDay = (day: Date) => day.getDay() === 0 || day.getDay() === 6 || holidayKeys.has(localDate(day))

  const step = (direction: 1 | -1, big = false) => setFocus((current) => view === 'month' || big ? shiftMonth(current, direction) : addDays(current, direction * (view === 'week' ? 7 : 1)))
  const title = view === 'month'
    ? focus.toLocaleDateString('mn-MN', { year: 'numeric', month: 'long' })
    : view === 'day'
      ? focus.toLocaleDateString('mn-MN', { month: 'long', day: 'numeric', weekday: 'short' })
      : days[0].getMonth() === days[6].getMonth()
        ? `${days[0].getMonth() + 1}-р сарын ${days[0].getDate()}–${days[6].getDate()}`
        : `${days[0].getMonth() + 1}/${days[0].getDate()} – ${days[6].getMonth() + 1}/${days[6].getDate()}`
  const openDay = (day: Date) => { setFocus(day); setView('day') }

  return <section className={`mobile-calendar mcal mcal-${view}`} aria-label="Гар утасны календарь">
    <header className="mcal-header">
      <div className="mcal-nav">
        {view === 'week' && <button type="button" className="mcal-icon-button" onClick={() => step(-1, true)} aria-label="Өмнөх сар"><ChevronsLeft size={18} /></button>}
        <button type="button" className="mcal-icon-button" onClick={() => step(-1)} aria-label="Өмнөх"><ChevronLeft size={20} /></button>
        <h2 className="mcal-title" aria-live="polite">{title}</h2>
        <button type="button" className="mcal-icon-button" onClick={() => step(1)} aria-label="Дараах"><ChevronRight size={20} /></button>
        {view === 'week' && <button type="button" className="mcal-icon-button" onClick={() => step(1, true)} aria-label="Дараагийн сар"><ChevronsRight size={18} /></button>}
      </div>
      <button type="button" className="mcal-today" onClick={() => setFocus(new Date())}>Өнөөдөр</button>
    </header>
    <div className="mcal-controls">
      <label className="mcal-view-select"><span className="sr-only">Харагдац</span><select value={view} onChange={(event) => setView(event.target.value as MobileCalendarViewMode)}>{(Object.keys(VIEW_LABELS) as MobileCalendarViewMode[]).map((mode) => <option key={mode} value={mode}>{VIEW_LABELS[mode]}</option>)}</select><ChevronDown size={16} aria-hidden /></label>
      <button type="button" className={`mcal-square-button ${popover === 'filters' ? 'active' : ''}`} onClick={() => setPopover((current) => current === 'filters' ? null : 'filters')} aria-expanded={popover === 'filters'} aria-label="Төрлөөр шүүх"><ListFilter size={18} /></button>
      <button type="button" className={`mcal-square-button ${popover === 'menu' ? 'active' : ''}`} onClick={() => setPopover((current) => current === 'menu' ? null : 'menu')} aria-expanded={popover === 'menu'} aria-label="Бусад тохиргоо"><EllipsisVertical size={18} /></button>
      {popover && <>
        <div className="mcal-popover-scrim" onClick={() => setPopover(null)} aria-hidden />
        <div className="mcal-popover" role="dialog" aria-label={popover === 'filters' ? 'Төрлөөр шүүх' : 'Бусад тохиргоо'}>{popover === 'filters' ? filters : menu}</div>
      </>}
    </div>
    <div className="mcal-body">
      {view === 'month'
        ? <MonthGrid days={days} focus={focus} todayKey={todayKey} itemsByDate={itemsByDate} isRedDay={isRedDay} onOpenDay={openDay} />
        : <TimeGrid days={days} now={now} todayKey={todayKey} itemsByDate={itemsByDate} isRedDay={isRedDay} onSelectItem={onSelectItem} onCreate={onCreate} onOpenDay={openDay} scrollKey={`${view}-${localDate(days[0])}`} />}
      {!hasItems && <p className="mcal-empty">Энэ хугацаанд үйл явдал алга.</p>}
    </div>
    {createPortal(<button type="button" className="mcal-fab" onClick={() => onCreate(focus)} aria-label="Шинээр үүсгэх"><Plus size={26} /></button>, document.body)}
  </section>
}

function MonthGrid({ days, focus, todayKey, itemsByDate, isRedDay, onOpenDay }: { days: Date[]; focus: Date; todayKey: string; itemsByDate: Map<string, any[]>; isRedDay: (day: Date) => boolean; onOpenDay: (day: Date) => void }) {
  return <div className="mcal-month">
    <div className="mcal-month-weekdays">{WEEKDAYS.map((label, index) => <span key={label} className={index >= 5 ? 'red-day' : ''}>{label}</span>)}</div>
    <div className="mcal-month-grid">{days.map((day) => {
      const key = localDate(day)
      const items = itemsByDate.get(key) ?? []
      return <button type="button" key={key} className={`mcal-month-cell ${day.getMonth() !== focus.getMonth() ? 'outside' : ''} ${key === todayKey ? 'today' : ''} ${isRedDay(day) ? 'red-day' : ''}`} onClick={() => onOpenDay(day)} aria-label={`${day.toLocaleDateString('mn-MN', { month: 'long', day: 'numeric', weekday: 'long' })}, ${items.length} зүйл`}>
        <strong>{day.getDate()}</strong>
        {items.slice(0, 2).map((item) => <span key={itemKey(item)} className={`mcal-chip calendar-item ${item.kind}`}>{item.title}</span>)}
        {items.length > 2 && <small className="mcal-more">+{items.length - 2}</small>}
      </button>
    })}</div>
  </div>
}

function TimeGrid({ days, now, todayKey, itemsByDate, isRedDay, onSelectItem, onCreate, onOpenDay, scrollKey }: { days: Date[]; now: Date; todayKey: string; itemsByDate: Map<string, any[]>; isRedDay: (day: Date) => boolean; onSelectItem: (item: any) => void; onCreate: (day: Date, hour?: number) => void; onOpenDay: (day: Date) => void; scrollKey: string }) {
  const scrollerRef = useRef<HTMLDivElement>(null)
  const columns = useMemo(() => days.map((day) => {
    const items = itemsByDate.get(localDate(day)) ?? []
    const timed = layoutTimed(items)
    const timedItems = new Set(timed.map((block) => block.item))
    return { day, key: localDate(day), timed, allDay: items.filter((item) => !timedItems.has(item)) }
  }), [days, itemsByDate])
  const todayIndex = columns.findIndex((column) => column.key === todayKey)

  useLayoutEffect(() => {
    const scroller = scrollerRef.current
    if (!scroller) return
    const targetHour = todayIndex >= 0 ? Math.max(0, now.getHours() - 2) : 8
    scroller.scrollTop = targetHour * HOUR_HEIGHT
    if (todayIndex > 0 && days.length > 1) {
      const column = scroller.querySelector<HTMLElement>(`[data-day-index="${todayIndex}"]`)
      if (column) scroller.scrollLeft = Math.max(0, column.offsetLeft - 52)
    } else scroller.scrollLeft = 0
  }, [scrollKey]) // eslint-disable-line react-hooks/exhaustive-deps

  const createAt = (event: React.MouseEvent<HTMLDivElement>, day: Date) => {
    const hour = Math.min(23, Math.max(0, Math.floor((event.clientY - event.currentTarget.getBoundingClientRect().top) / HOUR_HEIGHT)))
    onCreate(day, hour)
  }
  const nowTop = ((now.getHours() * 60 + now.getMinutes()) / 60) * HOUR_HEIGHT

  return <div className="mcal-time-scroller" ref={scrollerRef} data-no-pull-refresh>
    <div className="mcal-time-grid" style={{ '--mcal-days': days.length, '--mcal-hour': `${HOUR_HEIGHT}px` } as React.CSSProperties}>
      <div className="mcal-corner" aria-hidden><Zap size={16} /></div>
      {columns.map(({ day, key, allDay }, index) => <div key={key} className={`mcal-day-head ${key === todayKey ? 'today' : ''} ${isRedDay(day) ? 'red-day' : ''}`} data-day-index={index}>
        <button type="button" className="mcal-day-label" onClick={() => onOpenDay(day)} aria-label={day.toLocaleDateString('mn-MN', { month: 'long', day: 'numeric', weekday: 'long' })}><span>{WEEKDAYS[(day.getDay() + 6) % 7]}</span><strong>{day.getDate()}</strong></button>
        {allDay.length > 0 && <div className="mcal-all-day">{allDay.slice(0, 3).map((item) => <button type="button" key={itemKey(item)} className={`mcal-chip calendar-item ${item.kind}`} onClick={() => onSelectItem(item)} title={item.title}>{item.title}</button>)}{allDay.length > 3 && <button type="button" className="mcal-more" onClick={() => onOpenDay(day)}>+{allDay.length - 3}</button>}</div>}
      </div>)}
      <div className="mcal-hours" aria-hidden>{Array.from({ length: 24 }, (_, hour) => <div key={hour}><span>{hourLabel(hour)}</span><small>:30</small></div>)}</div>
      {columns.map(({ day, key, timed }) => <div key={key} className={`mcal-day-column ${key === todayKey ? 'today' : ''}`} onClick={(event) => createAt(event, day)}>
        {timed.map((block) => <button type="button" key={itemKey(block.item)} className={`mcal-event calendar-item ${block.item.kind}`} style={{ top: block.top, height: block.height, left: `calc(${(block.column / block.columns) * 100}% + 2px)`, width: `calc(${100 / block.columns}% - 4px)` }} onClick={(event) => { event.stopPropagation(); onSelectItem(block.item) }}>
          <strong>{block.item.title}</strong>
          {block.height >= 36 && <small>{timeLabel(block.start)} – {timeLabel(block.end)}</small>}
        </button>)}
        {key === todayKey && <div className="mcal-now" style={{ top: nowTop }} aria-hidden />}
      </div>)}
    </div>
  </div>
}
