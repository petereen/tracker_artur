import { defineTheme } from '@astryxdesign/core/theme'
import type { TenantBranding } from '../api/tenancy'
import { oyunsTheme } from './oyunsTheme'

const HEX = /^#([0-9a-f]{6})$/i

function channels(hex: string): [number, number, number] {
  const value = HEX.exec(hex)![1]
  return [0, 2, 4].map((offset) => parseInt(value.slice(offset, offset + 2), 16)) as [number, number, number]
}

function toHex(rgb: number[]) {
  return `#${rgb.map((part) => Math.round(Math.max(0, Math.min(255, part))).toString(16).padStart(2, '0')).join('')}`
}

/** Mix a colour towards white (dark-mode accents need a lighter seed). */
export function lighten(hex: string, amount: number) {
  return toHex(channels(hex).map((part) => part + (255 - part) * amount))
}

/** Readable text colour on top of ``hex`` (WCAG relative luminance). */
export function onColor(hex: string) {
  const [r, g, b] = channels(hex).map((part) => {
    const value = part / 255
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.45 ? '#111111' : '#ffffff'
}

export function isHexColor(value: string | null | undefined): value is string {
  return Boolean(value && HEX.test(value))
}

const themeCache = new Map<string, ReturnType<typeof defineTheme>>()

/** Astryx theme re-seeded with the tenant's primary colour (cached per colour). */
export function tenantTheme(primary: string | null | undefined) {
  if (!isHexColor(primary)) return oyunsTheme
  const key = primary.toLowerCase()
  if (!themeCache.has(key)) {
    themeCache.set(key, defineTheme({
      name: `tenant-${key.slice(1)}`,
      extends: oyunsTheme,
      color: { accent: [key, lighten(key, 0.35)], neutralStyle: 'cool' },
    }))
  }
  return themeCache.get(key)!
}

const BRAND_PROPERTIES = ['--color-accent', '--color-accent-soft', '--color-on-accent', '--color-tenant-secondary'] as const

/**
 * Title, favicon and the legacy CSS palette (`--color-accent` in index.css)
 * follow the tenant. Inline properties on <html> beat the stylesheet `:root`.
 */
export function applyDocumentBranding(branding: TenantBranding, defaultTitle: string) {
  if (typeof document === 'undefined') return
  // The OYUNS workspace itself keeps its product title.
  document.title = branding.name && !/^oyuns( erp)?$/i.test(branding.name.trim()) ? `${branding.name} · OYUNS ERP` : defaultTitle
  const icon = document.querySelector<HTMLLinkElement>('link[rel~="icon"]')
  if (icon && branding.favicon_url && icon.getAttribute('href') !== branding.favicon_url) icon.setAttribute('href', branding.favicon_url)
  const root = document.documentElement.style
  if (isHexColor(branding.primary_color)) {
    const primary = branding.primary_color.toLowerCase()
    root.setProperty('--color-accent', `light-dark(${primary}, ${lighten(primary, 0.35)})`)
    root.setProperty('--color-accent-soft', `color-mix(in srgb, ${primary} 12%, var(--color-surface))`)
    root.setProperty('--color-on-accent', `light-dark(${onColor(primary)}, ${onColor(lighten(primary, 0.35))})`)
  } else {
    BRAND_PROPERTIES.slice(0, 3).forEach((name) => root.removeProperty(name))
  }
  if (isHexColor(branding.secondary_color)) root.setProperty('--color-tenant-secondary', branding.secondary_color)
  else root.removeProperty('--color-tenant-secondary')
}
