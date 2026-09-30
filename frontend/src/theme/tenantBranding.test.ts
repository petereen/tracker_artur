import { afterEach, describe, expect, it } from 'vitest'
import { DEFAULT_BRANDING } from '../api/tenancy'
import { oyunsTheme } from './oyunsTheme'
import { applyDocumentBranding, isHexColor, lighten, onColor, tenantTheme } from './tenantBranding'

describe('tenant branding', () => {
  afterEach(() => {
    document.documentElement.removeAttribute('style')
    document.title = ''
  })

  it('derives dark-mode seeds and readable text colours', () => {
    expect(lighten('#000000', 0.5)).toBe('#808080')
    expect(lighten('#2d62ec', 0)).toBe('#2d62ec')
    expect(onColor('#ffffff')).toBe('#111111')
    expect(onColor('#123456')).toBe('#ffffff')
    expect(isHexColor('#AbCdEf')).toBe(true)
    expect(isHexColor('red')).toBe(false)
  })

  it('re-seeds the Astryx theme per tenant colour and falls back to OYUNS', () => {
    expect(tenantTheme(null)).toBe(oyunsTheme)
    expect(tenantTheme('not-a-colour')).toBe(oyunsTheme)
    const acme = tenantTheme('#0F766E')
    expect(acme).not.toBe(oyunsTheme)
    expect(tenantTheme('#0f766e')).toBe(acme)
  })

  it('applies title, favicon and CSS accent to the document', () => {
    document.head.innerHTML = '<link rel="icon" href="/favicon.png" />'
    applyDocumentBranding({ ...DEFAULT_BRANDING, name: 'Acme ERP', favicon_url: '/acme.png', primary_color: '#0f766e' }, 'OYUNS')
    expect(document.title).toBe('Acme ERP · OYUNS ERP')
    expect(document.querySelector('link[rel="icon"]')?.getAttribute('href')).toBe('/acme.png')
    expect(document.documentElement.style.getPropertyValue('--color-accent')).toContain('#0f766e')

    applyDocumentBranding({ ...DEFAULT_BRANDING, name: 'OYUNS' }, 'OYUNS WORKSPACE')
    expect(document.title).toBe('OYUNS WORKSPACE')
    expect(document.documentElement.style.getPropertyValue('--color-accent')).toBe('')
  })
})
