import i18n from 'i18next'
import { defineMessages } from './define'
import { docsEn } from './docs/en'
import { docsMn } from './docs/mn'
import { docsRu } from './docs/ru'

/**
 * In-app documentation (`/docs`). Articles are long Markdown bodies, so each language lives in
 * its own file under `docs/`, and the set is not part of `messageSets`: it ships in the docs
 * route chunk instead of the i18n bundle every page loads. `locales.test.ts` still checks it.
 */
const docs = defineMessages({ mn: docsMn, ru: docsRu, en: docsEn })
export default docs

/** Adds the docs strings to i18n; called when the docs page module loads. */
export function registerDocsMessages() {
  for (const language of ['mn', 'ru', 'en'] as const) i18n.addResourceBundle(language, 'translation', docs[language], true, false)
}
