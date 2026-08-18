import { useEffect, useRef, useState } from 'react'
import { CalendarRange, Check, X } from 'lucide-react'
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

const OPTIONS: { key: PeriodPreset; label: string }[] = [
  { key: 'today', label: 'Өнөөдөр' },
  { key: 'week', label: '7 хоног' },
  { key: 'month', label: '30 хоног' },
  { key: 'quarter', label: '90 хоног' },
]

export function TimePeriodFilter({ preset, period, onChange }: { preset: PeriodPreset | 'custom'; period: DateRange; onChange: (preset: PeriodPreset | 'custom', period: DateRange) => void }) {
  const [mobileOpen, setMobileOpen] = useState(false)
  const [draft, setDraft] = useState(period)
  const [draftPreset, setDraftPreset] = useState<PeriodPreset | 'custom'>(preset)
  const [error, setError] = useState('')
  const triggerRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!mobileOpen) return
    setDraft(period)
    setDraftPreset(preset)
    setError('')
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setMobileOpen(false)
        triggerRef.current?.focus()
      }
    }
    document.addEventListener('keydown', closeOnEscape)
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', closeOnEscape)
      document.body.style.overflow = previousOverflow
    }
  }, [mobileOpen, period, preset])

  const label = preset === 'custom'
    ? `${period.date_from} – ${period.date_to}`
    : OPTIONS.find((option) => option.key === preset)?.label ?? 'Хугацаа'

  const selectPreset = (nextPreset: PeriodPreset) => {
    onChange(nextPreset, periodFromPreset(nextPreset))
    setMobileOpen(false)
    triggerRef.current?.focus()
  }

  const applyCustom = () => {
    if (!draft.date_from || !draft.date_to || draft.date_from > draft.date_to) {
      setError('Эхлэх огноо нь дуусах огнооноос өмнө байна уу шалгана уу.')
      return
    }
    onChange('custom', draft)
    setMobileOpen(false)
    triggerRef.current?.focus()
  }

  return <>
    <div className="period-filter period-filter-desktop" aria-label="Хугацааны шүүлтүүр">
      <CalendarRange size={16} aria-hidden />
      <div className="period-presets">{OPTIONS.map((option) => <button type="button" key={option.key} className={preset === option.key ? 'active' : ''} onClick={() => onChange(option.key, periodFromPreset(option.key))}>{option.label}</button>)}</div>
      <label><span className="sr-only">Эхлэх огноо</span><input type="date" value={period.date_from} onChange={(event) => onChange('custom', { ...period, date_from: event.target.value })} /></label>
      <span>–</span>
      <label><span className="sr-only">Дуусах огноо</span><input type="date" value={period.date_to} onChange={(event) => onChange('custom', { ...period, date_to: event.target.value })} /></label>
    </div>
    <button ref={triggerRef} type="button" className="period-filter-mobile-trigger" onClick={() => setMobileOpen(true)} aria-haspopup="dialog" aria-expanded={mobileOpen}>
      <CalendarRange size={17} aria-hidden />
      <span><small>Хугацаа</small><strong>{label}</strong></span>
      <span aria-hidden>⌄</span>
    </button>
    {mobileOpen && <div className="period-filter-mobile-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) { setMobileOpen(false); triggerRef.current?.focus() } }}>
      <section className="period-filter-mobile-sheet" role="dialog" aria-modal="true" aria-labelledby="mobile-period-title">
        <header><div><span className="eyebrow">Хугацааны шүүлтүүр</span><h2 id="mobile-period-title">Хугацаа сонгох</h2></div><button type="button" onClick={() => { setMobileOpen(false); triggerRef.current?.focus() }} aria-label="Хаах"><X size={19} /></button></header>
        <div className="period-filter-mobile-presets">{OPTIONS.map((option) => <button type="button" key={option.key} className={draftPreset === option.key ? 'active' : ''} onClick={() => selectPreset(option.key)}><span>{option.label}</span>{draftPreset === option.key && <Check size={16} aria-hidden />}</button>)}</div>
        <div className="period-filter-mobile-custom">
          <span className="eyebrow">Өөрийн хугацаа</span>
          <div><label>Эхлэх<input type="date" value={draft.date_from} onChange={(event) => { setDraftPreset('custom'); setDraft({ ...draft, date_from: event.target.value }); setError('') }} /></label><span aria-hidden>–</span><label>Дуусах<input type="date" value={draft.date_to} onChange={(event) => { setDraftPreset('custom'); setDraft({ ...draft, date_to: event.target.value }); setError('') }} /></label></div>
          {error && <p role="alert">{error}</p>}
        </div>
        <footer><button type="button" className="secondary-action" onClick={() => { setMobileOpen(false); triggerRef.current?.focus() }}>Цуцлах</button><button type="button" className="primary-action" onClick={applyCustom}>Хэрэглэх</button></footer>
      </section>
    </div>}
  </>
}
