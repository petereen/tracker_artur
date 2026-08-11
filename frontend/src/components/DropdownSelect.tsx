import { useEffect, useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { Check, ChevronDown } from 'lucide-react'

export type DropdownOption = {
  value: string
  label: string
  disabled?: boolean
}

type DropdownSelectProps = {
  value: string
  onChange: (value: string) => void
  options: DropdownOption[]
  label?: string
  ariaLabel?: string
  disabled?: boolean
  fullWidth?: boolean
  className?: string
  required?: boolean
}

export function DropdownSelect({
  value,
  onChange,
  options,
  label,
  ariaLabel,
  disabled = false,
  fullWidth = false,
  className = '',
  required = false,
}: DropdownSelectProps) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const listboxId = useId()
  const selected = options.find((option) => option.value === value)

  useEffect(() => {
    if (!open) return
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false)
        triggerRef.current?.focus()
      }
    }
    document.addEventListener('pointerdown', closeOnOutsidePointer)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsidePointer)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [open])

  const select = (option: DropdownOption) => {
    if (option.disabled) return
    onChange(option.value)
    setOpen(false)
    triggerRef.current?.focus()
  }

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      setOpen(true)
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      setOpen((current) => !current)
    }
  }

  return (
    <div ref={rootRef} className={`dropdown-select ${fullWidth ? 'dropdown-select-full' : ''} ${className}`}>
      {label && <span className="dropdown-select-label">{label}</span>}
      <button
        ref={triggerRef}
        type="button"
        className="dropdown-select-trigger"
        disabled={disabled}
        aria-label={ariaLabel || label}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-required={required || undefined}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={handleKeyDown}
      >
        <span>{selected?.label || options[0]?.label || 'Сонгох'}</span>
        <ChevronDown aria-hidden="true" size={16} strokeWidth={2.25} className={`dropdown-select-chevron ${open ? 'is-open' : ''}`} />
      </button>
      {open && (
        <div id={listboxId} className="dropdown-select-menu bg-white shadow-xl rounded-xl p-1.5 mt-2" role="listbox" aria-label={ariaLabel || label}>
          {options.map((option) => (
            <button
              key={option.value}
              type="button"
              className={`dropdown-select-option ${option.value === value ? 'is-selected' : ''}`}
              role="option"
              aria-selected={option.value === value}
              disabled={option.disabled}
              onClick={() => select(option)}
            >
              <span>{option.label}</span>
              {option.value === value && <Check aria-hidden="true" size={15} strokeWidth={2.5} />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
