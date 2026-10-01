import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  BarChart3, BriefcaseBusiness, Calculator, CalendarDays, CheckSquare2, FileCheck2, FileSignature, FolderArchive, Goal,
  Handshake, MessageCircle, PiggyBank, ScanLine, Search, Sparkles, UserRoundCog, Zap, type LucideIcon,
} from 'lucide-react'
import { CheckboxList, CheckboxListItem } from '@astryxdesign/core/CheckboxList'
import { useBudgetCapabilities } from '../../../api/budget'
import { useCRMCapabilities } from '../../../api/crm'
import { useERPMetadata } from '../../../api/enterprise'
import { isFeatureEnabled, useTenantContext } from '../../../api/tenancy'
import { openAssistant, openGlobalSearch } from '../../../platform/app-events'
import { EMPTY_ROLES, useAuthStore } from '../../../store/auth'
import type { WidgetProps, WidgetSettingsProps } from '../types'
import { WidgetHeader } from './shared'

type ShortcutKey =
  | 'search' | 'assistant' | 'tasks' | 'calendar' | 'reports' | 'worktime' | 'chat' | 'projects' | 'plans'
  | 'contracts' | 'hr' | 'files' | 'analytics' | 'crm' | 'budget' | 'payroll'

interface Shortcut { icon: LucideIcon; to?: string; run?: () => void }

const SHORTCUTS: Record<ShortcutKey, Shortcut> = {
  search: { icon: Search, run: openGlobalSearch },
  assistant: { icon: Sparkles, run: openAssistant },
  tasks: { icon: CheckSquare2, to: '/tasks' },
  calendar: { icon: CalendarDays, to: '/calendar' },
  reports: { icon: FileCheck2, to: '/reports' },
  worktime: { icon: ScanLine, to: '/worktime' },
  chat: { icon: MessageCircle, to: '/chat' },
  projects: { icon: BriefcaseBusiness, to: '/projects' },
  plans: { icon: Goal, to: '/plans' },
  contracts: { icon: FileSignature, to: '/contracts' },
  hr: { icon: UserRoundCog, to: '/hr' },
  files: { icon: FolderArchive, to: '/company-files' },
  analytics: { icon: BarChart3, to: '/analytics' },
  crm: { icon: Handshake, to: '/erp/crm' },
  budget: { icon: PiggyBank, to: '/erp/budget' },
  payroll: { icon: Calculator, to: '/erp/payroll' },
}
const SHORTCUT_KEYS = Object.keys(SHORTCUTS) as ShortcutKey[]
const PAYROLL_ROLES = ['admin', 'hr']

export interface QuickActionsSettings { shortcuts: ShortcutKey[] }
export const DEFAULT_QUICK_ACTIONS_SETTINGS: QuickActionsSettings = { shortcuts: ['search', 'assistant', 'tasks', 'calendar', 'reports', 'chat'] }

/** Shortcuts the viewer may actually open — the same gates as the sidebar. */
function useAvailableShortcuts(): ShortcutKey[] {
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES)
  const signedIn = useAuthStore((state) => Boolean(state.actor))
  const tenant = useTenantContext(signedIn)
  const crm = useCRMCapabilities(signedIn)
  const budget = useBudgetCapabilities(signedIn)
  const canPayroll = roles.some((role) => PAYROLL_ROLES.includes(role))
  const erp = useERPMetadata(signedIn && canPayroll)
  return useMemo(() => SHORTCUT_KEYS.filter((key) => {
    if (key === 'contracts') return isFeatureEnabled(tenant.data, 'contracts')
    if (key === 'assistant') return isFeatureEnabled(tenant.data, 'ai_assistant')
    if (key === 'crm') return Boolean(crm.data?.module_enabled && (crm.data.activities.view || crm.data.parties.view))
    if (key === 'budget') return Boolean(budget.data?.module_enabled && budget.data.budgets.view)
    if (key === 'payroll') return Boolean(canPayroll && erp.data?.modules.payroll)
    return true
  }), [budget.data, canPayroll, crm.data, erp.data, tenant.data])
}

export function QuickActionsWidget({ settings }: WidgetProps<QuickActionsSettings>) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const available = useAvailableShortcuts()
  const chosen = (settings.shortcuts ?? DEFAULT_QUICK_ACTIONS_SETTINGS.shortcuts).filter((key) => available.includes(key))
  return (
    <section className="today-widget today-quick-actions" aria-label={t('today.widget.quick-actions.title')}>
      <WidgetHeader icon={Zap} title={t('today.widget.quick-actions.title')} />
      {chosen.length ? (
        <nav className="today-quick-grid" aria-label={t('today.quick.nav')}>
          {chosen.map((key) => {
            const { icon: Icon, to, run } = SHORTCUTS[key]
            return (
              <button key={key} type="button" className="today-quick-action" onClick={() => (run ? run() : to && navigate(to))}>
                <Icon size={17} aria-hidden /><span>{t(`today.quick.${key}`)}</span>
              </button>
            )
          })}
        </nav>
      ) : <p className="today-widget-empty">{t('today.quick.empty')}</p>}
    </section>
  )
}

export function QuickActionsSettingsForm({ settings, onChange }: WidgetSettingsProps<QuickActionsSettings>) {
  const { t } = useTranslation()
  const available = useAvailableShortcuts()
  return (
    <CheckboxList label={t('today.quick.shortcuts')} description={t('today.quick.shortcutsHint')} density="compact" value={(settings.shortcuts ?? []).filter((key) => available.includes(key))} onChange={(values) => onChange({ shortcuts: SHORTCUT_KEYS.filter((key) => values.includes(key)) })}>
      {available.map((key) => <CheckboxListItem key={key} value={key} label={t(`today.quick.${key}`)} />)}
    </CheckboxList>
  )
}
