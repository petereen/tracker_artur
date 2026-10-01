import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { Plus, Star } from 'lucide-react'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { EmptyState } from '@astryxdesign/core/EmptyState'
import { HStack } from '@astryxdesign/core/HStack'
import { Link } from '@astryxdesign/core/Link'
import { SegmentedControl, SegmentedControlItem } from '@astryxdesign/core/SegmentedControl'
import { Selector } from '@astryxdesign/core/Selector'
import { Skeleton } from '@astryxdesign/core/Skeleton'
import { Table, pixel, proportional } from '@astryxdesign/core/Table'
import { Text } from '@astryxdesign/core/Text'
import { TextInput } from '@astryxdesign/core/TextInput'
import { VStack } from '@astryxdesign/core/VStack'
import { type Budget, type BudgetCapabilities, type BudgetListFilters, type BudgetLookups, type BudgetScenario, useBudgets } from '../../api/budget'
import { BudgetFormDialog } from './BudgetFormDialog'
import { PERIOD_LABELS, RouterLink, SCENARIO_LABELS, ScenarioToken, StatusToken, formatMoney, formatPeriod } from './shared'

interface BudgetRow extends Record<string, unknown> { budget: Budget; id: number }
type StatusView = NonNullable<BudgetListFilters['status']>

const thisYear = new Date().getFullYear()
const yearOptions = Array.from({ length: 7 }, (_, index) => String(thisYear + 1 - index)).map((value) => ({ value, label: value }))

export function BudgetsPanel({ capabilities, lookups }: { capabilities: BudgetCapabilities; lookups: BudgetLookups }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [status, setStatus] = useState<StatusView>('active')
  const [scenario, setScenario] = useState('')
  const [year, setYear] = useState('')
  const [search, setSearch] = useState('')
  const [creating, setCreating] = useState(false)
  const filters = useMemo<BudgetListFilters>(() => ({ status, scenario: (scenario || undefined) as BudgetScenario | undefined, year: year ? Number(year) : undefined, search: search || undefined }), [scenario, search, status, year])
  const budgets = useBudgets(filters)
  const rows: BudgetRow[] = (budgets.data?.items ?? []).map((budget) => ({ id: budget.id, budget }))
  const currency = lookups.currency

  return <VStack gap={4}>
    <HStack gap={2} wrap="wrap" vAlign="end">
      <SegmentedControl label={t('budget.list.status')} value={status} onChange={(value) => setStatus(value as StatusView)}>
        <SegmentedControlItem value="active" label={t('budget.list.statusActive')} />
        <SegmentedControlItem value="draft" label={t('budget.list.statusDraft')} />
        <SegmentedControlItem value="approved" label={t('budget.list.statusApproved')} />
        <SegmentedControlItem value="archived" label={t('budget.list.statusArchived')} />
      </SegmentedControl>
      <TextInput label={t('budget.list.search')} isLabelHidden value={search} onChange={setSearch} placeholder={t('budget.list.searchPlaceholder')} hasClear width={240} />
      <Selector label={t('budget.list.scenario')} isLabelHidden options={(Object.keys(SCENARIO_LABELS) as BudgetScenario[]).map((value) => ({ value, label: SCENARIO_LABELS[value] }))}
        value={scenario || null} onChange={(value) => setScenario(value ?? '')} hasClear placeholder={t('budget.list.allScenarios')} width={220} />
      <Selector label={t('budget.list.year')} isLabelHidden options={yearOptions} value={year || null} onChange={(value) => setYear(value ?? '')} hasClear placeholder={t('budget.list.allYears')} width={140} />
      {capabilities.budgets.create && <Button label={t('budget.list.new')} variant="primary" icon={<Plus size={15} />} onClick={() => setCreating(true)} />}
    </HStack>

    <Card padding={0}>
      {budgets.isLoading ? <VStack padding={4}><Skeleton height={180} /></VStack>
        : rows.length === 0 ? <EmptyState title={t('budget.list.emptyTitle')} description={status === 'archived' ? t('budget.list.emptyArchived') : t('budget.list.emptyHint')}
          actions={capabilities.budgets.create && status !== 'archived' ? <Button label={t('budget.list.new')} variant="primary" onClick={() => setCreating(true)} /> : undefined} />
        : <Table<BudgetRow>
          data={rows}
          idKey="id"
          density="compact"
          hasHover
          columns={[
            { key: 'name', header: t('budget.list.colBudget'), width: proportional(2), renderCell: ({ budget }) => <VStack gap={0.5}>
              <HStack gap={1} vAlign="center">
                {budget.is_primary && <Star size={13} aria-label={t('budget.list.primary')} fill="currentColor" />}
                <Link as={RouterLink} href={`/erp/budget/${budget.id}`}>{budget.name}</Link>
              </HStack>
              <Text type="supporting" maxLines={1}>{budget.number}{budget.purpose ? ` · ${budget.purpose}` : ''}</Text>
            </VStack> },
            { key: 'scenario', header: t('budget.list.colScenario'), width: pixel(170), renderCell: ({ budget }) => <ScenarioToken scenario={budget.scenario} /> },
            { key: 'period', header: t('budget.list.colPeriod'), width: proportional(1), renderCell: ({ budget }) => <VStack gap={0.5}><Text>{formatPeriod(budget.start_date, budget.end_date)}</Text><Text type="supporting">{PERIOD_LABELS[budget.period_type]}{budget.project_name ? ` · ${budget.project_name}` : ''}</Text></VStack> },
            { key: 'income', header: t('budget.list.colIncome'), align: 'end', width: pixel(140), renderCell: ({ budget }) => <Text hasTabularNumbers>{formatMoney(budget.totals?.income, currency)}</Text> },
            { key: 'expense', header: t('budget.list.colExpense'), align: 'end', width: pixel(140), renderCell: ({ budget }) => <Text hasTabularNumbers>{formatMoney(Number(budget.totals?.expense ?? 0) + Number(budget.totals?.cogs ?? 0), currency)}</Text> },
            { key: 'profit', header: t('budget.list.colProfit'), align: 'end', width: pixel(140), renderCell: ({ budget }) => <Text hasTabularNumbers weight="semibold">{formatMoney(budget.totals?.profit, currency)}</Text> },
            { key: 'status', header: t('budget.list.colStatus'), width: pixel(120), renderCell: ({ budget }) => <StatusToken status={budget.status} /> },
          ]}
        />}
    </Card>
    <Text type="supporting">{t('budget.list.legend')}</Text>
    {creating && <BudgetFormDialog lookups={lookups} onClose={() => setCreating(false)} onSaved={(budget) => { setCreating(false); navigate(`/erp/budget/${budget.id}`) }} />}
  </VStack>
}
