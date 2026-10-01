import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
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

interface Shortcut { label: string; icon: LucideIcon; to?: string; run?: () => void }

const SHORTCUTS: Record<ShortcutKey, Shortcut> = {
  search: { label: 'Хайх', icon: Search, run: openGlobalSearch },
  assistant: { label: 'OYUNS AI', icon: Sparkles, run: openAssistant },
  tasks: { label: 'Даалгавар', icon: CheckSquare2, to: '/tasks' },
  calendar: { label: 'Календарь', icon: CalendarDays, to: '/calendar' },
  reports: { label: 'Тайлан', icon: FileCheck2, to: '/reports' },
  worktime: { label: 'Ажлын цаг', icon: ScanLine, to: '/worktime' },
  chat: { label: 'Чат', icon: MessageCircle, to: '/chat' },
  projects: { label: 'Төсөл', icon: BriefcaseBusiness, to: '/projects' },
  plans: { label: 'Төлөвлөгөө', icon: Goal, to: '/plans' },
  contracts: { label: 'Гэрээ', icon: FileSignature, to: '/contracts' },
  hr: { label: 'Хүний нөөц', icon: UserRoundCog, to: '/hr' },
  files: { label: 'Файлууд', icon: FolderArchive, to: '/company-files' },
  analytics: { label: 'Статистик', icon: BarChart3, to: '/analytics' },
  crm: { label: 'CRM', icon: Handshake, to: '/erp/crm' },
  budget: { label: 'Төсөв', icon: PiggyBank, to: '/erp/budget' },
  payroll: { label: 'Цалин', icon: Calculator, to: '/erp/payroll' },
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
  const navigate = useNavigate()
  const available = useAvailableShortcuts()
  const chosen = (settings.shortcuts ?? DEFAULT_QUICK_ACTIONS_SETTINGS.shortcuts).filter((key) => available.includes(key))
  return (
    <section className="today-widget today-quick-actions" aria-label="Шуурхай үйлдэл">
      <WidgetHeader icon={Zap} title="Шуурхай үйлдэл" />
      {chosen.length ? (
        <nav className="today-quick-grid" aria-label="Шуурхай үйлдлүүд">
          {chosen.map((key) => {
            const { label, icon: Icon, to, run } = SHORTCUTS[key]
            return (
              <button key={key} type="button" className="today-quick-action" onClick={() => (run ? run() : to && navigate(to))}>
                <Icon size={17} aria-hidden /><span>{label}</span>
              </button>
            )
          })}
        </nav>
      ) : <p className="today-widget-empty">Тохиргооноос товчлол сонгоно уу.</p>}
    </section>
  )
}

export function QuickActionsSettingsForm({ settings, onChange }: WidgetSettingsProps<QuickActionsSettings>) {
  const available = useAvailableShortcuts()
  return (
    <CheckboxList label="Товчлолууд" description="Хандах эрхтэй модулиуд л харагдана." density="compact" value={(settings.shortcuts ?? []).filter((key) => available.includes(key))} onChange={(values) => onChange({ shortcuts: SHORTCUT_KEYS.filter((key) => values.includes(key)) })}>
      {available.map((key) => <CheckboxListItem key={key} value={key} label={SHORTCUTS[key].label} />)}
    </CheckboxList>
  )
}
