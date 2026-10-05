import accounts from './accounts'
import api from './api'
import analytics from './analytics'
import assistant from './assistant'
import auth from './auth'
import budget from './budget'
import calendar from './calendar'
import catalogs from './catalogs'
import chat from './chat'
import common from './common'
import consoleMessages from './console'
import contracts from './contracts'
import core from './core'
import crm from './crm'
import files from './files'
import hr from './hr'
import legal from './legal'
import payroll from './payroll'
import payrollRun from './payrollRun'
import plans from './plans'
import profile from './profile'
import projects from './projects'
import reports from './reports'
import settings from './settings'
import shell from './shell'
import tasks from './tasks'
import today from './today'
import twoFactor from './twoFactor'
import worktime from './worktime'
import worktimeAuto from './worktimeAuto'

export { LANGUAGES, type Language } from './languages'
import type { Language } from './languages'

/**
 * Add a new domain file here; `locales.test.ts` checks ru/mn parity and key collisions. This file is the
 * registry `vite-plugins/localeSplit.ts` reads to build the per-language bundles the app loads, so the app
 * itself must not import `messageSets`/`resources` (it would ship all three languages again); tests do.
 */
export const messageSets = { accounts, api, analytics, assistant, auth, budget, calendar, catalogs, chat, common, console: consoleMessages, contracts, core, crm, files, hr, legal, payroll, payrollRun, plans, profile, projects, reports, settings, shell, tasks, today, twoFactor, worktime, worktimeAuto }

function merge(language: Language): Record<string, string> {
  return Object.assign({}, ...Object.values(messageSets).map((set) => set[language] ?? {}))
}

export const resources = {
  mn: { translation: merge('mn') },
  ru: { translation: merge('ru') },
  en: { translation: merge('en') },
}
