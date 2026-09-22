import React, { useId } from 'react'
import { DropdownSelect } from './DropdownSelect'

type BadgeColor = 'green' | 'red' | 'yellow' | 'blue' | 'purple' | 'muted'
const badgeStyles: Record<BadgeColor, string> = {
  green: 'workspace-badge-green', red: 'workspace-badge-red', yellow: 'workspace-badge-yellow',
  blue: 'workspace-badge-blue', purple: 'workspace-badge-purple', muted: 'workspace-badge-muted',
}

export function Badge({ children, color = 'muted', className = '' }: { children: React.ReactNode; color?: BadgeColor; className?: string }) {
  return <span className={`workspace-badge inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium ${badgeStyles[color]} ${className}`}>{children}</span>
}

type BtnVariant = 'primary' | 'secondary' | 'ghost' | 'danger'
type BtnSize = 'sm' | 'md' | 'lg' | 'icon'
const btnBase = 'inline-flex items-center justify-center gap-1.5 font-medium rounded-lg cursor-pointer border disabled:opacity-40 disabled:cursor-not-allowed'
const btnVariants: Record<BtnVariant, string> = {
  primary: 'workspace-btn-primary text-white', secondary: 'workspace-btn-secondary', ghost: 'workspace-btn-ghost', danger: 'workspace-btn-danger',
}
const btnSizes: Record<BtnSize, string> = {
  sm: 'text-[13px] px-3 py-1', md: 'text-sm px-3.5 py-2', lg: 'text-sm px-4 py-2.5', icon: 'h-10 w-10 p-0',
}

export function Btn({ children, variant = 'ghost', size = 'sm', className = '', type = 'button', ...props }: {
  children: React.ReactNode; variant?: BtnVariant; size?: BtnSize; className?: string
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button type={type} {...props} className={`${btnBase} ${btnVariants[variant]} ${btnSizes[size]} workspace-btn workspace-btn-${variant} workspace-btn-${size} ${className}`}>{children}</button>
}

export function Card({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <div className={`workspace-card bg-surface border border-border rounded-xl p-5 ${className}`}>{children}</div>
}

export function Input({ label, value, onChange, type = 'text', placeholder = '', fullWidth, min, max, id, className = '', helpText, error, required, disabled, ...props }: {
  label?: string; value: string; onChange: (v: string) => void; type?: string; placeholder?: string; fullWidth?: boolean
  min?: string | number; max?: string | number; id?: string; className?: string; helpText?: React.ReactNode
  error?: React.ReactNode; required?: boolean; disabled?: boolean
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange' | 'type' | 'placeholder' | 'min' | 'max' | 'id' | 'disabled' | 'required' | 'className'>) {
  const generatedId = useId()
  const inputId = id ?? generatedId
  const descriptionId = `${inputId}-description`
  const errorId = `${inputId}-error`
  const describedBy = [helpText ? descriptionId : '', error ? errorId : '', props['aria-describedby'] ?? ''].filter(Boolean).join(' ') || undefined
  return <div className={`flex flex-col gap-1.5 ${fullWidth ? 'w-full' : ''}`}>
    {label && <label htmlFor={inputId} className="text-xs text-muted font-medium">{label}{required && <span aria-hidden="true"> *</span>}</label>}
    <input {...props} id={inputId} value={value} onChange={(event) => onChange(event.target.value)} type={type} min={min} max={max} placeholder={placeholder} required={required} disabled={disabled} aria-invalid={error ? true : undefined} aria-describedby={describedBy} className={`workspace-input bg-surface2 border border-border rounded-lg px-3 py-2 text-text ${fullWidth ? 'w-full' : ''} ${error ? 'has-error' : ''} ${className}`} />
    {helpText && <span id={descriptionId} className="field-help">{helpText}</span>}
    {error && <span id={errorId} className="field-error" role="alert">{error}</span>}
  </div>
}

export function Select({ label, value, onChange, options, fullWidth = false, ...props }: {
  label?: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; fullWidth?: boolean
} & Omit<React.ComponentProps<typeof DropdownSelect>, 'label' | 'value' | 'onChange' | 'options' | 'fullWidth'>) {
  return <DropdownSelect {...props} label={label} value={value} onChange={onChange} options={options} fullWidth={fullWidth} />
}

export function Toggle({ checked, onChange, disabled = false, className = '', 'aria-label': ariaLabel = 'Тохиргоо солих' }: {
  checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; className?: string; 'aria-label'?: string
}) {
  return <button type="button" disabled={disabled} onClick={() => onChange(!checked)} className={`workspace-toggle relative cursor-pointer ${checked ? 'is-checked' : ''} ${className}`} role="switch" aria-label={ariaLabel} aria-checked={checked}>
    <span className="workspace-toggle-thumb" aria-hidden="true" />
  </button>
}

export function Modal({ title, onClose, children, className = '' }: { title: string; onClose: () => void; children: React.ReactNode; className?: string }) {
  const titleId = useId()
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70" onClick={onClose}>
    <div className={`bg-surface border border-border rounded-2xl p-7 w-full max-w-lg ${className}`} role="dialog" aria-modal="true" aria-labelledby={titleId} onClick={(event) => event.stopPropagation()}>
      <div className="flex items-center justify-between mb-5">
        <h2 id={titleId} className="text-base font-semibold">{title}</h2>
        <button type="button" onClick={onClose} aria-label="Хаах" className="bg-surface3 border-none rounded text-muted cursor-pointer px-2 py-1 text-base hover:text-text">✕</button>
      </div>
      {children}
    </div>
  </div>
}

export function PageHeader({ title, sub, children, className = '' }: { title: string; sub?: string; children?: React.ReactNode; className?: string }) {
  return <div className={`flex items-start justify-between mb-6 ${className}`}>
    <div><h1 className="page-title text-[22px] font-semibold tracking-tight">{title}</h1>{sub && <p className="page-subtitle text-[13px] text-muted mt-0.5">{sub}</p>}</div>
    {children && <div className="page-actions flex gap-2">{children}</div>}
  </div>
}
