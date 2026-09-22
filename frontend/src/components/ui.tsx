import React from 'react'
import { DropdownSelect } from './DropdownSelect'

// --- Badge ---
type BadgeColor = 'green' | 'red' | 'yellow' | 'blue' | 'purple' | 'muted'
const badgeStyles: Record<BadgeColor, string> = {
  green: 'workspace-badge-green',
  red: 'workspace-badge-red',
  yellow: 'workspace-badge-yellow',
  blue: 'workspace-badge-blue',
  purple: 'workspace-badge-purple',
  muted: 'workspace-badge-muted',
}
export function Badge({ children, color = 'muted' }: { children: React.ReactNode; color?: BadgeColor }) {
  return (
    <span className={`workspace-badge inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium ${badgeStyles[color]}`}>
      {children}
    </span>
  )
}

// --- Btn ---
type BtnVariant = 'primary' | 'ghost' | 'danger'
type BtnSize = 'sm' | 'lg'
const btnBase = 'inline-flex items-center gap-1.5 font-medium rounded-lg transition-all cursor-pointer border disabled:opacity-40'
const btnVariants: Record<BtnVariant, string> = {
  primary: 'workspace-btn-primary text-white hover:opacity-85 active:scale-[0.98]',
  ghost: 'workspace-btn-ghost',
  danger: 'workspace-btn-danger hover:opacity-85',
}
const btnSizes: Record<BtnSize, string> = {
  sm: 'text-[13px] px-3 py-1',
  lg: 'text-sm px-4 py-2',
}
export function Btn({ children, variant = 'ghost', size = 'sm', onClick, disabled, type = 'button' }: {
  children: React.ReactNode; variant?: BtnVariant; size?: BtnSize;
  onClick?: () => void; disabled?: boolean; type?: 'button' | 'submit'
}) {
  return (
    <button type={type} disabled={disabled} onClick={onClick}
      className={`${btnBase} ${btnVariants[variant]} ${btnSizes[size]} workspace-btn workspace-btn-${variant} workspace-btn-${size}`}>
      {children}
    </button>
  )
}

// --- Card ---
export function Card({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`workspace-card bg-surface border border-border rounded-xl p-5 ${className}`}>
      {children}
    </div>
  )
}

// --- Input ---
export function Input({ label, value, onChange, type = 'text', placeholder = '', fullWidth, min, max }: {
  label?: string; value: string; onChange: (v: string) => void;
  type?: string; placeholder?: string; fullWidth?: boolean; min?: string | number; max?: string | number
}) {
  return (
    <div className={`flex flex-col gap-1.5 ${fullWidth ? 'w-full' : ''}`}>
      {label && <label className="text-xs text-muted font-medium">{label}</label>}
      <input value={value} onChange={(e) => onChange(e.target.value)} type={type} min={min} max={max} placeholder={placeholder}
        className={`workspace-input bg-surface2 border border-border rounded-lg px-3 py-2 text-text outline-none focus:border-accent transition-colors ${fullWidth ? 'w-full' : ''}`} />
    </div>
  )
}

// --- Select ---
export function Select({ label, value, onChange, options, fullWidth }: {
  label?: string; value: string; onChange: (v: string) => void;
  options: { value: string; label: string }[]; fullWidth?: boolean
}) {
  return (
    <DropdownSelect label={label} value={value} onChange={onChange} options={options} fullWidth />
  )
}

// --- Toggle ---
export function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div onClick={() => onChange(!checked)} className={`workspace-toggle relative cursor-pointer ${checked ? 'is-checked' : ''}`} role="switch" aria-checked={checked} tabIndex={0}
      onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onChange(!checked) } }}>
      <div className="workspace-toggle-thumb" />
    </div>
  )
}

// --- Modal ---
export function Modal({ title, onClose, children, className = '' }: { title: string; onClose: () => void; children: React.ReactNode; className?: string }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70" onClick={onClose}>
      <div className={`bg-surface border border-border rounded-2xl p-7 w-full max-w-lg ${className}`} role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-5">
          <div className="text-base font-semibold">{title}</div>
          <button onClick={onClose} className="bg-surface3 border-none rounded text-muted cursor-pointer px-2 py-1 text-base hover:text-text">✕</button>
        </div>
        {children}
      </div>
    </div>
  )
}

// --- PageHeader ---
export function PageHeader({ title, sub, children, className = '' }: { title: string; sub?: string; children?: React.ReactNode; className?: string }) {
  return (
    <div className={`flex items-start justify-between mb-6 ${className}`}>
      <div>
        <h1 className="text-[22px] font-semibold tracking-tight">{title}</h1>
        {sub && <p className="text-[13px] text-muted mt-0.5">{sub}</p>}
      </div>
      {children && <div className="flex gap-2">{children}</div>}
    </div>
  )
}
