import type { ReactNode } from 'react'
import { BarChart3, BookOpen, Wallet } from 'lucide-react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { Banner } from '@astryxdesign/core/Banner'
import { Link } from '@astryxdesign/core/Link'
import { Skeleton } from '@astryxdesign/core/Skeleton'
import { Tab, TabList } from '@astryxdesign/core/TabList'
import { VStack } from '@astryxdesign/core/VStack'
import { useBudgetCapabilities, useBudgetLookups } from '../api/budget'
import { useActor } from '../api/enterprise'
import { AccountsPanel } from '../components/budget/AccountsPanel'
import { AnalysisPanel } from '../components/budget/AnalysisPanel'
import { BudgetEditor } from '../components/budget/BudgetEditor'
import { BudgetsPanel } from '../components/budget/BudgetsPanel'
import { RouterLink, budgetErrorText } from '../components/budget/shared'

type BudgetTab = 'budgets' | 'analysis' | 'accounts'
const TAB_PATHS: Record<BudgetTab, string> = { budgets: '/erp/budget', analysis: '/erp/budget/analysis', accounts: '/erp/budget/accounts' }
const TAB_LABELS: Record<BudgetTab, string> = { budgets: 'Төсөв', analysis: 'Төсвийн анализ', accounts: 'Төсөвт данс' }
const TAB_ICONS: Record<BudgetTab, ReactNode> = { budgets: <Wallet size={15} />, analysis: <BarChart3 size={15} />, accounts: <BookOpen size={15} /> }

/** Төсөв, гүйцэтгэл (Dayansoft d161): plan → budget → actual → comparison → decision. */
export function BudgetWorkspacePage() {
  const capabilities = useBudgetCapabilities()
  const actor = useActor()
  const location = useLocation()
  const navigate = useNavigate()
  const { budgetId } = useParams()
  const caps = capabilities.data
  const canUse = Boolean(caps && (caps.budgets.view || caps.settings.view))
  const lookups = useBudgetLookups(canUse)

  if (capabilities.isLoading || (canUse && lookups.isLoading)) return <Skeleton height={320} />
  if (capabilities.isError) return <Banner status="error" title={budgetErrorText(capabilities.error)} collapsible={false} />
  if (!caps || !canUse) return <Banner status="warning" title="Төсөв модульд хандах эрх танд олгогдоогүй байна" description="Системийн админаас “Accountant” ERP эрх эсвэл төсвийн эрх хүснэ үү." collapsible={false} />
  if (!lookups.data) return <Banner status="error" title={lookups.isError ? budgetErrorText(lookups.error) : 'Ачаалж байна…'} collapsible={false} />

  const tab: BudgetTab = location.pathname.startsWith(TAB_PATHS.analysis) ? 'analysis' : location.pathname.startsWith(TAB_PATHS.accounts) ? 'accounts' : 'budgets'
  const visibleTabs = (['budgets', 'analysis', 'accounts'] as BudgetTab[]).filter((key) => (key === 'accounts' ? caps.settings.view : caps.budgets.view))
  const isAdmin = Boolean(actor.data?.roles?.includes('admin'))

  return <VStack gap={4}>
    {!caps.module_enabled && <Banner status="info" collapsible={false} title="Төсөв модуль цэсэнд идэвхжээгүй байна"
      description={isAdmin ? undefined : 'Админ “Модуль ба боломжууд” хэсгээс идэвхжүүлнэ.'}
      endContent={isAdmin ? <Link as={RouterLink} href="/administration/organization/modules">Модуль ба боломжууд</Link> : undefined} />}
    <TabList value={tab} onChange={(value) => navigate(TAB_PATHS[value as BudgetTab])} hasDivider role="tablist">
      {visibleTabs.map((key) => <Tab key={key} value={key} label={TAB_LABELS[key]} icon={TAB_ICONS[key]} />)}
    </TabList>
    {tab === 'budgets' && caps.budgets.view && (budgetId ? <BudgetEditor budgetId={Number(budgetId)} capabilities={caps} lookups={lookups.data} /> : <BudgetsPanel capabilities={caps} lookups={lookups.data} />)}
    {tab === 'analysis' && caps.budgets.view && <AnalysisPanel capabilities={caps} lookups={lookups.data} />}
    {tab === 'accounts' && caps.settings.view && <AccountsPanel capabilities={caps} lookups={lookups.data} />}
  </VStack>
}
