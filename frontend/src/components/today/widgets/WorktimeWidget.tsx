import { useEffect, useRef, useState } from 'react'
import { Coffee, House, Laptop2, Pause, Play, Timer } from 'lucide-react'
import { useClock, useClockAction } from '../../../api/enterprise'
import { useAuthStore } from '../../../store/auth'
import { WorkdayStartButton } from '../../WorkdayStartButton'
import { WidgetHeader } from './shared'

function formatDuration(seconds: number) {
  seconds = Math.max(0, Math.floor(seconds))
  return [Math.floor(seconds / 3600), Math.floor((seconds % 3600) / 60), seconds % 60]
    .map((value) => String(value).padStart(2, '0'))
    .join(':')
}

function formatLocalTime(value: string, timezone: string) {
  try {
    return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: timezone }).format(new Date(value))
  } catch {
    return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
  }
}

/** Today's work-hour clock: start (office/remote), break, resume, stop. */
export function WorktimeWidget() {
  const employeeId = useAuthStore((state) => state.actor?.employee_id)
  const clock = useClock(employeeId != null)
  const action = useClockAction()
  const today = new Date().toISOString().slice(0, 10)
  const active = clock.data?.active
  const clockReady = Boolean(clock.data)
  const [clientNow, setClientNow] = useState(() => Date.now())
  const serverClockRef = useRef<{ serverTimeMs: number; clientTimeMs: number } | null>(null)
  const clockRefetchRef = useRef(clock.refetch)
  clockRefetchRef.current = clock.refetch
  const clockEnabledRef = useRef(employeeId != null)
  clockEnabledRef.current = employeeId != null
  const serverTime = clock.data?.server_time
  useEffect(() => {
    if (!serverTime) return
    const serverTimeMs = new Date(serverTime).getTime()
    if (Number.isFinite(serverTimeMs)) serverClockRef.current = { serverTimeMs, clientTimeMs: Date.now() }
  }, [serverTime])
  const activeTimerKey = active ? `${active.id}:${active.entry_type}:${active.started_at}` : null
  useEffect(() => {
    let timer: number | undefined
    const syncNow = () => setClientNow(Date.now())
    const clearTimer = () => {
      if (timer !== undefined) {
        window.clearInterval(timer)
        timer = undefined
      }
    }
    const startTimer = () => {
      if (activeTimerKey && document.visibilityState === 'visible' && timer === undefined) timer = window.setInterval(syncNow, 1000)
    }
    const handleVisibilityChange = () => {
      syncNow()
      if (document.visibilityState === 'visible') {
        if (clockEnabledRef.current) void clockRefetchRef.current()
        startTimer()
      } else {
        clearTimer()
      }
    }
    syncNow()
    startTimer()
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      clearTimer()
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [activeTimerKey])
  const serverClock = serverClockRef.current
  const initialServerTime = serverTime ? new Date(serverTime).getTime() : NaN
  const clockNow = serverClock
    ? serverClock.serverTimeMs + (clientNow - serverClock.clientTimeMs)
    : Number.isFinite(initialServerTime) ? initialServerTime : clientNow
  const recoveredClock = Boolean(active && (active.local_work_date !== today || clockNow - new Date(active.started_at).getTime() > 16 * 60 * 60 * 1000))
  const working = active?.entry_type === 'work'
  const onBreak = active?.entry_type === 'break'
  const todayEntries = clock.data?.today_entries ?? []
  const timezone = clock.data?.timezone ?? 'Asia/Ulaanbaatar'
  const entrySeconds = (entry: (typeof todayEntries)[number]) =>
    Math.max(0, ((entry.ended_at ? new Date(entry.ended_at).getTime() : clockNow) - new Date(entry.started_at).getTime()) / 1000)
  const todayWorkSeconds = todayEntries.reduce((total, entry) => (entry.entry_type === 'work' ? total + entrySeconds(entry) : total), 0)

  return (
    <section className="today-widget clock-panel today-worktime" aria-label="Өнөөдрийн ажлын цаг">
      <WidgetHeader icon={Timer} title="Өнөөдрийн ажлын цаг" meta={<span className={`live-indicator ${active ? 'online' : ''}`}>{active ? 'АЖИЛЛАЖ БАЙНА' : 'АМАРЧ БАЙНА'}</span>} />
      {clockReady ? (
        <div className="clock-summary">
          <div className="clock-time" aria-live="polite">{formatDuration(todayWorkSeconds)}</div>
          <p>
            {working
              ? `${active?.mode === 'remote' ? 'Remote' : 'Оффис'} горимоор ажиллаж байна.`
              : onBreak ? 'Завсарлагын хугацаа ажилласан цагт орохгүй.' : 'Telegram болон вэбийн цагийн төлөв үргэлж ижил байна.'}
          </p>
          <div className="clock-details" aria-label="Өнөөдрийн цагийн дэлгэрэнгүй">
            {todayEntries.map((entry) => (
              <div key={entry.id}>
                {entry.entry_type === 'break' ? 'Завсарлага' : entry.mode === 'remote' ? 'Remote' : 'Оффис'}:{' '}
                {formatLocalTime(entry.started_at, timezone)}–{entry.ended_at ? formatLocalTime(entry.ended_at, timezone) : 'одоо'}{' '}
                ({formatDuration(entrySeconds(entry))})
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="clock-summary clock-summary-skeleton" aria-label="Цагийн төлөв ачаалж байна">
          <span className="skeleton clock-time-skeleton" />
          <span className="skeleton clock-copy-skeleton" />
        </div>
      )}
      {recoveredClock && <div className="clock-recovery" role="alert"><strong>Өмнөх сесс сэргээгдлээ.</strong><span>Энэ цагийн бүртгэл удаан нээлттэй эсвэл өөр өдрөөс үргэлжилж байна. Одоогийн төлөвөө шалгаад үргэлжлүүлэх эсвэл дуусгана уу.</span></div>}
      <div className="clock-actions">
        {!active && <>
          <WorkdayStartButton className="clock-button office"><House />Оффис эхлэх</WorkdayStartButton>
          <button className="clock-button remote" onClick={() => action.mutate({ action: 'start', mode: 'remote' })}><Laptop2 />Remote эхлэх</button>
        </>}
        {working && <>
          <button className="clock-button break" onClick={() => action.mutate({ action: 'break' })}><Coffee />Завсарлага</button>
          <button className="clock-button stop" onClick={() => action.mutate({ action: 'stop' })}><Pause />Өдөр дуусгах</button>
        </>}
        {onBreak && <>
          <button className="clock-button office" onClick={() => action.mutate({ action: 'resume' })}><Play />Үргэлжлүүлэх</button>
          <button className="clock-button stop" onClick={() => action.mutate({ action: 'stop' })}><Pause />Өдөр дуусгах</button>
        </>}
      </div>
    </section>
  )
}
