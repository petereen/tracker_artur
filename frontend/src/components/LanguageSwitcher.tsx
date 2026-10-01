import { useTranslation } from 'react-i18next'
import { LANGUAGES, type Language } from '../locales'

export const LANGUAGE_NAMES: Record<Language, { short: string; full: string }> = {
  mn: { short: 'МН', full: 'Монгол' },
  ru: { short: 'РУ', full: 'Русский' },
  en: { short: 'EN', full: 'English' },
}

/** Signed-out language picker. Signed-in users change language in their profile. */
export function LanguageSwitcher() {
  const { t, i18n } = useTranslation()
  return <div className="language-switcher" role="group" aria-label={t('shell.language')}>
    {LANGUAGES.map((language) => <button key={language} type="button" lang={language} title={LANGUAGE_NAMES[language].full} aria-label={LANGUAGE_NAMES[language].full} aria-pressed={i18n.language === language} onClick={() => void i18n.changeLanguage(language)}>{LANGUAGE_NAMES[language].short}</button>)}
  </div>
}
