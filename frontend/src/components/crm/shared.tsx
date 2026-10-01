import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Search, X } from 'lucide-react'
import { useCRMParties, type CRMParty, type CRMStatusCategory } from '../../api/crm'
import i18n from '../../i18n'
import { labelMap } from '../../utils/labelMap'
import { intlLocale } from '../../utils/locale'

export function crmErrorText(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((item) => String(item?.msg || '').replace(/^Value error, /, '')).filter(Boolean).join('; ') || i18n.t('crm.error.invalid')
  if (detail && typeof detail === 'object' && 'message' in detail && typeof (detail as { message: unknown }).message === 'string') return (detail as { message: string }).message
  return i18n.t('crm.error.failed')
}

export function crmErrorCode(error: unknown): string | undefined {
  const detail = (error as { response?: { data?: { detail?: { code?: string } } } })?.response?.data?.detail
  return detail && typeof detail === 'object' ? detail.code : undefined
}

const dateTimeOptions: Intl.DateTimeFormatOptions = { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }
const dateOptions: Intl.DateTimeFormatOptions = { year: 'numeric', month: '2-digit', day: '2-digit' }

export const formatDateTime = (value: string | null | undefined) => (value ? new Intl.DateTimeFormat(intlLocale(), dateTimeOptions).format(new Date(value)) : '—')
export const formatDate = (value: string | null | undefined) => (value ? new Intl.DateTimeFormat(intlLocale(), dateOptions).format(new Date(value.length === 10 ? `${value}T12:00:00` : value)) : '—')
export function formatMoney(value: string | number | null | undefined, currency = 'MNT') {
  if (value === null || value === undefined || value === '') return '—'
  const amount = Number(value)
  return Number.isFinite(amount) ? `${amount.toLocaleString(intlLocale(), { maximumFractionDigits: 2 })} ${currency === 'MNT' ? '₮' : currency}` : String(value)
}

/** ISO timestamp → value for <input type="datetime-local"> in the browser's zone. */
export function toLocalInput(value: string | null | undefined) {
  if (!value) return ''
  const date = new Date(value)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}
export const fromLocalInput = (value: string) => (value ? new Date(value).toISOString() : null)

export const CATEGORY_LABELS = labelMap<CRMStatusCategory>('crm.category', ['open', 'in_progress', 'waiting', 'done', 'cancelled'])

export function StatusChip({ name, color }: { name: string; color: string }) {
  return <span className="crm-status-chip" style={{ '--crm-status': color } as CSSProperties}>{name}</span>
}

export function Field({ label, children, wide, hint }: { label: string; children: ReactNode; wide?: boolean; hint?: ReactNode }) {
  return <label className={`crm-field ${wide ? 'hr-form-wide' : ''}`}><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>
}

export function TextInput({ value, onChange, type = 'text', placeholder, required, disabled, min, step }: { value: string; onChange: (value: string) => void; type?: string; placeholder?: string; required?: boolean; disabled?: boolean; min?: string; step?: string }) {
  return <input className="crm-input" value={value} type={type} placeholder={placeholder} required={required} disabled={disabled} min={min} step={step} onChange={(event) => onChange(event.target.value)} />
}

export function TextArea({ value, onChange, rows = 3, placeholder }: { value: string; onChange: (value: string) => void; rows?: number; placeholder?: string }) {
  return <textarea className="crm-input" value={value} rows={rows} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
}

export function NativeSelect({ value, onChange, options, placeholder = '—' }: { value: string; onChange: (value: string) => void; options: Array<{ value: string; label: string }>; placeholder?: string }) {
  return <select className="crm-input" value={value} onChange={(event) => onChange(event.target.value)}>
    <option value="">{placeholder}</option>
    {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
  </select>
}

export function CheckField({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return <label className="crm-check"><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /><span>{label}</span></label>
}

/** Searchable customer picker backed by the paged parties endpoint. */
export function PartyPicker({ value, label, onChange, placeholder, excludeId }: { value: number | null; label: string | null; onChange: (party: CRMParty | null) => void; placeholder?: string; excludeId?: number }) {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const parties = useCRMParties({ search: query || undefined, page_size: 20, is_active: true }, open)
  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])
  const options = (parties.data?.items ?? []).filter((party) => party.id !== excludeId)
  return <div className="crm-picker" ref={root}>
    {value && !open
      ? <div className="crm-picker-value"><button type="button" onClick={() => setOpen(true)}>{label || `#${value}`}</button><button type="button" aria-label={t('crm.picker.clear')} onClick={() => onChange(null)}><X size={14} /></button></div>
      : <label className="crm-picker-search"><Search size={14} /><input autoFocus={open} value={query} placeholder={placeholder ?? t('crm.picker.search')} onFocus={() => setOpen(true)} onChange={(event) => { setQuery(event.target.value); setOpen(true) }} /></label>}
    {open && <div className="crm-picker-list" role="listbox">
      {parties.isLoading && <div className="hr-muted">{t('crm.common.loading')}</div>}
      {!parties.isLoading && !options.length && <div className="hr-muted">{t('crm.picker.notFound')}</div>}
      {options.map((party) => <button type="button" role="option" aria-selected={party.id === value} key={party.id} onClick={() => { onChange(party); setOpen(false); setQuery('') }}>
        <strong>{party.name}</strong><small>{party.code}{party.tax_id ? ` · ${t('crm.common.taxIdShort', { id: party.tax_id })}` : ''}</small>
      </button>)}
    </div>}
  </div>
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return <><h3 className="hr-form-section">{title}</h3><div className="hr-form-grid">{children}</div></>
}
