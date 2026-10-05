import i18n, { type BackendModule } from 'i18next'
import { initReactI18next } from 'react-i18next'
import { LANGUAGES, type Language } from './locales/languages'

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

// Each language is its own chunk (built by `vite-plugins/localeSplit.ts`), fetched only when it is
// the active language, so the app no longer downloads all three catalogues on first load.
const catalogues: Record<Language, () => Promise<{ default: Record<string, string> }>> = {
  mn: () => import('virtual:oyuns-locale/mn'),
  ru: () => import('virtual:oyuns-locale/ru'),
  en: () => import('virtual:oyuns-locale/en'),
}

const catalogueBackend: BackendModule = {
  type: 'backend',
  init() {},
  read(language, _namespace, callback) {
    if (!isLanguage(language)) return callback(new Error(`Unsupported language: ${language}`), null)
    catalogues[language]().then((module) => callback(null, module.default), (error) => callback(error, null))
  },
}

/**
 * Resolves once the active language is loaded; `main.tsx` waits for it before the first render.
 * Switching later (`i18n.changeLanguage`) loads the new catalogue first, then flips.
 * No fallback language: every key exists in all three (checked by `locales.test.ts`), and a
 * fallback would make i18next download Mongolian alongside the chosen language.
 */
export const i18nReady = i18n.use(catalogueBackend).use(initReactI18next).init({
  lng: storedLanguage(),
  fallbackLng: false,
  supportedLngs: [...LANGUAGES],
  interpolation: { escapeValue: false },
  react: { useSuspense: false },
})

// Keep <html lang> accurate for screen readers and remember the choice for the
// login screen, which has no account to read a locale from.
function applyLanguage(language: string) {
  document.documentElement.lang = language
  try { window.localStorage.setItem(STORAGE_KEY, language) } catch { /* private mode: falls back to the default */ }
}
applyLanguage(i18n.language)
i18n.on('languageChanged', applyLanguage)

export default i18n
