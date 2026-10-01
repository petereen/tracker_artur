import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Coffee, House, Laptop2, Pause, Play, Timer } from 'lucide-react'
import { useClock, useClockAction } from '../../../api/enterprise'
import { useAuthStore } from '../../../store/auth'
import { intlLocale } from '../../../utils/locale'
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
    return new Intl.DateTimeFormat(intlLocale(), { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: timezone }).format(new Date(value))
  } catch {
    return new Date(value).toLocaleTimeString(intlLocale(), { hour: '2-digit', minute: '2-digit', hour12: false })
  }
}

/** Today's work-hour clock: start (office/remote), break, resume, stop. */
export function WorktimeWidget() {
  const { t } = useTranslation()
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
    <section className="today-widget clock-panel today-worktime" aria-label={t('today.worktime.title')}>
      <WidgetHeader icon={Timer} title={t('today.worktime.title')} meta={<span className={`live-indicator ${active ? 'online' : ''}`}>{active ? t('today.worktime.working') : t('today.worktime.resting')}</span>} />
      {clockReady ? (
        <div className="clock-summary">
          <div className="clock-time" aria-live="polite">{formatDuration(todayWorkSeconds)}</div>
          <p>
            {working
              ? t('today.worktime.workingIn', { mode: active?.mode === 'remote' ? t('today.worktime.remote') : t('today.worktime.office') })
              : onBreak ? t('today.worktime.breakNote') : t('today.worktime.syncNote')}
          </p>
          <div className="clock-details" aria-label={t('today.worktime.details')}>
            {todayEntries.map((entry) => (
              <div key={entry.id}>
                {entry.entry_type === 'break' ? t('today.worktime.break') : entry.mode === 'remote' ? t('today.worktime.remote') : t('today.worktime.office')}:{' '}
                {formatLocalTime(entry.started_at, timezone)}–{entry.ended_at ? formatLocalTime(entry.ended_at, timezone) : t('today.worktime.now')}{' '}
                ({formatDuration(entrySeconds(entry))})
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="clock-summary clock-summary-skeleton" aria-label={t('today.worktime.loading')}>
          <span className="skeleton clock-time-skeleton" />
          <span className="skeleton clock-copy-skeleton" />
        </div>
      )}
      {recoveredClock && <div className="clock-recovery" role="alert"><strong>{t('today.worktime.recoveredTitle')}</strong><span>{t('today.worktime.recoveredBody')}</span></div>}
      <div className="clock-actions">
        {!active && <>
          <WorkdayStartButton className="clock-button office"><House />{t('today.worktime.startOffice')}</WorkdayStartButton>
          <button className="clock-button remote" onClick={() => action.mutate({ action: 'start', mode: 'remote' })}><Laptop2 />{t('today.worktime.startRemote')}</button>
        </>}
        {working && <>
          <button className="clock-button break" onClick={() => action.mutate({ action: 'break' })}><Coffee />{t('today.worktime.break')}</button>
          <button className="clock-button stop" onClick={() => action.mutate({ action: 'stop' })}><Pause />{t('today.worktime.finishDay')}</button>
        </>}
        {onBreak && <>
          <button className="clock-button office" onClick={() => action.mutate({ action: 'resume' })}><Play />{t('today.worktime.resume')}</button>
          <button className="clock-button stop" onClick={() => action.mutate({ action: 'stop' })}><Pause />{t('today.worktime.finishDay')}</button>
        </>}
      </div>
    </section>
  )
}
