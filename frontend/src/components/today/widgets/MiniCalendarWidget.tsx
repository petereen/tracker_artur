import { useMemo, type CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { CalendarDays } from 'lucide-react'
import { useCalendarEvents, useEnterpriseTasks, useTodayAgenda, type EnterpriseTask } from '../../../api/enterprise'
import { intlLocale } from '../../../utils/locale'
import { useWorkspaceMode } from '../../WorkspaceModeProvider'
import { localDateKey, WidgetHeader } from './shared'

type MiniCalendarRange = {
  id: string
  title: string
  week: number
  start: number
  end: number
  lane: number
  laneCount: number
  isStart: boolean
  isEnd: boolean
}

function calendarDayKey(value: string | null | undefined) {
  if (!value) return null
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? null : localDateKey(parsed)
}

/** Month grid with markers for tasks, events, reminders and multi-day task bars. */
const WEEKDAY_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const

export function MiniCalendarWidget() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { isManagerMode } = useWorkspaceMode()
  const today = new Date().toISOString().slice(0, 10)
  const monthDays = useMemo(() => {
    const now = new Date()
    const first = new Date(now.getFullYear(), now.getMonth(), 1)
    first.setDate(first.getDate() - ((first.getDay() + 6) % 7))
    return Array.from({ length: 42 }, (_, index) => {
      const day = new Date(first)
      day.setDate(day.getDate() + index)
      return day
    })
  }, [])
  const todayTasks = useEnterpriseTasks(undefined, { date_from: today, date_to: today }, { scope: 'mine' })
  const delegatedTasks = useEnterpriseTasks(undefined, undefined, { scope: 'delegated' })
  const agenda = useTodayAgenda()
  const miniCalendarTasks = useEnterpriseTasks(undefined, {
    date_from: localDateKey(monthDays[0]),
    date_to: localDateKey(monthDays[monthDays.length - 1]),
  }, { scope: 'mine' })
  const miniCalendarEvents = useCalendarEvents(isManagerMode ? 'corporate' : 'private', monthDays[20])
  const visibleTasks = useMemo(() => {
    const tasks = new Map<number, EnterpriseTask>()
    ;[
      ...(miniCalendarEvents.data?.tasks ?? []),
      ...(miniCalendarTasks.data ?? []),
      ...(todayTasks.data ?? []),
      ...(isManagerMode ? delegatedTasks.data ?? [] : []),
      ...(!isManagerMode ? agenda.data?.tasks ?? [] : []),
    ].forEach((task: EnterpriseTask) => tasks.set(task.id, task))
    return [...tasks.values()]
  }, [agenda.data?.tasks, delegatedTasks.data, isManagerMode, miniCalendarEvents.data?.tasks, miniCalendarTasks.data, todayTasks.data])
  const markers = useMemo(() => {
    type MarkerKind = 'task' | 'event' | 'reminder' | 'time-block'
    const dates = new Map<string, Set<MarkerKind>>()
    const add = (value: string | null | undefined, kind: MarkerKind) => {
      const key = calendarDayKey(value)
      if (!key) return
      if (!dates.has(key)) dates.set(key, new Set())
      dates.get(key)!.add(kind)
    }
    visibleTasks.forEach((task) => {
      if (task.start_at && task.deadline_at) return
      add(task.start_at || task.deadline_at, 'task')
    })
    ;[...(miniCalendarEvents.data?.entries ?? []), ...(!isManagerMode ? agenda.data?.entries ?? [] : [])].forEach((item: any) => add(item.remind_at || item.starts_at || item.start_at, item.kind === 'reminder' ? 'reminder' : 'event'))
    ;[...(miniCalendarEvents.data?.time_blocks ?? [])].forEach((item: any) => add(item.starts_at || item.start_at, 'time-block'))
    return dates
  }, [agenda.data?.entries, isManagerMode, miniCalendarEvents.data?.entries, miniCalendarEvents.data?.time_blocks, visibleTasks])
  const ranges = useMemo(() => {
    const visibleStart = localDateKey(monthDays[0])
    const visibleEnd = localDateKey(monthDays[monthDays.length - 1])
    const dayIndex = new Map(monthDays.map((day, index) => [localDateKey(day), index]))
    const segments: MiniCalendarRange[] = []
    visibleTasks.forEach((task) => {
      if (!task.start_at || !task.deadline_at) return
      let taskStart = calendarDayKey(task.start_at)!
      let taskEnd = calendarDayKey(task.deadline_at)!
      if (taskEnd < taskStart) [taskStart, taskEnd] = [taskEnd, taskStart]
      if (taskEnd < visibleStart || taskStart > visibleEnd) return
      const start = Math.max(0, dayIndex.get(taskStart) ?? (taskStart < visibleStart ? 0 : -1))
      const end = Math.min(monthDays.length - 1, dayIndex.get(taskEnd) ?? (taskEnd > visibleEnd ? monthDays.length - 1 : -1))
      if (start < 0 || end < start) return
      for (let week = Math.floor(start / 7); week <= Math.floor(end / 7); week += 1) {
        const segmentStart = Math.max(start, week * 7)
        const segmentEnd = Math.min(end, week * 7 + 6)
        const overlapping = segments.filter((segment) => segment.week === week && segment.start <= segmentEnd && segment.end >= segmentStart)
        let lane = 0
        while (overlapping.some((segment) => segment.lane === lane)) lane += 1
        segments.push({
          id: `${task.id}-${week}`,
          title: task.title,
          week,
          start: segmentStart % 7,
          end: segmentEnd % 7,
          lane,
          laneCount: 0,
          isStart: segmentStart === start && taskStart >= visibleStart,
          isEnd: segmentEnd === end && taskEnd <= visibleEnd,
        })
      }
    })
    for (let week = 0; week < 6; week += 1) {
      const weekSegments = segments.filter((segment) => segment.week === week)
      const laneCount = Math.max(1, ...weekSegments.map((segment) => segment.lane + 1))
      weekSegments.forEach((segment) => { segment.laneCount = laneCount })
    }
    return segments
  }, [visibleTasks, monthDays])
  const todayKey = localDateKey(new Date())
  const currentMonth = new Date().getMonth()

  return (
    <aside className="today-widget today-mini-calendar" aria-label={t('today.widget.mini-calendar.title')}>
      <WidgetHeader icon={CalendarDays} title={new Date().toLocaleDateString(intlLocale(), { month: 'long', year: 'numeric' })}>
        <button type="button" className="today-widget-link" onClick={() => navigate('/calendar')}>{t('today.miniCalendar.open')}</button>
      </WidgetHeader>
      <div className="mini-weekdays">{WEEKDAY_KEYS.map((day) => <b key={day}>{t(`today.weekday.${day}`)}</b>)}</div>
      <div className="mini-month-grid">
        {monthDays.map((day, dayIndex) => {
          const local = localDateKey(day)
          const dayMarkers = [...(markers.get(local) ?? [])]
          const week = Math.floor(dayIndex / 7)
          const column = dayIndex % 7
          const fragments = ranges.filter((range) => range.week === week && range.start <= column && range.end >= column)
          return (
            <span key={local} className={`${local === todayKey ? 'today' : ''} ${day.getMonth() !== currentMonth ? 'outside' : ''}`}>
              <i>{day.getDate()}</i>
              {fragments.map((range) => {
                const isStart = range.isStart && column === range.start
                const isEnd = range.isEnd && column === range.end
                return <u className={`mini-range-fragment${isStart ? ' range-start' : ''}${isEnd ? ' range-end' : ''}`} key={range.id} title={range.title} style={{ '--mini-lane': range.lane } as CSSProperties} />
              })}
              {dayMarkers.length > 0 && (
                <em className="mini-day-markers" aria-label={t('today.miniCalendar.markers', { n: dayMarkers.length })}>
                  {dayMarkers.map((marker) => <b className={`mini-day-marker ${marker}`} key={marker} />)}
                </em>
              )}
            </span>
          )
        })}
      </div>
    </aside>
  )
}
