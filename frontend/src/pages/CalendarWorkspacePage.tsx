import { useTranslation } from 'react-i18next'
import { useEffect, useMemo, useRef, useState, useTransition, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'motion/react'
import { CalendarDays, ChevronDown, ChevronLeft, ChevronRight, ExternalLink, LoaderCircle, MapPin, Plus, RefreshCw, Trash2, Unplug, UserRound, Users, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { isNativePlatform } from '../platform/runtime'
import { useCalendarEvents, useCreateCalendarEntry, useCreateEnterpriseTask, useDeleteCalendarEntry, useDeleteEnterpriseTask, useGoogleCalendarConnect, useGoogleCalendarDisconnect, useGoogleCalendarList, useGoogleCalendarSelect, useGoogleCalendarStatus, useGoogleCalendarSync, useUpdateCalendarEntry, useUpdateEnterpriseTask, useWorkerDirectory } from '../api/enterprise'
import { EMPTY_ROLES, useAuthStore } from '../store/auth'
import { CalendarSkeleton, QueryRegion, toQueryRegionState } from '../components/Loading'
import { useWorkspaceMode } from '../components/WorkspaceModeProvider'
import { MobileCalendarView } from '../components/MobileCalendarView'
import { CreateButton } from '../components/CreateButton'
import { Button } from '@astryxdesign/core/Button'
import { IconButton } from '@astryxdesign/core/IconButton'
import i18n from '../i18n'
import { intlLocale } from '../utils/locale'

function localDate(value: Date) { const offset = value.getTimezoneOffset() * 60_000; return new Date(value.getTime() - offset).toISOString().slice(0, 10) }
function calendarDate(value: unknown) {
  if (typeof value !== 'string' || !value) return null
  // Date-only values must not be passed through Date.parse: midnight UTC can
  // move them to the previous local day in Ulaanbaatar and similar zones.
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? null : localDate(parsed)
}
function dateRange(start: string | null, end: string | null) {
  const first = calendarDate(start)
  const last = calendarDate(end) || first
  if (!first || !last) return []
  const from = new Date(`${first}T00:00:00`)
  const to = new Date(`${last}T00:00:00`)
  if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime()) || to < from) return [first]
  const dates: string[] = []
  for (const day = new Date(from); day <= to; day.setDate(day.getDate() + 1)) dates.push(localDate(day))
  return dates
}
function itemDates(item: any) {
  // Holidays and birthdays are represented as all-day intervals whose end is
  // exclusive (for example, Jan 8 00:00 -> Jan 9 00:00). The end belongs to
  // the next interval, so it must not become a second visible calendar day.
  if (item.kind === 'holiday' || item.kind === 'birthday') {
    const start = calendarDate(item.holiday_date || item.starts_at || item.start_at)
    return start ? [start] : []
  }
  const start = item.start_at || item.starts_at || item.starts_on || item.plan_month || item.deadline_at || item.ends_at || item.due_date
  const end = item.kind === 'task' ? item.deadline_at : (item.ends_at || item.ends_on || item.due_date || item.deadline_at || item.start_at || item.starts_at || item.starts_on || item.plan_month)
  return dateRange(start, end)
}
function uniqueCalendarItems(items: any[]) {
  const seen = new Set<string>()
  return items.filter((item) => {
    const key = item.kind === 'holiday' || item.kind === 'birthday'
      ? [item.kind, item.title, item.holiday_date || item.starts_at || item.start_at].join('|')
      : [item.kind, item.id, item.title, item.start_at || item.starts_at || item.holiday_date, item.ends_at || item.deadline_at || ''].join('|')
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}
function calendarItemSubtitle(item: any) {
  return item.kind === 'task' ? item.primary_owner_name || i18n.t('calendar.type.task') : item.kind === 'project' ? i18n.t('calendar.projectSub', { code: item.code || '' }) : item.kind === 'plan' ? i18n.t('calendar.planSub', { horizon: item.horizon || '' }) : item.kind === 'holiday' ? i18n.t('calendar.holiday') : item.kind === 'birthday' ? i18n.t('calendar.birthday') : item.visibility === 'company' ? i18n.t('calendar.companyEvent') : item.kind === 'reminder' ? i18n.t('calendar.type.reminder') : i18n.t('calendar.personalEvent')
}
type CalendarFilterKey = 'event' | 'plan' | 'task' | 'reminder'
// `label` is a getter so it follows the UI language when read at render time.
const CALENDAR_FILTERS: Array<{ key: CalendarFilterKey; readonly label: string }> = (['event', 'plan', 'task', 'reminder'] as const).map((key) => ({
  key,
  get label() { return i18n.t(`calendar.type.${key}`) },
}))
const CALENDAR_FILTER_STORAGE_KEY = 'oyuns-calendar-type-filters'

function calendarFilterKey(item: any): CalendarFilterKey | null {
  if (item.kind === 'project' || item.kind === 'plan') return 'plan'
  if (item.kind === 'task' || item.kind === 'event' || item.kind === 'reminder') return item.kind
  return null
}
function monthGridDays(anchor: Date) {
  const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1)
  first.setDate(first.getDate() - ((first.getDay() + 6) % 7))
  return Array.from({ length: 42 }, (_, index) => {
    const day = new Date(first)
    day.setDate(day.getDate() + index)
    return day
  })
}
function availabilityItemTime(item: any) {
  const value = item.start_at || item.starts_at || item.starts_on || item.plan_month || item.deadline_at || item.due_date
  if (typeof value !== 'string' || /^\d{4}-\d{2}-\d{2}$/.test(value)) return i18n.t('calendar.allDay')
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? i18n.t('calendar.allDay') : parsed.toLocaleTimeString(intlLocale(), { hour: '2-digit', minute: '2-digit' })
}
function availabilityTypeLabel(item: any) {
  return item.kind === 'task' ? i18n.t('calendar.type.task') : item.kind === 'plan' ? i18n.t('calendar.type.plan') : item.kind === 'reminder' ? i18n.t('calendar.type.reminder') : i18n.t('calendar.type.event')
}

function SheetPortal({ children }: { children: ReactNode }) {
  return createPortal(children, document.body)
}

function WorkerAvailabilityPopover({ worker, scope, onClose }: { worker: { id: number; name: string; job_title?: string | null }; scope: 'private' | 'corporate'; onClose: () => void }) {
  const { t } = useTranslation()
  const [anchor, setAnchor] = useState(() => new Date())
  const [previewDate, setPreviewDate] = useState(() => localDate(new Date()))
  const [closing, setClosing] = useState(false)
  const popoverRef = useRef<HTMLDivElement>(null)
  const closePopover = () => {
    if (closing) return
    setClosing(true)
    window.setTimeout(onClose, 160)
  }
  const events = useCalendarEvents(scope, anchor, worker.id)
  const days = useMemo(() => monthGridDays(anchor), [anchor])
  const items = useMemo(() => uniqueCalendarItems([
    ...(events.data?.tasks ?? []),
    ...(events.data?.plans ?? []),
    ...(events.data?.entries ?? []),
  ]).filter((item: any) => ['task', 'plan', 'event', 'reminder'].includes(item.kind)), [events.data])
  const itemsByDate = useMemo(() => {
    const result = new Map<string, any[]>()
    items.forEach((item) => itemDates(item).forEach((date) => result.set(date, [...(result.get(date) ?? []), item])))
    return result
  }, [items])
  const previewItems = itemsByDate.get(previewDate) ?? []
  useEffect(() => {
    const handleOutsidePointer = (event: PointerEvent) => {
      if (!popoverRef.current?.contains(event.target as Node)) closePopover()
    }
    document.addEventListener('pointerdown', handleOutsidePointer)
    return () => document.removeEventListener('pointerdown', handleOutsidePointer)
  }, [closing, onClose])
  useEffect(() => {
    const inMonth = days.some((day) => localDate(day) === previewDate && day.getMonth() === anchor.getMonth())
    if (inMonth && itemsByDate.has(previewDate)) return
    const firstBusy = days.map(localDate).find((date) => itemsByDate.has(date))
    setPreviewDate(firstBusy ?? localDate(new Date(anchor.getFullYear(), anchor.getMonth(), 1)))
  }, [anchor, days, itemsByDate, previewDate])
  const monthTitle = anchor.toLocaleDateString(intlLocale(), { month: 'long', year: 'numeric' })
  return <motion.div ref={popoverRef} className="calendar-availability-popover" role="dialog" aria-label={t('calendar.workerSchedule', { name: worker.name })} onPointerDown={(event) => event.stopPropagation()} initial={{ opacity: 0, y: -4, scale: .97 }} animate={closing ? { opacity: 0, y: -4, scale: .97 } : { opacity: 1, y: 0, scale: 1 }} transition={{ duration: .16, ease: [0.22, 1, 0.36, 1] }}>
    <header className="calendar-availability-header"><div><strong>{worker.name}</strong><small>{worker.job_title || t('calendar.employee')} · {t('calendar.scheduleCount', { n: items.length })}</small></div><button type="button" className="calendar-availability-close" onClick={closePopover} aria-label={t('calendar.availability.close')}><X size={14} /></button></header>
    <div className="calendar-availability-month"><button type="button" onClick={() => setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() - 1, 1))} aria-label={t('calendar.prevMonth')}><ChevronLeft size={15} /></button><strong>{monthTitle}</strong><button type="button" onClick={() => setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() + 1, 1))} aria-label={t('calendar.nextMonth')}><ChevronRight size={15} /></button></div>
    <div className="calendar-availability-weekdays">{(['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const).map((day) => <span key={day}>{t(`calendar.weekdayInitial.${day}`)}</span>)}</div>
    <div className="calendar-availability-grid">{days.map((day) => {
      const key = localDate(day)
      const dayItems = itemsByDate.get(key) ?? []
      const selected = key === previewDate
      return <button type="button" key={key} className={`calendar-availability-day ${day.getMonth() !== anchor.getMonth() ? 'outside' : ''} ${selected ? 'selected' : ''} ${dayItems.length ? 'busy' : ''}`} onMouseEnter={() => setPreviewDate(key)} onFocus={() => setPreviewDate(key)} onClick={() => setPreviewDate(key)} title={dayItems.length ? dayItems.map((item) => item.title).join(', ') : undefined} aria-label={t('calendar.dayItems', { date: key, n: dayItems.length })}><span>{day.getDate()}</span>{dayItems.length > 0 && <i aria-hidden>{dayItems.slice(0, 3).map((item, index) => <b className={item.kind} key={`${item.kind}-${index}`} />)}</i>}</button>
    })}</div>
    <div className="calendar-availability-preview"><small>{new Date(`${previewDate}T12:00:00`).toLocaleDateString(intlLocale(), { month: 'long', day: 'numeric', weekday: 'long' })}</small>{events.isLoading ? <p>{t('common.loading')}</p> : previewItems.length ? <ul>{previewItems.slice(0, 4).map((item) => <li key={`${item.kind}-${item.id || item.plan_id}`}><span className={`availability-dot ${item.kind}`} /><span><strong>{item.title}</strong><small>{availabilityTypeLabel(item)} · {availabilityItemTime(item)}</small></span></li>)}{previewItems.length > 4 && <li className="availability-more">{t('calendar.moreSchedule', { n: previewItems.length - 4 })}</li>}</ul> : <p>{t('calendar.availability.empty')}</p>}</div>
  </motion.div>
}
// Month grid geometry (px). The same values drive the CSS lanes through
// custom properties, so bars and row heights never drift apart.
const CALENDAR_DAY_HEAD = 38
const CALENDAR_LANE = 26
const CALENDAR_ROW_PAD = 8
const CALENDAR_ROW_MIN = 128
const CALENDAR_GRID_VARS = { '--calendar-day-head': `${CALENDAR_DAY_HEAD}px`, '--calendar-lane': `${CALENDAR_LANE}px` } as React.CSSProperties

/** Start time of a timed event/reminder; all-day and date-only items have none. */
function calendarItemTime(item: any) {
  if (item.kind !== 'event' && item.kind !== 'reminder') return null
  const value = item.starts_at || item.start_at
  if (typeof value !== 'string' || /^\d{4}-\d{2}-\d{2}$/.test(value)) return null
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? null : parsed.toLocaleTimeString(intlLocale(), { hour: '2-digit', minute: '2-digit' })
}
type CalendarRangeSegment = { item: any; key: string; start: number; end: number; first: boolean; last: boolean; lane: number; week: number }
type CalendarRangeLayout = { segments: CalendarRangeSegment[]; weekLanes: number[] }

function calendarRangeSegments(items: any[], days: Date[]): CalendarRangeLayout {
  const dayIndexes = new Map(days.map((day, index) => [localDate(day), index]))
  const byWeek = Array.from({ length: 6 }, () => [] as Array<Omit<CalendarRangeSegment, 'week'>>)
  items.forEach((item) => {
    const dates = itemDates(item)
    const visibleIndexes = [...new Set(dates.map((date) => dayIndexes.get(date)).filter((index): index is number => index !== undefined))].sort((left, right) => left - right)
    if (!visibleIndexes.length) return
    const key = [item.kind || 'item', item.id || item.project_id || item.plan_id || item.title, dates[0], dates[dates.length - 1]].join('|')
    let segmentStart = visibleIndexes[0]
    let previous = visibleIndexes[0]
    const addSegment = (start: number, end: number) => {
      const week = Math.floor(start / 7)
      if (!byWeek[week]) return
      byWeek[week].push({ item, key, start: start % 7, end: end % 7, first: dates[0] === localDate(days[start]), last: dates[dates.length - 1] === localDate(days[end]), lane: 0 })
    }
    visibleIndexes.slice(1).forEach((index) => {
      if (index % 7 === 0 || index !== previous + 1) { addSegment(segmentStart, previous); segmentStart = index }
      previous = index
    })
    addSegment(segmentStart, previous)
  })

  const weekLanes = Array.from({ length: 6 }, () => 0)
  let previousWeekLanes = new Map<string, number>()
  const segments = byWeek.flatMap((weekSegments, week) => {
    const laneEnds: number[] = []
    const nextWeekLanes = new Map<string, number>()
    const placed = weekSegments.sort((left, right) => left.start - right.start || right.end - left.end || left.key.localeCompare(right.key)).map((segment) => {
      const preferredLane = previousWeekLanes.get(segment.key)
      let lane = preferredLane !== undefined && (laneEnds[preferredLane] ?? -1) < segment.start ? preferredLane : laneEnds.findIndex((end) => (end ?? -1) < segment.start)
      if (lane === -1) lane = laneEnds.length
      segment.lane = lane
      laneEnds[lane] = segment.end
      nextWeekLanes.set(segment.key, lane)
      return { ...segment, week }
    })
    weekLanes[week] = laneEnds.length
    previousWeekLanes = nextWeekLanes
    return placed
  })
  return { segments, weekLanes }
}

function formatLastSynced(value?: string | null) {
  if (!value) return i18n.t('calendar.sync.never')
  const minutes = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 60000))
  return minutes < 1 ? i18n.t('calendar.sync.justNow') : i18n.t('calendar.syncedMinutes', { n: minutes })
}

export function GoogleCalendarSyncControl() {
  const { t } = useTranslation()
  const status = useGoogleCalendarStatus()
  const connect = useGoogleCalendarConnect()
  const sync = useGoogleCalendarSync()
  const disconnect = useGoogleCalendarDisconnect()
  const calendarList = useGoogleCalendarList(Boolean(status.data?.status === 'active'))
  const selectCalendar = useGoogleCalendarSelect()
  const [manageOpen, setManageOpen] = useState(false)

  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.origin !== window.location.origin || event.data?.source !== 'oyuns-google-calendar') return
      if (event.data.status === 'connected') {
        toast.success(t('calendar.google.connected'))
        status.refetch()
      } else toast.error(t('calendar.google.connectFailed'))
    }
    window.addEventListener('message', receive)
    return () => window.removeEventListener('message', receive)
  }, [status])

  const openConnect = async () => {
    if (isNativePlatform()) {
      toast.error(t('calendar.google.webOnly'))
      return
    }
    try {
      const result = await connect.mutateAsync()
      if (!result.authorization_url) {
        toast.error(t('calendar.google.oauthMissing'))
        return
      }
      const popup = window.open(result.authorization_url, 'oyuns-google-calendar', 'popup,width=560,height=720,resizable=yes,scrollbars=yes')
      if (!popup) window.location.assign(result.authorization_url)
      else popup.focus()
    } catch (error: any) {
      toast.error(error.response?.data?.detail || t('calendar.google.notConnected'))
    }
  }

  if (status.isLoading) return <button className="google-calendar-sync-control disconnected" disabled><LoaderCircle size={15} className="spin" />Google Calendar</button>
  if (status.data?.status !== 'active') return <button className="google-calendar-sync-control disconnected" onClick={openConnect} disabled={connect.isPending}><span className="google-calendar-mark" aria-hidden="true">31</span>{connect.isPending ? t('calendar.google.connecting') : t('calendar.google.connect')}</button>
  if (sync.isPending) return <button className="google-calendar-sync-control syncing" disabled><LoaderCircle size={15} className="spin" />{t('calendar.google.syncing')}</button>

  return <div className="google-calendar-sync-wrap">
    <div className="google-calendar-sync-control connected"><span className="google-calendar-mark" aria-hidden="true">31</span><span className="google-calendar-sync-copy"><strong><span className="google-calendar-status-dot" />{t('calendar.google.connectedLabel')}</strong><small>{status.data.account_email || t('calendar.google.account')} · {formatLastSynced(status.data.last_synced_at)}</small></span><button className="google-calendar-refresh" onClick={() => sync.mutate()} aria-label={t('calendar.google.syncNowAria')} title={t('calendar.google.syncNow')}><RefreshCw size={15} /></button><button className="google-calendar-manage-trigger" onClick={() => setManageOpen((open) => !open)} aria-expanded={manageOpen} aria-haspopup="menu">{t('calendar.google.manage')}<ChevronDown size={14} /></button></div>
    {manageOpen && <div className="google-calendar-manage-menu" role="menu"><div className="google-calendar-menu-heading"><span>{status.data.calendar_name || 'Google Calendar'}</span><small>{status.data.calendar_timezone || 'Asia/Ulaanbaatar'}</small></div><label>{t('calendar.google.calendar')}<select value={status.data.calendar_id || ''} onChange={(event) => selectCalendar.mutate(event.target.value)} disabled={selectCalendar.isPending || calendarList.isLoading}>{calendarList.data?.items.map((calendar) => <option key={calendar.id} value={calendar.id}>{calendar.name}{calendar.primary ? t('calendar.google.primary') : ''}</option>)}</select></label><button role="menuitem" onClick={() => sync.mutate()} disabled={sync.isPending}><RefreshCw size={14} />{t('calendar.google.syncNow')}</button><button role="menuitem" className="danger" onClick={() => { if (window.confirm(t('calendar.google.disconnectConfirm'))) disconnect.mutate() }} disabled={disconnect.isPending}><Unplug size={14} />{t('calendar.google.disconnect')}</button><a role="menuitem" href="https://calendar.google.com" target="_blank" rel="noreferrer"><ExternalLink size={14} />{t('calendar.google.open')}</a></div>}
  </div>
}

export function CalendarWorkspacePage() {
  const { t } = useTranslation()
  const [anchor, setAnchor] = useState(() => new Date())
  const [creating, setCreating] = useState(false)
  const [selected, setSelected] = useState<any | null>(null)
  const [editingItem, setEditingItem] = useState<any | null>(null)
  const [kind, setKind] = useState<'task' | 'reminder' | 'event'>('reminder')
  const [editing, setEditing] = useState(false)
  const [collaboratorQuery, setCollaboratorQuery] = useState('')
  const [availabilityWorker, setAvailabilityWorker] = useState<{ id: number; name: string; job_title?: string | null } | null>(null)
  const [filters, setFilters] = useState<Record<CalendarFilterKey, boolean>>(() => {
    const defaults = { event: true, plan: true, task: true, reminder: true }
    try {
      const saved = JSON.parse(window.localStorage.getItem(CALENDAR_FILTER_STORAGE_KEY) || '{}')
      return CALENDAR_FILTERS.reduce((result, filter) => ({ ...result, [filter.key]: saved[filter.key] !== false }), defaults)
    } catch {
      return defaults
    }
  })
  const [form, setForm] = useState({ title: '', description: '', starts_at: '', ends_at: '', visibility: 'private', location: '', collaborator_ids: [] as number[] })
  const [, startTransition] = useTransition()
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const { isManagerMode } = useWorkspaceMode()
  const scope: 'private' | 'corporate' = isManagerMode ? 'corporate' : 'private'
  const canPublish = roles.some((role) => ['admin', 'manager', 'team_lead'].includes(role))
  const days = useMemo(() => monthGridDays(anchor), [anchor])
  const isCurrentMonth = anchor.getFullYear() === new Date().getFullYear() && anchor.getMonth() === new Date().getMonth()
  const events = useCalendarEvents(scope, anchor)
  const createEntry = useCreateCalendarEntry(); const updateEntry = useUpdateCalendarEntry(); const deleteEntry = useDeleteCalendarEntry()
  const createTask = useCreateEnterpriseTask(); const updateTask = useUpdateEnterpriseTask(); const deleteTask = useDeleteEnterpriseTask()
  const workerDirectory = useWorkerDirectory()
  const workers = workerDirectory.data ?? []
  const filteredWorkers = workers.filter((worker) => worker.name.toLocaleLowerCase().includes(collaboratorQuery.toLocaleLowerCase().trim()) || worker.job_title?.toLocaleLowerCase().includes(collaboratorQuery.toLocaleLowerCase().trim()))
  const defaultVisibility = scope === 'corporate' && canPublish ? 'company' : 'private'
  const blankForm = () => ({ title: '', description: '', starts_at: '', ends_at: '', visibility: defaultVisibility, location: '', collaborator_ids: [] as number[] })
  const dateTimeInput = (date: Date) => { const pad = (value: number) => String(value).padStart(2, '0'); return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}` }
  const dateOnlyTimeInput = (value: unknown) => { if (typeof value !== 'string' || !value) return ''; if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return `${value}T00:00`; const date = new Date(value); return Number.isNaN(date.getTime()) ? '' : dateTimeInput(date) }
  const isoValue = (value: string) => value ? new Date(value).toISOString() : null
  const openCreate = (day?: Date, hour?: number) => {
    const start = day ? new Date(day) : new Date()
    const now = new Date()
    start.setHours(hour ?? now.getHours(), 0, 0, 0)
    const end = new Date(start); end.setHours(end.getHours() + 2)
    setSelected(null); setEditingItem(null); setEditing(false); setKind('reminder'); setCollaboratorQuery(''); setAvailabilityWorker(null)
    setForm({ ...blankForm(), starts_at: dateTimeInput(start), ends_at: dateTimeInput(end) }); setCreating(true)
  }
  const openEdit = (item: any) => {
    if (!['task', 'reminder', 'event'].includes(item.kind)) return
    setSelected(null); setEditingItem(item); setEditing(true); setKind(item.kind); setCollaboratorQuery(''); setAvailabilityWorker(null)
    setForm({
      title: item.title || '', description: item.description || '',
      starts_at: dateOnlyTimeInput(item.kind === 'task' ? item.start_at : item.starts_at),
      ends_at: dateOnlyTimeInput(item.kind === 'task' ? item.deadline_at : item.ends_at),
      visibility: item.visibility || 'private', location: item.kind === 'task' ? item.work_location || '' : item.location || '',
      collaborator_ids: item.kind === 'task' ? item.assignee_ids || [] : item.collaborator_ids || [],
    }); setCreating(true)
  }
  const updateStart = (starts_at: string) => {
    setForm((current) => { if (!starts_at) return { ...current, starts_at }; const end = new Date(starts_at); end.setHours(end.getHours() + 2); return { ...current, starts_at, ends_at: Number.isNaN(end.getTime()) ? current.ends_at : dateTimeInput(end) } })
  }
  const toggleCollaborator = (employeeId: number) => setForm((current) => ({ ...current, collaborator_ids: current.collaborator_ids.includes(employeeId) ? current.collaborator_ids.filter((id) => id !== employeeId) : [...current.collaborator_ids, employeeId] }))
  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    const starts_at = isoValue(form.starts_at); const ends_at = isoValue(form.ends_at)
    if (kind !== 'task' && (!starts_at || !ends_at)) { toast.error(t('calendar.timesRequired')); return }
    if (kind === 'task') {
      const payload = { title: form.title, description: form.description || null, start_at: starts_at, deadline_at: ends_at, assignee_ids: form.collaborator_ids, workflow_status: editing ? editingItem?.workflow_status || 'to_do' : 'to_do', work_location: form.location || null }
      if (editing && editingItem?.kind === 'task') await updateTask.mutateAsync({ id: editingItem.id, version: editingItem.version, ...payload })
      else await createTask.mutateAsync(payload)
    } else {
      const payload = { kind, visibility: canPublish ? form.visibility : 'private', title: form.title, description: form.description || null, location: form.location || null, starts_at, ends_at, collaborator_ids: form.collaborator_ids, remind_at: kind === 'reminder' ? starts_at : null }
      if (editing && editingItem) await updateEntry.mutateAsync({ id: editingItem.id, version: editingItem.version, ...payload })
      else await createEntry.mutateAsync(payload)
    }
    setForm(blankForm()); setCreating(false); setEditing(false); setEditingItem(null)
  }
  const removeSelected = async () => {
    if (!selected || !window.confirm(t('calendar.deleteConfirm', { title: selected.title }))) return
    if (selected.kind === 'task') await deleteTask.mutateAsync(selected.id)
    else if (selected.kind === 'reminder' || selected.kind === 'event') await deleteEntry.mutateAsync({ id: selected.id, version: selected.version })
    setSelected(null)
  }
  const all = useMemo(() => uniqueCalendarItems([...(events.data?.tasks ?? []), ...(events.data?.projects ?? []), ...(events.data?.plans ?? []), ...(events.data?.entries ?? []), ...(events.data?.holidays ?? []), ...(events.data?.time_blocks ?? [])]), [events.data])
  const visibleAll = useMemo(() => all.filter((item) => { const filter = calendarFilterKey(item); return !filter || filters[filter] }), [all, filters])
  const rangeLayout = useMemo(() => calendarRangeSegments(visibleAll, days), [visibleAll, days])
  const calendarGridRows = useMemo(() => rangeLayout.weekLanes.map((laneCount) => `${Math.max(CALENDAR_ROW_MIN, CALENDAR_DAY_HEAD + laneCount * CALENDAR_LANE + CALENDAR_ROW_PAD)}px`).join(' '), [rangeLayout.weekLanes])
  const mobileItemsByDate = useMemo(() => {
    const result = new Map<string, any[]>()
    visibleAll.forEach((item) => itemDates(item).forEach((date) => result.set(date, [...(result.get(date) ?? []), item])))
    return result
  }, [visibleAll])
  const followMobileMonth = (month: Date) => setAnchor((current) => current.getFullYear() === month.getFullYear() && current.getMonth() === month.getMonth() ? current : month)
  const holidayKeys = useMemo(() => new Set((events.data?.holidays ?? []).filter((item: any) => item.kind === 'holiday').flatMap(itemDates)), [events.data])
  const todayKey = localDate(new Date())
  const collaboratorNames = (ids: number[]) => ids.map((id) => workers.find((worker) => worker.id === id)?.name).filter(Boolean).join(', ')
  const itemTypeLabel = (item: any) => item.kind === 'task' ? t('calendar.type.task') : item.kind === 'reminder' ? t('calendar.type.reminder') : item.kind === 'event' ? t('calendar.type.event') : item.kind === 'project' ? t('calendar.project') : item.kind === 'plan' ? t('calendar.type.plan') : item.kind === 'holiday' ? t('calendar.holiday') : item.kind === 'birthday' ? t('calendar.birthday') : t('calendar.personalPlan')
  const formatDateTime = (value: unknown) => { const date = calendarDate(value); if (!date) return '—'; const parsed = new Date(String(value)); return Number.isNaN(parsed.getTime()) ? date : parsed.toLocaleString(intlLocale(), { dateStyle: 'medium', timeStyle: 'short' }) }
  const canEditSelected = selected && ['task', 'reminder', 'event'].includes(selected.kind) && selected.can_edit !== false
  const isSaving = createEntry.isPending || updateEntry.isPending || createTask.isPending || updateTask.isPending
  useEffect(() => {
    window.localStorage.setItem(CALENDAR_FILTER_STORAGE_KEY, JSON.stringify(filters))
  }, [filters])
  const toggleFilter = (key: CalendarFilterKey) => setFilters((current) => ({ ...current, [key]: !current[key] }))
  const allFiltersSelected = CALENDAR_FILTERS.every((filter) => filters[filter.key])
  const setAllFilters = () => setFilters((current) => CALENDAR_FILTERS.reduce((result, filter) => ({ ...result, [filter.key]: !allFiltersSelected }), current))
  return <div className="calendar-workspace"><div className="workspace-toolbar calendar-toolbar">
      <div className="calendar-toolbar-nav">
        <IconButton label={t('calendar.prevMonth')} tooltip={t('calendar.prevMonth')} icon={<ChevronLeft size={16} />} variant="ghost" size="sm" onClick={() => startTransition(() => setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() - 1, 1)))} />
        <strong className="calendar-toolbar-month">{anchor.toLocaleDateString(intlLocale(), { year: 'numeric', month: 'long' })}</strong>
        <IconButton label={t('calendar.nextMonth')} tooltip={t('calendar.nextMonth')} icon={<ChevronRight size={16} />} variant="ghost" size="sm" onClick={() => startTransition(() => setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() + 1, 1)))} />
        {!isCurrentMonth && <Button label={t('calendar.today')} variant="ghost" size="sm" onClick={() => startTransition(() => { const today = new Date(); setAnchor(new Date(today.getFullYear(), today.getMonth(), 1)) })} />}
      </div>
      <div className="calendar-filter-toolbar" role="toolbar" aria-label={t('calendar.filterAria')}>
        <div className="calendar-filter-chips">{CALENDAR_FILTERS.map((filter) => <button type="button" key={filter.key} className={`calendar-filter-chip ${filter.key} ${filters[filter.key] ? 'active' : ''}`} aria-pressed={filters[filter.key]} onClick={() => toggleFilter(filter.key)}><i aria-hidden />{filter.label}</button>)}</div>
        <button type="button" className="calendar-filter-all" onClick={setAllFilters}>{allFiltersSelected ? t('calendar.clearAll') : t('calendar.selectAll')}</button>
      </div>
      <div className="calendar-toolbar-actions">
        <GoogleCalendarSyncControl />
        <CreateButton label={t('calendar.create')} onClick={() => openCreate()} />
      </div>
    </div>
    {events.isError && <div className="panel calendar-status error">{t('calendar.loadFailed')}</div>}
    <QueryRegion state={toQueryRegionState(events)} skeleton={<CalendarSkeleton />}><>
      <div className="planning-calendar calendar-month panel">
        <div className="calendar-weekdays" aria-hidden>{days.slice(0, 7).map((day) => <span key={day.getDay()} className={day.getDay() === 0 || day.getDay() === 6 ? 'weekend' : ''}>{day.toLocaleDateString(intlLocale(), { weekday: 'short' })}</span>)}</div>
        <div className="calendar-month-grid" style={{ gridTemplateRows: calendarGridRows, ...CALENDAR_GRID_VARS }}>{days.map((day) => {
          const key = localDate(day)
          const redDay = day.getDay() === 0 || day.getDay() === 6 || holidayKeys.has(key)
          return <section key={key} role="button" tabIndex={0} aria-label={t('calendar.createOnDay', { date: key })} onClick={() => openCreate(day)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') openCreate(day) }} className={`calendar-day ${day.getMonth() === anchor.getMonth() ? '' : 'outside'} ${redDay ? 'red-day' : ''} ${key === todayKey ? 'today' : ''}`}>
            <header><strong>{day.getDate()}</strong>{day.getDate() === 1 && <span>{day.toLocaleDateString(intlLocale(), { month: 'short' })}</span>}</header>
          </section>
        })}<div className="calendar-range-layer" aria-label={t('calendar.aria')} style={{ gridTemplateRows: calendarGridRows }}>{rangeLayout.segments.map((segment) => {
          const time = segment.first ? calendarItemTime(segment.item) : null
          return <button className={`calendar-item calendar-range ${segment.item.kind || 'item'} ${segment.first ? 'range-start' : ''} ${segment.last ? 'range-end' : ''} ${time && segment.last && segment.start === segment.end ? 'timed' : ''}`} title={`${segment.item.title} · ${calendarItemSubtitle(segment.item)}`} key={`${segment.key}-${segment.week}`} style={{ gridColumn: `${segment.start + 1} / ${segment.end + 2}`, gridRow: `${segment.week + 1}`, '--range-lane': segment.lane } as React.CSSProperties} onClick={(event) => { event.stopPropagation(); setSelected(segment.item) }}><i className="calendar-item-dot" aria-hidden />{time && <time>{time}</time>}<strong>{segment.item.title}</strong></button>
        })}</div></div>
      </div>
      <MobileCalendarView itemsByDate={mobileItemsByDate} holidayKeys={holidayKeys} onSelectItem={setSelected} onCreate={openCreate} onMonthChange={followMobileMonth}
        filters={<div className="mcal-filter-list">{CALENDAR_FILTERS.map((filter) => <button type="button" key={filter.key} className={`calendar-filter-chip ${filter.key} ${filters[filter.key] ? 'active' : ''}`} aria-pressed={filters[filter.key]} onClick={() => toggleFilter(filter.key)}><i aria-hidden />{filter.label}</button>)}<button type="button" className="calendar-filter-all" onClick={setAllFilters}>{allFiltersSelected ? t('calendar.clearAll') : t('calendar.selectAll')}</button></div>}
        menu={<div className="mcal-menu"><span className="calendar-scope-badge">{isManagerMode ? t('calendar.companyView') : t('calendar.personalView')}</span><GoogleCalendarSyncControl /></div>} />
    </></QueryRegion>
    <AnimatePresence>{selected && <SheetPortal><motion.div className="sheet-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={() => setSelected(null)}><motion.aside className="detail-sheet" initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }} transition={{ type: 'spring', bounce: 0, duration: .4 }} onMouseDown={(event) => event.stopPropagation()}><div className="sheet-header"><div><span className="eyebrow">Calendar item</span><h2>{selected.title}</h2></div><div className="sheet-header-actions"><button className="sheet-close" onClick={() => setSelected(null)} aria-label={t('chat.close')}><X size={17} /></button></div></div><div className="calendar-detail"><p className="calendar-detail-type">{itemTypeLabel(selected)}</p>{selected.description && <p>{selected.description}</p>}<dl><div><dt>{t('calendar.start')}</dt><dd>{formatDateTime(selected.start_at || selected.starts_at || selected.starts_on || selected.plan_month || selected.holiday_date)}</dd></div><div><dt>{t('calendar.end')}</dt><dd>{selected.kind === 'task' && !selected.deadline_at ? t('calendar.noTime') : formatDateTime(selected.deadline_at || selected.ends_at || selected.ends_on || selected.due_date)}</dd></div>{(selected.location || selected.work_location) && <div><dt><MapPin size={13} />{t('calendar.location')}</dt><dd><a href={/^https?:\/\//i.test(selected.location || selected.work_location) ? selected.location || selected.work_location : undefined} target="_blank" rel="noreferrer">{selected.location || selected.work_location}</a></dd></div>}{(selected.collaborator_ids?.length || selected.assignee_ids?.length) > 0 && <div><dt><Users size={13} />{t('calendar.participants')}</dt><dd>{collaboratorNames(selected.collaborator_ids || selected.assignee_ids || []) || '—'}</dd></div>}{selected.kind === 'task' && <><div><dt>{t('tasks.form.status')}</dt><dd>{selected.workflow_status || '—'}</dd></div><div><dt>{t('calendar.owner')}</dt><dd>{selected.primary_owner_name || t('calendar.type.task')}</dd></div>{selected.project_name && <div><dt>{t('calendar.project')}</dt><dd>{selected.project_name}</dd></div>}</>}</dl>{canEditSelected && <div className="calendar-detail-actions"><button className="secondary-action" onClick={() => openEdit(selected)}><UserRound size={15} />{t('calendar.edit')}</button><button className="danger-action" onClick={() => void removeSelected()} disabled={deleteEntry.isPending || deleteTask.isPending}><Trash2 size={15} />{t('tasks.delete')}</button></div>}</div></motion.aside></motion.div></SheetPortal>}</AnimatePresence>
    <AnimatePresence>{creating && <SheetPortal><motion.div className="sheet-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={() => setCreating(false)}><motion.aside className="detail-sheet" initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }} transition={{ type: 'spring', bounce: 0, duration: .4 }} onMouseDown={(event) => event.stopPropagation()}><div className="sheet-header"><div><span className="eyebrow">Calendar item</span><h2>{editing ? t('calendar.edit') : t('calendar.createNew')}</h2></div><button className="sheet-close" onClick={() => setCreating(false)} aria-label={t('chat.close')}><X size={17} /></button></div><form className="sheet-form" onSubmit={submit}><label>{t('calendar.kind')}<select value={kind} disabled={editing} onChange={(event) => setKind(event.target.value as typeof kind)}><option value="task">{t('calendar.type.task')}</option><option value="reminder">{t('calendar.type.reminder')}</option><option value="event">{t('calendar.type.event')}</option></select></label>{kind !== 'task' && canPublish && <label>{t('calendar.visibility')}<select value={form.visibility} onChange={(event) => setForm({ ...form, visibility: event.target.value })}><option value="private">{t('calendar.visibility.personal')}</option><option value="company">{t('calendar.visibility.company')}</option></select></label>}<label>{t('calendar.fieldTitle')}<input required value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} /></label><label>{t('calendar.fieldDescription')}<textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label><label>{t('calendar.fieldLocation')}<span className="field-help">{t('calendar.fieldLocationHint')}</span><input type="text" value={form.location} onChange={(event) => setForm({ ...form, location: event.target.value })} placeholder="https://meet.google.com/..." /></label><div className="calendar-collaborator-picker"><div className="calendar-picker-heading"><span>{t('calendar.participants')}</span><small>{t('chat.selectedN', { n: form.collaborator_ids.length })}</small></div><div className="calendar-picker-search"><Users size={15} /><input type="search" value={collaboratorQuery} onChange={(event) => setCollaboratorQuery(event.target.value)} placeholder={t('calendar.searchByName')} aria-label={t('calendar.searchParticipant')} /></div><div className="calendar-picker-options">{filteredWorkers.slice(0, 8).map((worker) => <div className="calendar-picker-option" key={worker.id}><button type="button" className={form.collaborator_ids.includes(worker.id) ? 'selected' : ''} onClick={() => toggleCollaborator(worker.id)}><span><strong>{worker.name}</strong><small>{worker.job_title || t('calendar.employee')}</small></span>{form.collaborator_ids.includes(worker.id) && <X size={14} />}</button><button type="button" className="calendar-availability-trigger" aria-label={t('calendar.workerSchedule', { name: worker.name })} title={t('calendar.viewSchedule')} aria-expanded={availabilityWorker?.id === worker.id} onClick={(event) => { event.stopPropagation(); setAvailabilityWorker((current) => current?.id === worker.id ? null : worker) }}><CalendarDays size={15} /></button></div>)}{filteredWorkers.length === 0 && <small className="calendar-picker-empty">{t('calendar.noPeople')}</small>}</div>{availabilityWorker && <WorkerAvailabilityPopover worker={availabilityWorker} scope={scope} onClose={() => setAvailabilityWorker(null)} />}</div><div className="form-row"><label>{t('calendar.start')} {kind === 'task' && <span className="field-help">{t('calendar.optional')}</span>}<input required={kind !== 'task'} type="datetime-local" value={form.starts_at} onChange={(event) => updateStart(event.target.value)} /></label><label>{t('calendar.end')} {kind === 'task' && <span className="field-help">{t('calendar.optional')}</span>}<input required={kind !== 'task'} type="datetime-local" value={form.ends_at} onChange={(event) => setForm({ ...form, ends_at: event.target.value })} /></label></div><button className="primary-action" disabled={isSaving}><Plus size={16} />{t('calendar.create')}</button></form></motion.aside></motion.div></SheetPortal>}</AnimatePresence>
  </div>
}
