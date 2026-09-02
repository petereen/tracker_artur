import { useEffect, useMemo, useState, useTransition } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { CalendarDays, ChevronDown, ExternalLink, LoaderCircle, MapPin, Plus, RefreshCw, Trash2, Unplug, UserRound, Users, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { isNativePlatform } from '../platform/runtime'
import { useCalendarEvents, useCreateCalendarEntry, useCreateEnterpriseTask, useDeleteCalendarEntry, useDeleteEnterpriseTask, useGoogleCalendarConnect, useGoogleCalendarDisconnect, useGoogleCalendarList, useGoogleCalendarSelect, useGoogleCalendarStatus, useGoogleCalendarSync, useHolidaySettings, useSetHolidayCountry, useUpdateCalendarEntry, useUpdateEnterpriseTask, useWorkerDirectory } from '../api/enterprise'
import { EMPTY_ROLES, useAuthStore } from '../store/auth'
import { CalendarSkeleton, QueryRegion } from '../components/Loading'
import { useWorkspaceMode } from '../components/WorkspaceModeProvider'

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
  return item.kind === 'task' ? item.primary_owner_name || 'Даалгавар' : item.kind === 'project' ? `Төсөл · ${item.code || ''}` : item.kind === 'plan' ? `Төлөвлөгөө · ${item.horizon || ''}` : item.kind === 'holiday' ? 'Нийтийн амралт' : item.kind === 'birthday' ? 'Төрсөн өдөр' : item.visibility === 'company' ? 'Компаний үйл явдал' : item.kind === 'reminder' ? 'Сануулга' : 'Хувийн үйл явдал'
}
function calendarRangeSegments(items: any[], days: Date[]) {
  const dayIndexes = new Map(days.map((day, index) => [localDate(day), index]))
  const byWeek = Array.from({ length: 6 }, () => [] as Array<{ item: any; start: number; end: number; first: boolean; last: boolean; lane: number }>)
  items.filter((item) => ['task', 'project', 'plan'].includes(item.kind)).forEach((item) => {
    const dates = itemDates(item)
    const visibleIndexes = dates.map((date) => dayIndexes.get(date)).filter((index): index is number => index !== undefined)
    if (visibleIndexes.length < 2) return
    let segmentStart = visibleIndexes[0]
    let previous = visibleIndexes[0]
    const addSegment = (start: number, end: number) => {
      const week = Math.floor(start / 7)
      byWeek[week].push({ item, start: start % 7, end: end % 7, first: dates[0] === localDate(days[start]), last: dates[dates.length - 1] === localDate(days[end]), lane: 0 })
    }
    visibleIndexes.slice(1).forEach((index) => {
      if (index % 7 === 0 || index !== previous + 1) { addSegment(segmentStart, previous); segmentStart = index }
      previous = index
    })
    addSegment(segmentStart, previous)
  })
  return byWeek.flatMap((segments, week) => {
    const laneEnds: number[] = []
    return segments.sort((left, right) => left.start - right.start || right.end - left.end).map((segment) => {
      const lane = laneEnds.findIndex((end) => end < segment.start)
      segment.lane = lane === -1 ? laneEnds.length : lane
      laneEnds[segment.lane] = segment.end
      return { ...segment, week }
    })
  })
}

function formatLastSynced(value?: string | null) {
  if (!value) return 'Одоогоор sync хийгдээгүй'
  const minutes = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 60000))
  return minutes < 1 ? 'Дөнгөж сая sync хийсэн' : `${minutes} мин өмнө sync хийсэн`
}

export function GoogleCalendarSyncControl() {
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
        toast.success('Google Calendar холбогдлоо')
        status.refetch()
      } else toast.error('Google Calendar холболт амжилтгүй боллоо')
    }
    window.addEventListener('message', receive)
    return () => window.removeEventListener('message', receive)
  }, [status])

  const openConnect = async () => {
    if (isNativePlatform()) {
      toast.error('Google Calendar холболтыг одоогоор вэб хувилбараас тохируулна уу')
      return
    }
    try {
      const result = await connect.mutateAsync()
      if (!result.authorization_url) {
        toast.error('Google OAuth тохиргоо дутуу байна')
        return
      }
      const popup = window.open(result.authorization_url, 'oyuns-google-calendar', 'popup,width=560,height=720,resizable=yes,scrollbars=yes')
      if (!popup) window.location.assign(result.authorization_url)
      else popup.focus()
    } catch (error: any) {
      toast.error(error.response?.data?.detail || 'Google Calendar холбогдсонгүй')
    }
  }

  if (status.isLoading) return <button className="google-calendar-sync-control disconnected" disabled><LoaderCircle size={15} className="spin" />Google Calendar</button>
  if (status.data?.status !== 'active') return <button className="google-calendar-sync-control disconnected" onClick={openConnect} disabled={connect.isPending}><span className="google-calendar-mark" aria-hidden="true">31</span>{connect.isPending ? 'Холбож байна…' : 'Google Calendar холбох'}</button>
  if (sync.isPending) return <button className="google-calendar-sync-control syncing" disabled><LoaderCircle size={15} className="spin" />Syncing...</button>

  return <div className="google-calendar-sync-wrap">
    <div className="google-calendar-sync-control connected"><span className="google-calendar-mark" aria-hidden="true">31</span><span className="google-calendar-sync-copy"><strong><span className="google-calendar-status-dot" />Холбогдсон</strong><small>{status.data.account_email || 'Google account'} · {formatLastSynced(status.data.last_synced_at)}</small></span><button className="google-calendar-refresh" onClick={() => sync.mutate()} aria-label="Sync Google Calendar now" title="Sync Now"><RefreshCw size={15} /></button><button className="google-calendar-manage-trigger" onClick={() => setManageOpen((open) => !open)} aria-expanded={manageOpen} aria-haspopup="menu">Manage<ChevronDown size={14} /></button></div>
    {manageOpen && <div className="google-calendar-manage-menu" role="menu"><div className="google-calendar-menu-heading"><span>{status.data.calendar_name || 'Google Calendar'}</span><small>{status.data.calendar_timezone || 'Asia/Ulaanbaatar'}</small></div><label>Calendar<select value={status.data.calendar_id || ''} onChange={(event) => selectCalendar.mutate(event.target.value)} disabled={selectCalendar.isPending || calendarList.isLoading}>{calendarList.data?.items.map((calendar) => <option key={calendar.id} value={calendar.id}>{calendar.name}{calendar.primary ? ' · Primary' : ''}</option>)}</select></label><button role="menuitem" onClick={() => sync.mutate()} disabled={sync.isPending}><RefreshCw size={14} />Sync Now</button><button role="menuitem" className="danger" onClick={() => { if (window.confirm('Google Calendar холболтыг салгах уу?')) disconnect.mutate() }} disabled={disconnect.isPending}><Unplug size={14} />Disconnect</button><a role="menuitem" href="https://calendar.google.com" target="_blank" rel="noreferrer"><ExternalLink size={14} />Open Google Calendar</a></div>}
  </div>
}

export function CalendarWorkspacePage() {
  const [anchor, setAnchor] = useState(() => new Date())
  const [selectedMobileDate, setSelectedMobileDate] = useState(() => localDate(new Date()))
  const [creating, setCreating] = useState(false)
  const [selected, setSelected] = useState<any | null>(null)
  const [editingItem, setEditingItem] = useState<any | null>(null)
  const [kind, setKind] = useState<'task' | 'reminder' | 'event'>('reminder')
  const [editing, setEditing] = useState(false)
  const [collaboratorQuery, setCollaboratorQuery] = useState('')
  const [form, setForm] = useState({ title: '', description: '', starts_at: '', ends_at: '', visibility: 'private', location: '', collaborator_ids: [] as number[] })
  const [, startTransition] = useTransition()
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const { isManagerMode } = useWorkspaceMode()
  const scope: 'private' | 'corporate' = isManagerMode ? 'corporate' : 'private'
  const canPublish = roles.some((role) => ['admin', 'manager', 'team_lead'].includes(role))
  const isAdmin = roles.includes('admin')
  const days = useMemo(() => { const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1); first.setDate(first.getDate() - ((first.getDay() + 6) % 7)); return Array.from({ length: 42 }, (_, index) => { const day = new Date(first); day.setDate(day.getDate() + index); return day }) }, [anchor])
  const events = useCalendarEvents(scope, anchor)
  const holidaySettings = useHolidaySettings(); const setCountry = useSetHolidayCountry()
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
  const openCreate = (day?: Date) => {
    const start = day ? new Date(day) : new Date()
    const now = new Date()
    start.setHours(now.getHours(), 0, 0, 0)
    const end = new Date(start); end.setHours(end.getHours() + 2)
    setSelected(null); setEditingItem(null); setEditing(false); setKind('reminder'); setCollaboratorQuery('')
    setForm({ ...blankForm(), starts_at: dateTimeInput(start), ends_at: dateTimeInput(end) }); setCreating(true)
  }
  const openEdit = (item: any) => {
    if (!['task', 'reminder', 'event'].includes(item.kind)) return
    setSelected(null); setEditingItem(item); setEditing(true); setKind(item.kind); setCollaboratorQuery('')
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
    if (kind !== 'task' && (!starts_at || !ends_at)) { toast.error('Үйл явдал, сануулгад эхлэх ба дуусах цаг шаардлагатай'); return }
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
    if (!selected || !window.confirm(`“${selected.title}” устгах уу?`)) return
    if (selected.kind === 'task') await deleteTask.mutateAsync(selected.id)
    else if (selected.kind === 'reminder' || selected.kind === 'event') await deleteEntry.mutateAsync({ id: selected.id, version: selected.version })
    setSelected(null)
  }
  const all = useMemo(() => uniqueCalendarItems([...(events.data?.tasks ?? []), ...(events.data?.projects ?? []), ...(events.data?.plans ?? []), ...(events.data?.entries ?? []), ...(events.data?.holidays ?? []), ...(events.data?.time_blocks ?? [])]), [events.data])
  const rangeSegments = useMemo(() => calendarRangeSegments(all, days), [all, days])
  const mobileDays = days
  const mobileMonthDays = useMemo(() => days.filter((day) => day.getMonth() === anchor.getMonth()), [anchor, days])
  const mobileItemsByDate = useMemo(() => {
    const result = new Map<string, any[]>()
    all.forEach((item) => itemDates(item).forEach((date) => result.set(date, [...(result.get(date) ?? []), item])))
    return result
  }, [all])
  const mobileSelectedItems = mobileItemsByDate.get(selectedMobileDate) ?? []
  useEffect(() => {
    const today = new Date()
    const selectedDate = new Date(`${selectedMobileDate}T12:00:00`)
    const selectedIsInAnchorMonth = selectedDate.getFullYear() === anchor.getFullYear() && selectedDate.getMonth() === anchor.getMonth()
    if (selectedIsInAnchorMonth) return
    const todayInMonth = today.getFullYear() === anchor.getFullYear() && today.getMonth() === anchor.getMonth()
    const firstPopulated = mobileMonthDays.map(localDate).find((date) => mobileItemsByDate.has(date))
    setSelectedMobileDate(todayInMonth ? localDate(today) : firstPopulated ?? localDate(mobileMonthDays[0] ?? anchor))
  }, [anchor, mobileMonthDays, mobileItemsByDate, selectedMobileDate])
  const holidayKeys = new Set((events.data?.holidays ?? []).filter((item: any) => item.kind === 'holiday').flatMap(itemDates))
  const todayKey = localDate(new Date())
  const collaboratorNames = (ids: number[]) => ids.map((id) => workers.find((worker) => worker.id === id)?.name).filter(Boolean).join(', ')
  const itemTypeLabel = (item: any) => item.kind === 'task' ? 'Даалгавар' : item.kind === 'reminder' ? 'Сануулга' : item.kind === 'event' ? 'Үйл явдал' : item.kind === 'project' ? 'Төсөл' : item.kind === 'plan' ? 'Төлөвлөгөө' : item.kind === 'holiday' ? 'Нийтийн амралт' : item.kind === 'birthday' ? 'Төрсөн өдөр' : 'Хувийн төлөвлөгөө'
  const formatDateTime = (value: unknown) => { const date = calendarDate(value); if (!date) return '—'; const parsed = new Date(String(value)); return Number.isNaN(parsed.getTime()) ? date : parsed.toLocaleString('mn-MN', { dateStyle: 'medium', timeStyle: 'short' }) }
  const canEditSelected = selected && ['task', 'reminder', 'event'].includes(selected.kind) && selected.can_edit !== false
  const isSaving = createEntry.isPending || updateEntry.isPending || createTask.isPending || updateTask.isPending
  return <div className="calendar-workspace"><div className="workspace-toolbar calendar-toolbar"><div className="toolbar-start"><GoogleCalendarSyncControl /><span className="calendar-scope-badge">{isManagerMode ? 'Компаний харагдац' : 'Хувийн харагдац'}</span></div><button className="primary-action compact" onClick={() => openCreate()}><Plus size={16} />Үүсгэх</button></div>
    <div className="calendar-month-nav"><strong>{anchor.toLocaleDateString('mn-MN', { year: 'numeric', month: 'long' })}</strong><div className="calendar-holiday-setting"><span className="holiday-country">Амралт: {holidaySettings.data?.country || 'MN'}</span>{isAdmin && <select aria-label="Амралтын өдрийн улс" value={holidaySettings.data?.country || 'MN'} onChange={(event) => setCountry.mutate(event.target.value)} disabled={setCountry.isPending}>{holidaySettings.data?.countries.map((country) => <option key={country.countryCode} value={country.countryCode}>{country.name}</option>)}</select>}</div><div className="calendar-nav-actions"><button onClick={() => startTransition(() => setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() - 1, 1)))} aria-label="Өмнөх сар">←</button><button className="calendar-today-button" onClick={() => startTransition(() => { const today = new Date(); setAnchor(new Date(today.getFullYear(), today.getMonth(), 1)) })}>Өнөөдөр</button><button onClick={() => startTransition(() => setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() + 1, 1)))} aria-label="Дараагийн сар">→</button></div></div>
    {events.isError && <div className="panel calendar-status error">Календарийн мэдээлэл ачаалагдсангүй. Дахин оролдоно уу.</div>}
    <QueryRegion pending={events.isLoading || events.isFetching} skeleton={<CalendarSkeleton />}><>
      <div className="planning-calendar panel">{days.map((day) => { const key = localDate(day); const items = all.filter((item: any) => itemDates(item).includes(key) && (!['task', 'project', 'plan'].includes(item.kind) || itemDates(item).length === 1)); const redDay = day.getDay() === 0 || day.getDay() === 6 || holidayKeys.has(key); return <section key={key} role="button" tabIndex={0} aria-label={`${key} өдөрт зүйл үүсгэх`} onClick={() => openCreate(day)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') openCreate(day) }} className={`${day.getMonth() === anchor.getMonth() ? '' : 'outside'} ${redDay ? 'red-day' : ''} ${key === todayKey ? 'today' : ''}`}><header><strong>{day.getDate()}</strong><span>{day.toLocaleDateString('mn-MN', { weekday: 'short' })}</span></header>{items.map((item: any) => <button className={`calendar-item ${item.kind}`} key={`${item.kind}-${item.id || item.project_id || item.plan_id}`} onClick={(event) => { event.stopPropagation(); setSelected(item) }}><strong>{item.title}</strong><small>{calendarItemSubtitle(item)}</small></button>)}</section> })}<div className="calendar-range-layer" aria-label="Олон өдрийн ажлууд">{rangeSegments.map((segment) => <button className={`calendar-item calendar-range ${segment.item.kind} ${segment.first ? 'range-start' : ''} ${segment.last ? 'range-end' : ''}`} key={`${segment.item.kind}-${segment.item.id || segment.item.project_id || segment.item.plan_id}-${segment.week}`} style={{ gridColumn: `${segment.start + 1} / ${segment.end + 2}`, gridRow: `${segment.week + 1}`, '--range-lane': segment.lane } as React.CSSProperties} onClick={(event) => { event.stopPropagation(); setSelected(segment.item) }}><strong>{segment.item.title}</strong><small>{calendarItemSubtitle(segment.item)}</small></button>)}</div></div>
      <section className="mobile-calendar panel" aria-label="Гар утасны календарь"><div className="mobile-calendar-weekdays">{['Дав', 'Мяг', 'Лха', 'Пүр', 'Баа', 'Бям', 'Ням'].map((day) => <span key={day}>{day}</span>)}</div><div className="mobile-calendar-grid">{mobileDays.map((day) => { const key = localDate(day); const items = mobileItemsByDate.get(key) ?? []; const markerKinds = [...new Set(items.map((item) => item.kind))].slice(0, 3); return <button type="button" key={key} className={`${day.getMonth() !== anchor.getMonth() ? 'outside' : ''} ${key === selectedMobileDate ? 'selected' : ''} ${key === todayKey ? 'today' : ''} ${day.getDay() === 0 || day.getDay() === 6 || holidayKeys.has(key) ? 'red-day' : ''}`} aria-label={`${day.toLocaleDateString('mn-MN', { month: 'long', day: 'numeric', weekday: 'long' })}, ${items.length} зүйл`} aria-pressed={key === selectedMobileDate} onClick={() => { setSelectedMobileDate(key); openCreate(day) }}><strong>{day.getDate()}</strong>{items.length > 0 && <span className="mobile-calendar-count">{items.length}</span>}<i aria-hidden>{markerKinds.map((kind, index) => <b className={kind} key={`${kind}-${index}`} />)}</i></button> })}</div><div className="mobile-calendar-agenda"><header><div><span className="eyebrow">Сонгосон өдөр</span><h2>{new Date(`${selectedMobileDate}T12:00:00`).toLocaleDateString('mn-MN', { month: 'long', day: 'numeric', weekday: 'long' })}</h2></div><span>{mobileSelectedItems.length} зүйл</span></header>{mobileSelectedItems.length ? mobileSelectedItems.map((item: any) => <button type="button" className={`mobile-calendar-agenda-item ${item.kind}`} key={`${item.kind}-${item.id || item.project_id || item.plan_id}`} onClick={() => setSelected(item)}><span className="mobile-calendar-agenda-marker" aria-hidden /><span><strong>{item.title}</strong><small>{calendarItemSubtitle(item)}</small></span></button>) : <p>Энэ өдөр танд төлөвлөсөн ажил байхгүй байна.</p>}</div></section>
    </></QueryRegion>
    <AnimatePresence>{selected && <motion.div className="sheet-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={() => setSelected(null)}><motion.aside className="detail-sheet" initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }} transition={{ type: 'spring', bounce: 0, duration: .4 }} onMouseDown={(event) => event.stopPropagation()}><div className="sheet-header"><div><span className="eyebrow">Calendar item</span><h2>{selected.title}</h2></div><div className="sheet-header-actions"><button className="sheet-close" onClick={() => setSelected(null)} aria-label="Хаах"><X size={17} /></button></div></div><div className="calendar-detail"><p className="calendar-detail-type">{itemTypeLabel(selected)}</p>{selected.description && <p>{selected.description}</p>}<dl><div><dt>Эхлэх</dt><dd>{formatDateTime(selected.start_at || selected.starts_at || selected.starts_on || selected.plan_month || selected.holiday_date)}</dd></div><div><dt>Дуусах</dt><dd>{selected.kind === 'task' && !selected.deadline_at ? 'Хугацаагүй' : formatDateTime(selected.deadline_at || selected.ends_at || selected.ends_on || selected.due_date)}</dd></div>{(selected.location || selected.work_location) && <div><dt><MapPin size={13} />Байршил</dt><dd><a href={/^https?:\/\//i.test(selected.location || selected.work_location) ? selected.location || selected.work_location : undefined} target="_blank" rel="noreferrer">{selected.location || selected.work_location}</a></dd></div>}{(selected.collaborator_ids?.length || selected.assignee_ids?.length) > 0 && <div><dt><Users size={13} />Хамтрагчид</dt><dd>{collaboratorNames(selected.collaborator_ids || selected.assignee_ids || []) || '—'}</dd></div>}{selected.kind === 'task' && <><div><dt>Төлөв</dt><dd>{selected.workflow_status || '—'}</dd></div><div><dt>Хариуцагч</dt><dd>{selected.primary_owner_name || 'Даалгавар'}</dd></div>{selected.project_name && <div><dt>Төсөл</dt><dd>{selected.project_name}</dd></div>}</>}</dl>{canEditSelected && <div className="calendar-detail-actions"><button className="secondary-action" onClick={() => openEdit(selected)}><UserRound size={15} />Засах</button><button className="danger-action" onClick={() => void removeSelected()} disabled={deleteEntry.isPending || deleteTask.isPending}><Trash2 size={15} />Устгах</button></div>}</div></motion.aside></motion.div>}</AnimatePresence>
    <AnimatePresence>{creating && <motion.div className="sheet-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={() => setCreating(false)}><motion.aside className="detail-sheet" initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }} transition={{ type: 'spring', bounce: 0, duration: .4 }} onMouseDown={(event) => event.stopPropagation()}><div className="sheet-header"><div><span className="eyebrow">Calendar item</span><h2>{editing ? 'Засах' : 'Шинэ зүйл үүсгэх'}</h2></div><button className="sheet-close" onClick={() => setCreating(false)} aria-label="Хаах"><X size={17} /></button></div><form className="sheet-form" onSubmit={submit}><label>Төрөл<select value={kind} disabled={editing} onChange={(event) => setKind(event.target.value as typeof kind)}><option value="task">Даалгавар</option><option value="reminder">Сануулга</option><option value="event">Үйл явдал</option></select></label>{kind !== 'task' && canPublish && <label>Харагдац<select value={form.visibility} onChange={(event) => setForm({ ...form, visibility: event.target.value })}><option value="private">Хувийн</option><option value="company">Компаний</option></select></label>}<label>Гарчиг<input required value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} /></label><label>Тайлбар<textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label><label>Байршил эсвэл уулзалтын холбоос<span className="field-help">Google Meet, Zoom, оффисын хаяг</span><input type="text" value={form.location} onChange={(event) => setForm({ ...form, location: event.target.value })} placeholder="https://meet.google.com/..." /></label><div className="calendar-collaborator-picker"><div className="calendar-picker-heading"><span>Хамтрагчид</span><small>{form.collaborator_ids.length} сонгосон</small></div><div className="calendar-picker-search"><Users size={15} /><input type="search" value={collaboratorQuery} onChange={(event) => setCollaboratorQuery(event.target.value)} placeholder="Нэрээр хайх…" aria-label="Хамтрагч хайх" /></div><div className="calendar-picker-options">{filteredWorkers.slice(0, 8).map((worker) => <button type="button" className={form.collaborator_ids.includes(worker.id) ? 'selected' : ''} key={worker.id} onClick={() => toggleCollaborator(worker.id)}><span><strong>{worker.name}</strong><small>{worker.job_title || 'Ажилтан'}</small></span>{form.collaborator_ids.includes(worker.id) && <X size={14} />}</button>)}{filteredWorkers.length === 0 && <small className="calendar-picker-empty">Ажилтан олдсонгүй.</small>}</div></div><div className="form-row"><label>Эхлэх {kind === 'task' && <span className="field-help">сонголттой</span>}<input required={kind !== 'task'} type="datetime-local" value={form.starts_at} onChange={(event) => updateStart(event.target.value)} /></label><label>Дуусах {kind === 'task' && <span className="field-help">сонголттой</span>}<input required={kind !== 'task'} type="datetime-local" value={form.ends_at} onChange={(event) => setForm({ ...form, ends_at: event.target.value })} /></label></div><button className="primary-action" disabled={isSaving}><Plus size={16} />Үүсгэх</button></form></motion.aside></motion.div>}</AnimatePresence>
  </div>
}
