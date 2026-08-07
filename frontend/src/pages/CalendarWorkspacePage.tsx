import { useMemo, useState, useTransition } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { CalendarDays, Plus } from 'lucide-react'
import { useCalendarEvents, useCreateCalendarEntry, useCreateEnterpriseTask, useHolidaySettings, useSetHolidayCountry } from '../api/enterprise'
import { EMPTY_ROLES, useAuthStore } from '../store/auth'
import { CalendarSkeleton, QueryRegion } from '../components/Loading'

function localDate(value: Date) { const offset = value.getTimezoneOffset() * 60_000; return new Date(value.getTime() - offset).toISOString().slice(0, 10) }
function calendarDate(value: unknown) {
  if (typeof value !== 'string' || !value) return null
  // Date-only values must not be passed through Date.parse: midnight UTC can
  // move them to the previous local day in Ulaanbaatar and similar zones.
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? null : localDate(parsed)
}
function itemDates(item: any) {
  // Holidays and birthdays are represented as all-day intervals whose end is
  // exclusive (for example, Jan 8 00:00 -> Jan 9 00:00). The end belongs to
  // the next interval, so it must not become a second visible calendar day.
  if (item.kind === 'holiday' || item.kind === 'birthday') {
    const start = calendarDate(item.holiday_date || item.starts_at || item.start_at)
    return start ? [start] : []
  }
  return [...new Set([item.start_at, item.starts_at, item.deadline_at, item.ends_at, item.holiday_date]
    .map(calendarDate)
    .filter((value): value is string => Boolean(value)))]
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

export function CalendarWorkspacePage() {
  const [scope, setScope] = useState<'private' | 'corporate'>('private')
  const [anchor, setAnchor] = useState(() => new Date())
  const [creating, setCreating] = useState(false)
  const [kind, setKind] = useState<'task' | 'reminder' | 'event'>('reminder')
  const [form, setForm] = useState({ title: '', description: '', starts_at: '', ends_at: '', visibility: 'private' })
  const [, startTransition] = useTransition()
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const canPublish = roles.some((role) => ['admin', 'manager', 'team_lead'].includes(role))
  const isAdmin = roles.includes('admin')
  const days = useMemo(() => { const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1); first.setDate(first.getDate() - ((first.getDay() + 6) % 7)); return Array.from({ length: 42 }, (_, index) => { const day = new Date(first); day.setDate(day.getDate() + index); return day }) }, [anchor])
  const period = { date_from: localDate(days[0]), date_to: localDate(days[41]) }
  const events = useCalendarEvents(scope, period)
  const holidaySettings = useHolidaySettings(); const setCountry = useSetHolidayCountry()
  const createEntry = useCreateCalendarEntry(); const createTask = useCreateEnterpriseTask()
  const submit = async (event: React.FormEvent) => { event.preventDefault(); const starts_at = new Date(form.starts_at).toISOString(); const ends_at = new Date(form.ends_at).toISOString(); if (kind === 'task') await createTask.mutateAsync({ title: form.title, description: form.description || null, start_at: starts_at, deadline_at: ends_at, workflow_status: 'to_do' }); else await createEntry.mutateAsync({ kind, visibility: form.visibility, title: form.title, description: form.description || null, starts_at, ends_at, remind_at: kind === 'reminder' ? starts_at : null }); setForm({ title: '', description: '', starts_at: '', ends_at: '', visibility: 'private' }); setCreating(false) }
  const all = useMemo(() => uniqueCalendarItems([...(events.data?.tasks ?? []), ...(events.data?.entries ?? []), ...(events.data?.holidays ?? []), ...(events.data?.time_blocks ?? [])]), [events.data])
  const holidayKeys = new Set((events.data?.holidays ?? []).filter((item: any) => item.kind === 'holiday').flatMap(itemDates))
  const todayKey = localDate(new Date())
  return <div className="calendar-workspace"><div className="view-toolbar"><div><h2>Календарь</h2><p>Даалгавар, сануулга, үйл явдал болон компанийн чухал өдрүүд.</p></div><div className="toolbar-cluster"><div className="segmented-control"><button className={scope === 'private' ? 'active' : ''} onClick={() => startTransition(() => setScope('private'))}>Хувийн</button><button className={scope === 'corporate' ? 'active' : ''} onClick={() => startTransition(() => setScope('corporate'))}>Компанийн</button></div><button className="primary-action compact" onClick={() => { setForm({ ...form, visibility: scope === 'corporate' && canPublish ? 'company' : 'private' }); setCreating(true) }}><Plus size={16} />Үүсгэх</button></div></div>
    <div className="calendar-month-nav"><strong>{anchor.toLocaleDateString('mn-MN', { year: 'numeric', month: 'long' })}</strong><div className="calendar-holiday-setting"><span className="holiday-country">Амралт: {holidaySettings.data?.country || 'MN'}</span>{isAdmin && <select aria-label="Амралтын өдрийн улс" value={holidaySettings.data?.country || 'MN'} onChange={(event) => setCountry.mutate(event.target.value)} disabled={setCountry.isPending}>{holidaySettings.data?.countries.map((country) => <option key={country.countryCode} value={country.countryCode}>{country.name}</option>)}</select>}</div><div className="calendar-nav-actions"><button onClick={() => startTransition(() => setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() - 1, 1)))} aria-label="Өмнөх сар">←</button><button className="calendar-today-button" onClick={() => startTransition(() => { const today = new Date(); setAnchor(new Date(today.getFullYear(), today.getMonth(), 1)) })}>Өнөөдөр</button><button onClick={() => startTransition(() => setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() + 1, 1)))} aria-label="Дараагийн сар">→</button></div></div>
    {events.isError && <div className="panel calendar-status error">Календарийн мэдээлэл ачаалагдсангүй. Дахин оролдоно уу.</div>}
    <QueryRegion pending={events.isLoading || events.isFetching} skeleton={<CalendarSkeleton />}><div className="planning-calendar panel">{days.map((day) => { const key = localDate(day); const items = all.filter((item: any) => itemDates(item).includes(key)); const redDay = day.getDay() === 0 || day.getDay() === 6 || holidayKeys.has(key); return <section key={key} className={`${day.getMonth() === anchor.getMonth() ? '' : 'outside'} ${redDay ? 'red-day' : ''} ${key === todayKey ? 'today' : ''}`}><header><strong>{day.getDate()}</strong><span>{day.toLocaleDateString('mn-MN', { weekday: 'short' })}</span></header>{items.map((item: any) => <article className={`calendar-item ${item.kind}`} key={`${item.kind}-${item.id}`}><strong>{item.title}</strong><small>{item.kind === 'task' ? item.primary_owner_name || 'Даалгавар' : item.kind === 'holiday' ? 'Нийтийн амралт' : item.kind === 'birthday' ? 'Төрсөн өдөр' : item.visibility === 'company' ? 'Компанийн үйл явдал' : item.kind === 'reminder' ? 'Сануулга' : 'Хувийн үйл явдал'}</small></article>)}</section> })}</div></QueryRegion>
    <AnimatePresence>{creating && <motion.div className="sheet-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={() => setCreating(false)}><motion.aside className="detail-sheet" initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }} transition={{ type: 'spring', bounce: 0, duration: .4 }} onMouseDown={(event) => event.stopPropagation()}><div className="sheet-header"><div><span className="eyebrow">Calendar item</span><h2>Шинэ зүйл үүсгэх</h2></div><CalendarDays /></div><form className="sheet-form" onSubmit={submit}><label>Төрөл<select value={kind} onChange={(event) => setKind(event.target.value as typeof kind)}><option value="task">Даалгавар</option><option value="reminder">Сануулга</option><option value="event">Үйл явдал</option></select></label>{kind !== 'task' && canPublish && <label>Харагдац<select value={form.visibility} onChange={(event) => setForm({ ...form, visibility: event.target.value })}><option value="private">Хувийн</option><option value="company">Компанийн</option></select></label>}<label>Гарчиг<input required value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} /></label><label>Тайлбар<textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label><label>Эхлэх<input required type="datetime-local" value={form.starts_at} onChange={(event) => setForm({ ...form, starts_at: event.target.value })} /></label><label>Дуусах<input required type="datetime-local" value={form.ends_at} onChange={(event) => setForm({ ...form, ends_at: event.target.value })} /></label><button className="primary-action" disabled={createEntry.isPending || createTask.isPending}>Хадгалах</button></form></motion.aside></motion.div>}</AnimatePresence>
  </div>
}
