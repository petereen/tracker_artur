import accounts from './accounts'
import analytics from './analytics'
import assistant from './assistant'
import auth from './auth'
import budget from './budget'
import calendar from './calendar'
import chat from './chat'
import common from './common'
import contracts from './contracts'
import core from './core'
import crm from './crm'
import files from './files'
import hr from './hr'
import payroll from './payroll'
import plans from './plans'
import profile from './profile'
import projects from './projects'
import reports from './reports'
import shell from './shell'
import tasks from './tasks'
import today from './today'
import worktime from './worktime'

export const LANGUAGES = ['mn', 'ru', 'en'] as const
export type Language = (typeof LANGUAGES)[number]

/** Add a new domain file here; `locales.test.ts` checks ru/mn parity and key collisions. */
export const messageSets = { accounts, analytics, assistant, auth, budget, calendar, chat, common, contracts, core, crm, files, hr, payroll, plans, profile, projects, reports, shell, tasks, today, worktime }

function merge(language: Language): Record<string, string> {
  return Object.assign({}, ...Object.values(messageSets).map((set) => set[language] ?? {}))
}

export const resources = {
  mn: { translation: merge('mn') },
  ru: { translation: merge('ru') },
  en: { translation: merge('en') },
}
