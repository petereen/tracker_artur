import type { CSSProperties, ReactNode } from 'react'

type BorderBeamProps = {
  children: ReactNode
  active?: boolean
  className?: string
  colorVariant?: 'colorful' | 'mono' | 'ocean' | 'sunset'
  radius?: number
  size?: 'md' | 'sm' | 'line' | 'pulse-inner' | 'pulse-outside'
  strength?: number
  theme?: 'light' | 'dark'
}

/**
 * A dependency-free, OYUNS-tuned version of the free BorderBeam pattern.
 * The beam is decorative; the wrapped surface remains the interactive target.
 */
export function BorderBeam({
  children,
  active = true,
  className = '',
  colorVariant = 'ocean',
  radius = 20,
  size = 'md',
  strength = 0.55,
  theme = 'light',
}: BorderBeamProps) {
  const style = {
    '--border-beam-radius': `${radius}px`,
    '--border-beam-strength': String(Math.max(0, Math.min(1, strength))),
  } as CSSProperties

  return (
    <div
      className={`border-beam border-beam-${size} ${active ? 'is-active' : ''} ${className}`.trim()}
      data-color={colorVariant}
      data-theme={theme}
      style={style}
    >
      <span className="border-beam-glow" aria-hidden="true" />
      <span className="border-beam-line" aria-hidden="true" />
      <div className="border-beam-content">{children}</div>
    </div>
  )
}
