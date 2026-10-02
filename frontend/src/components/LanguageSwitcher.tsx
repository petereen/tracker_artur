import { useEffect, useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Check } from 'lucide-react'
import { LANGUAGES, type Language } from '../locales'

export const LANGUAGE_NAMES: Record<Language, { short: string; full: string }> = {
  mn: { short: 'МН', full: 'Монгол' },
  ru: { short: 'РУ', full: 'Русский' },
  en: { short: 'EN', full: 'English' },
}

/** Set when the language was picked on the signed-out screen; the shell saves it to the profile once. */
export const LANGUAGE_CHOSEN_KEY = 'oyuns.language.chosen'

/** Translate glyph: speech bubbles with 文 / A and circular exchange arrows. */
export function TranslateIcon({ size = 20 }: { size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M3 4.5A1.5 1.5 0 0 1 4.5 3h7A1.5 1.5 0 0 1 13 4.5v5A1.5 1.5 0 0 1 11.5 11H8l-2.5 2v-2h-1A1.5 1.5 0 0 1 3 9.5z" />
    <path d="M11 13.5v1A1.5 1.5 0 0 0 12.5 16H15l2.5 2v-2h2a1.5 1.5 0 0 0 1.5-1.5v-5A1.5 1.5 0 0 0 19.5 8H17" />
    <path d="M5.4 5.6h4.2M7.5 5v.6m1.6 0c-.3 1.6-1.4 2.6-2.8 3.1m.4-2.6c.4.9 1.3 1.8 2.4 2.1" strokeWidth="1.2" />
    <path d="m14.6 14.8 1.6-3.8 1.6 3.8m-2.6-1.2h2" strokeWidth="1.2" />
    <path d="M20.5 19.8a3.3 3.3 0 0 1-3-1.2M3.6 20.7a3.3 3.3 0 0 0 3 1.1" strokeWidth="1.2" className="translate-icon-arrows" />
  </svg>
}

/** Signed-out language picker. Signed-in users change language in their profile. */
export function LanguageSwitcher() {
  const { t, i18n } = useTranslation()
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuId = useId()

  useEffect(() => {
    if (!open) return
    const onPointer = (event: PointerEvent) => { if (!rootRef.current?.contains(event.target as Node)) setOpen(false) }
    const onKey = (event: globalThis.KeyboardEvent) => { if (event.key === 'Escape') { setOpen(false); triggerRef.current?.focus() } }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('pointerdown', onPointer); document.removeEventListener('keydown', onKey) }
  }, [open])

  const choose = (language: Language) => {
    try { window.localStorage.setItem(LANGUAGE_CHOSEN_KEY, '1') } catch { /* private mode: choice just isn't synced to the profile */ }
    void i18n.changeLanguage(language)
    setOpen(false)
    triggerRef.current?.focus()
  }

  const onTriggerKey = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'ArrowDown') { event.preventDefault(); setOpen(true) }
  }

  return <div ref={rootRef} className="language-menu">
    <button ref={triggerRef} type="button" className="language-menu-trigger" aria-label={t('shell.language')} title={t('shell.language')} aria-haspopup="listbox" aria-expanded={open} aria-controls={menuId} onClick={() => setOpen((current) => !current)} onKeyDown={onTriggerKey}>
      <TranslateIcon />
    </button>
    {open && <div id={menuId} className="language-menu-list" role="listbox" aria-label={t('shell.language')}>
      {LANGUAGES.map((language) => <button key={language} type="button" role="option" lang={language} aria-selected={i18n.language === language} className={`language-menu-option ${i18n.language === language ? 'is-selected' : ''}`} onClick={() => choose(language)}>
        <span>{LANGUAGE_NAMES[language].full}</span>
        {i18n.language === language && <Check aria-hidden="true" size={15} strokeWidth={2.5} />}
      </button>)}
    </div>}
  </div>
}
