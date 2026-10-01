import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { Hourglass, NotebookPen, Pause, Play, RotateCcw } from 'lucide-react'
import { NumberInput } from '@astryxdesign/core/NumberInput'
import { SegmentedControl, SegmentedControlItem } from '@astryxdesign/core/SegmentedControl'
import { Switch } from '@astryxdesign/core/Switch'
import { VStack } from '@astryxdesign/core/VStack'
import i18n from '../../../i18n'
import { safeLocalStorage } from '../../../platform/runtime'
import type { WidgetProps, WidgetSettingsProps } from '../types'
import { WidgetHeader } from './shared'

// ---- timer -------------------------------------------------------------------

type TimerMode = 'focus' | 'countdown' | 'stopwatch'
interface TimerRun { mode: TimerMode; phase: 'focus' | 'break'; running: boolean; startedAt: number | null; accumulated: number }
export interface TimerSettings { focusMinutes: number; breakMinutes: number; countdownMinutes: number; sound: boolean }
export const DEFAULT_TIMER_SETTINGS: TimerSettings = { focusMinutes: 25, breakMinutes: 5, countdownMinutes: 10, sound: true }

const IDLE_RUN: TimerRun = { mode: 'focus', phase: 'focus', running: false, startedAt: null, accumulated: 0 }
const timerKey = (id: string) => `oyuns.today-timer:${id}`

function loadRun(id: string): TimerRun {
  try {
    const saved = JSON.parse(safeLocalStorage().get(timerKey(id)) || 'null')
    return saved && typeof saved === 'object' ? { ...IDLE_RUN, ...saved } : IDLE_RUN
  } catch {
    return IDLE_RUN
  }
}

function formatClock(ms: number) {
  const total = Math.max(0, Math.round(ms / 1000))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  const pad = (value: number) => String(value).padStart(2, '0')
  return hours ? `${hours}:${pad(minutes)}:${pad(seconds)}` : `${pad(minutes)}:${pad(seconds)}`
}

function chime() {
  try {
    const context = new (window.AudioContext || (window as any).webkitAudioContext)()
    const oscillator = context.createOscillator()
    const gain = context.createGain()
    oscillator.frequency.value = 880
    gain.gain.setValueAtTime(0.0001, context.currentTime)
    gain.gain.exponentialRampToValueAtTime(0.2, context.currentTime + 0.02)
    gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.6)
    oscillator.connect(gain).connect(context.destination)
    oscillator.start()
    oscillator.stop(context.currentTime + 0.6)
    oscillator.onended = () => void context.close()
  } catch {
    // Audio can be blocked; the toast still tells the user.
  }
}

export function TimerWidget({ id, settings }: WidgetProps<TimerSettings>) {
  const { t } = useTranslation()
  const config = { ...DEFAULT_TIMER_SETTINGS, ...settings }
  const [run, setRunState] = useState<TimerRun>(() => loadRun(id))
  const [now, setNow] = useState(() => Date.now())
  const setRun = (next: TimerRun) => {
    setRunState(next)
    safeLocalStorage().set(timerKey(id), JSON.stringify(next))
  }
  const target = run.mode === 'countdown'
    ? config.countdownMinutes * 60_000
    : run.mode === 'focus' ? (run.phase === 'focus' ? config.focusMinutes : config.breakMinutes) * 60_000 : null
  const elapsed = run.accumulated + (run.running && run.startedAt ? now - run.startedAt : 0)
  const remaining = target === null ? null : target - elapsed

  useEffect(() => {
    if (!run.running) return
    const timer = window.setInterval(() => setNow(Date.now()), 250)
    return () => window.clearInterval(timer)
  }, [run.running])

  const runRef = useRef(run)
  runRef.current = run
  useEffect(() => {
    if (remaining === null || remaining > 0 || !runRef.current.running) return
    const current = runRef.current
    if (config.sound) chime()
    if (current.mode === 'focus') {
      const nextPhase = current.phase === 'focus' ? 'break' : 'focus'
      toast(i18n.t(nextPhase === 'break' ? 'today.timer.focusEnded' : 'today.timer.breakEnded'), { icon: '⏱️' })
      setRun({ ...current, phase: nextPhase, running: false, startedAt: null, accumulated: 0 })
    } else {
      toast(i18n.t('today.timer.ended'), { icon: '⏱️' })
      setRun({ ...current, running: false, startedAt: null, accumulated: 0 })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [remaining !== null && remaining <= 0])

  const toggle = () => {
    const at = Date.now()
    setNow(at)
    setRun(run.running
      ? { ...run, running: false, startedAt: null, accumulated: run.accumulated + (run.startedAt ? at - run.startedAt : 0) }
      : { ...run, running: true, startedAt: at })
  }
  const reset = () => setRun({ ...run, running: false, startedAt: null, accumulated: 0, phase: 'focus' })
  const progress = target ? Math.min(1, elapsed / target) : 0

  return (
    <section className="today-widget today-timer" aria-label={t('today.widget.timer.title')}>
      <WidgetHeader icon={Hourglass} title={t('today.widget.timer.title')} meta={run.mode === 'focus' ? (run.phase === 'focus' ? t('today.timer.focusPhase') : t('today.timer.breakPhase')) : undefined} />
      <span className="today-timer-mode" data-today-interactive>
        <SegmentedControl label={t('today.timer.mode')} size="sm" layout="fill" value={run.mode} onChange={(mode) => setRun({ ...IDLE_RUN, mode: mode as TimerMode })}>
          <SegmentedControlItem value="focus" label={t('today.timer.focusPhase')} />
          <SegmentedControlItem value="countdown" label={t('today.timer.countdown')} />
          <SegmentedControlItem value="stopwatch" label={t('today.timer.stopwatch')} />
        </SegmentedControl>
      </span>
      <time className={`today-timer-display${run.running ? ' is-running' : ''}`} role="timer" aria-live="off">
        {formatClock(remaining ?? elapsed)}
      </time>
      {target !== null && <span className="today-timer-progress" aria-hidden><i style={{ transform: `scaleX(${progress})` }} /></span>}
      <span className="today-timer-actions">
        <button type="button" className="primary-action compact" onClick={toggle}>{run.running ? <><Pause size={14} />{t('today.timer.stop')}</> : <><Play size={14} />{elapsed > 0 ? t('today.timer.resume') : t('today.timer.start')}</>}</button>
        <button type="button" className="secondary-action compact" onClick={reset} disabled={!elapsed && run.phase === 'focus'} aria-label={t('today.timer.reset')}><RotateCcw size={14} /></button>
      </span>
    </section>
  )
}

export function TimerSettingsForm({ settings, onChange }: WidgetSettingsProps<TimerSettings>) {
  const { t } = useTranslation()
  const config = { ...DEFAULT_TIMER_SETTINGS, ...settings }
  const minutes = (value: number) => Math.min(600, Math.max(1, Math.round(value) || 1))
  return (
    <VStack gap={3}>
      <NumberInput label={t('today.timer.focusMinutes')} units={t('today.timer.minutesUnit')} value={config.focusMinutes} min={1} max={600} isIntegerOnly hasNumberSteppers onChange={(value) => onChange({ ...config, focusMinutes: minutes(value) })} />
      <NumberInput label={t('today.timer.breakMinutes')} units={t('today.timer.minutesUnit')} value={config.breakMinutes} min={1} max={600} isIntegerOnly hasNumberSteppers onChange={(value) => onChange({ ...config, breakMinutes: minutes(value) })} />
      <NumberInput label={t('today.timer.countdownMinutes')} units={t('today.timer.minutesUnit')} value={config.countdownMinutes} min={1} max={600} isIntegerOnly hasNumberSteppers onChange={(value) => onChange({ ...config, countdownMinutes: minutes(value) })} />
      <Switch label={t('today.timer.sound')} value={config.sound} onChange={(sound) => onChange({ ...config, sound })} />
    </VStack>
  )
}

// ---- notes -------------------------------------------------------------------

export interface NotesSettings { text: string }
export const NOTES_MAX_LENGTH = 4000
const NOTES_SAVE_DELAY_MS = 600

/** Scratchpad that autosaves into the widget's (server-synced) settings. */
export function NotesWidget({ settings, updateSettings }: WidgetProps<NotesSettings>) {
  const { t } = useTranslation()
  const [text, setText] = useState(settings.text ?? '')
  const [status, setStatus] = useState<'saved' | 'dirty'>('saved')
  const timer = useRef<number | undefined>(undefined)
  const latest = useRef(text)
  const saveRef = useRef(updateSettings)
  saveRef.current = updateSettings

  // Adopt changes that arrive from another device while nothing is pending.
  useEffect(() => {
    if (timer.current === undefined && settings.text !== undefined && settings.text !== latest.current) {
      latest.current = settings.text
      setText(settings.text)
    }
  }, [settings.text])
  useEffect(() => () => {
    if (timer.current !== undefined) {
      window.clearTimeout(timer.current)
      saveRef.current({ text: latest.current })
    }
  }, [])

  const change = (value: string) => {
    const next = value.slice(0, NOTES_MAX_LENGTH)
    latest.current = next
    setText(next)
    setStatus('dirty')
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      timer.current = undefined
      saveRef.current({ text: latest.current })
      setStatus('saved')
    }, NOTES_SAVE_DELAY_MS)
  }

  return (
    <section className="today-widget today-notes" aria-label={t('today.widget.notes.title')}>
      <WidgetHeader icon={NotebookPen} title={t('today.widget.notes.title')} meta={<span aria-live="polite">{status === 'dirty' ? t('today.notes.saving') : text ? t('today.notes.saved') : ''}</span>} />
      <textarea
        className="today-notes-input"
        value={text}
        onChange={(event) => change(event.target.value)}
        placeholder={t('today.notes.placeholder')}
        aria-label={t('today.widget.notes.title')}
        maxLength={NOTES_MAX_LENGTH}
        spellCheck
      />
    </section>
  )
}
