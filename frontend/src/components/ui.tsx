import React from 'react'

// --- Badge ---
type BadgeColor = 'green' | 'red' | 'yellow' | 'blue' | 'purple' | 'muted'
const badgeStyles: Record<BadgeColor, string> = {
  green:  'bg-green-dim text-green border border-[#2a5c33]',
  red:    'bg-red-dim text-red border border-[#6b2020]',
  yellow: 'bg-yellow-dim text-yellow border border-[#5a4010]',
  blue:   'bg-accent-dim text-accent border border-[#1e4080]',
  purple: 'bg-[#2a1a4a] text-purple border border-[#4a2a7a]',
  muted:  'bg-surface3 text-muted border border-border',
}
export function Badge({ children, color = 'muted' }: { children: React.ReactNode; color?: BadgeColor }) {
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium ${badgeStyles[color]}`}>
      {children}
    </span>
  )
}

// --- Btn ---
type BtnVariant = 'primary' | 'ghost' | 'danger'
type BtnSize = 'sm' | 'lg'
const btnBase = 'inline-flex items-center gap-1.5 font-medium rounded-lg transition-all cursor-pointer border disabled:opacity-40'
const btnVariants: Record<BtnVariant, string> = {
  primary: 'bg-accent text-white border-accent hover:opacity-85 active:scale-[0.98]',
  ghost:   'bg-transparent text-muted border-border hover:bg-surface2',
  danger:  'bg-red-dim text-red border-[#6b2020] hover:opacity-85',
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
      className={`${btnBase} ${btnVariants[variant]} ${btnSizes[size]}`}>
      {children}
    </button>
  )
}

// --- Card ---
export function Card({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-surface border border-border rounded-xl p-5 ${className}`}>
      {children}
    </div>
  )
}

// --- Input ---
export function Input({ label, value, onChange, type = 'text', placeholder = '', fullWidth }: {
  label?: string; value: string; onChange: (v: string) => void;
  type?: string; placeholder?: string; fullWidth?: boolean
}) {
  return (
    <div className={`flex flex-col gap-1.5 ${fullWidth ? 'w-full' : ''}`}>
      {label && <label className="text-xs text-muted font-medium">{label}</label>}
      <input value={value} onChange={(e) => onChange(e.target.value)} type={type} placeholder={placeholder}
        className={`bg-surface2 border border-border rounded-lg px-3 py-2 text-text outline-none focus:border-accent transition-colors ${fullWidth ? 'w-full' : ''}`} />
    </div>
  )
}

// --- Select ---
export function Select({ label, value, onChange, options, fullWidth }: {
  label?: string; value: string; onChange: (v: string) => void;
  options: { value: string; label: string }[]; fullWidth?: boolean
}) {
  return (
    <div className={`flex flex-col gap-1.5 ${fullWidth ? 'w-full' : ''}`}>
      {label && <label className="text-xs text-muted font-medium">{label}</label>}
      <select value={value} onChange={(e) => onChange(e.target.value)}
        className={`bg-surface2 border border-border rounded-lg px-3 py-2 text-text outline-none focus:border-accent transition-colors ${fullWidth ? 'w-full' : ''}`}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  )
}

// --- Toggle ---
export function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div onClick={() => onChange(!checked)} className="relative cursor-pointer"
      style={{ width: 40, height: 22, borderRadius: 11, background: checked ? '#388BFD' : '#21262D', border: `1px solid ${checked ? '#388BFD' : '#30363D'}`, transition: 'background 0.2s' }}>
      <div style={{ position: 'absolute', top: 2, left: checked ? 20 : 2, width: 16, height: 16, borderRadius: '50%', background: '#fff', transition: 'left 0.2s', boxShadow: '0 1px 3px rgba(0,0,0,0.4)' }} />
    </div>
  )
}

// --- Modal ---
export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70" onClick={onClose}>
      <div className="bg-surface border border-border rounded-2xl p-7 w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
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
export function PageHeader({ title, sub, children }: { title: string; sub?: string; children?: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between mb-6">
      <div>
        <h1 className="text-[22px] font-semibold tracking-tight">{title}</h1>
        {sub && <p className="text-[13px] text-muted mt-0.5">{sub}</p>}
      </div>
      {children && <div className="flex gap-2">{children}</div>}
    </div>
  )
}
