import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { CalendarRange, Check, ChevronDown, X } from 'lucide-react'
import { DateRange } from '../api/enterprise'

export type PeriodPreset = 'today' | 'week' | 'month' | 'quarter'

function localDate(date: Date) {
  const offset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offset).toISOString().slice(0, 10)
}

export function periodFromPreset(preset: PeriodPreset): DateRange {
  const end = new Date()
  const start = new Date(end)
  const days = preset === 'today' ? 0 : preset === 'week' ? 6 : preset === 'month' ? 29 : 89
  start.setDate(start.getDate() - days)
  return { date_from: localDate(start), date_to: localDate(end) }
}

const OPTIONS: PeriodPreset[] = ['today', 'week', 'month', 'quarter']

/** "2026-09-02" → "09.02"; the year is added only when the range leaves the current year. */
function shortDate(value: string, withYear: boolean) {
  const [year, month, day] = value.split('-')
  if (!year || !month || !day) return value
  return withYear ? `${year}.${month}.${day}` : `${month}.${day}`
}

function rangeLabel(period: DateRange) {
  const thisYear = String(new Date().getFullYear())
  const withYear = !period.date_from.startsWith(thisYear) || !period.date_to.startsWith(thisYear)
  if (period.date_from === period.date_to) return shortDate(period.date_from, withYear)
  return `${shortDate(period.date_from, withYear)} – ${shortDate(period.date_to, withYear)}`
}

const PANEL_WIDTH = 288

/**
 * One compact trigger for every viewport. The panel is anchored under the trigger on desktop and
 * becomes a bottom sheet on phones (CSS decides; the anchor is passed as custom properties).
 */
export function TimePeriodFilter({ preset, period, onChange }: { preset: PeriodPreset | 'custom'; period: DateRange; onChange: (preset: PeriodPreset | 'custom', period: DateRange) => void }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(period)
  const [draftPreset, setDraftPreset] = useState<PeriodPreset | 'custom'>(preset)
  const [error, setError] = useState('')
  const [anchor, setAnchor] = useState<{ top: number; left: number } | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)

  const close = () => {
    setOpen(false)
    triggerRef.current?.focus()
  }

  useEffect(() => {
    if (!open) return
    setDraft(period)
    setDraftPreset(preset)
    setError('')
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false)
        triggerRef.current?.focus()
      }
    }
    document.addEventListener('keydown', closeOnEscape)
    return () => document.removeEventListener('keydown', closeOnEscape)
  }, [open, period, preset])

  useLayoutEffect(() => {
    if (!open) return
    const place = () => {
      const rect = triggerRef.current?.getBoundingClientRect()
      if (!rect) return
      const left = Math.max(8, Math.min(rect.left, window.innerWidth - PANEL_WIDTH - 8))
      setAnchor({ top: rect.bottom + 6, left })
    }
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [open])

  const presetLabel = OPTIONS.includes(preset as PeriodPreset) ? t(`period.${preset}`) : undefined
  const range = rangeLabel(period)

  const selectPreset = (nextPreset: PeriodPreset) => {
    onChange(nextPreset, periodFromPreset(nextPreset))
    close()
  }

  const applyCustom = () => {
    if (!draft.date_from || !draft.date_to || draft.date_from > draft.date_to) {
      setError(t('period.invalidRange'))
      return
    }
    onChange('custom', draft)
    close()
  }

  const panelStyle = anchor ? { '--period-picker-top': `${anchor.top}px`, '--period-picker-left': `${anchor.left}px` } as CSSProperties : undefined

  return <>
    <button ref={triggerRef} type="button" className="period-picker-trigger" onClick={() => setOpen((current) => !current)} aria-haspopup="dialog" aria-expanded={open} aria-label={t('period.trigger', { value: presetLabel ?? range })}>
      <CalendarRange size={15} aria-hidden />
      <strong>{presetLabel ?? range}</strong>
      {presetLabel && <span className="period-picker-range">{range}</span>}
      <ChevronDown size={14} aria-hidden />
    </button>
    {open && createPortal(<div className="period-picker-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) close() }}>
      <section className="period-picker-panel" role="dialog" aria-modal="true" aria-labelledby="period-picker-title" style={panelStyle}>
        <header><h2 id="period-picker-title">{t('period.pickTitle')}</h2><button type="button" onClick={close} aria-label={t('period.close')}><X size={16} /></button></header>
        <div className="period-picker-presets">{OPTIONS.map((option) => <button type="button" key={option} className={draftPreset === option ? 'active' : ''} aria-pressed={draftPreset === option} onClick={() => selectPreset(option)}><span>{t(`period.${option}`)}</span>{draftPreset === option && <Check size={15} aria-hidden />}</button>)}</div>
        <div className="period-picker-custom">
          <span className="period-picker-caption">{t('period.custom')}</span>
          <div><label>{t('period.from')}<input type="date" value={draft.date_from} onChange={(event) => { setDraftPreset('custom'); setDraft({ ...draft, date_from: event.target.value }); setError('') }} /></label><label>{t('period.to')}<input type="date" value={draft.date_to} onChange={(event) => { setDraftPreset('custom'); setDraft({ ...draft, date_to: event.target.value }); setError('') }} /></label></div>
          {error && <p role="alert">{error}</p>}
        </div>
        <footer><button type="button" className="secondary-action" onClick={close}>{t('period.cancel')}</button><button type="button" className="primary-action" onClick={applyCustom}>{t('period.apply')}</button></footer>
      </section>
    </div>, document.body)}
  </>
}
