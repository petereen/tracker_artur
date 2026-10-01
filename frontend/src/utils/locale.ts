import i18n from '../i18n'

const INTL_LOCALES: Record<string, string> = { mn: 'mn-MN', ru: 'ru-RU', en: 'en-US' }

/** BCP 47 tag for `Intl`/`toLocale*String`, following the current UI language. */
export function intlLocale(language: string = i18n.language): string {
  return INTL_LOCALES[language] ?? INTL_LOCALES.mn
}
