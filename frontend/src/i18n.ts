import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import { LANGUAGES, resources, type Language } from './locales'

const STORAGE_KEY = 'oyuns.language'
const DEFAULT_LANGUAGE: Language = 'mn'

function isLanguage(value: unknown): value is Language {
  return typeof value === 'string' && (LANGUAGES as readonly string[]).includes(value)
}

function storedLanguage(): Language {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY)
    return isLanguage(value) ? value : DEFAULT_LANGUAGE
  } catch {
    return DEFAULT_LANGUAGE
  }
}

i18n.use(initReactI18next).init({ resources, lng: storedLanguage(), fallbackLng: DEFAULT_LANGUAGE, interpolation: { escapeValue: false } })

// Keep <html lang> accurate for screen readers and remember the choice for the
// login screen, which has no account to read a locale from.
function applyLanguage(language: string) {
  document.documentElement.lang = language
  try { window.localStorage.setItem(STORAGE_KEY, language) } catch { /* private mode: falls back to the default */ }
}
applyLanguage(i18n.language)
i18n.on('languageChanged', applyLanguage)

export default i18n
