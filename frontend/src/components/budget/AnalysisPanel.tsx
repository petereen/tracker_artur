import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import toast from 'react-hot-toast'
import { Download, Search } from 'lucide-react'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { DateInput } from '@astryxdesign/core/DateInput'
import type { ISODateString } from '@astryxdesign/core/Calendar'
import { Dialog, DialogHeader } from '@astryxdesign/core/Dialog'
import { EmptyState } from '@astryxdesign/core/EmptyState'
import { Grid } from '@astryxdesign/core/Grid'
import { HStack } from '@astryxdesign/core/HStack'
import { IconButton } from '@astryxdesign/core/IconButton'
import { ProgressBar } from '@astryxdesign/core/ProgressBar'
import { SegmentedControl, SegmentedControlItem } from '@astryxdesign/core/SegmentedControl'
import { Selector } from '@astryxdesign/core/Selector'
import { Skeleton } from '@astryxdesign/core/Skeleton'
import { Table, pixel, proportional, useTableStickyColumns } from '@astryxdesign/core/Table'
import { Text } from '@astryxdesign/core/Text'
import { VStack } from '@astryxdesign/core/VStack'
import {
  type AnalysisDimension, type AnalysisFilters, type AnalysisRow, type BudgetCapabilities, type BudgetKind, type BudgetLookups, type DrillFilters, type LedgerLine, type Measures,
  downloadBudgetAnalysis, useBudgetAnalysis, useBudgetTransactions, useBudgets,
} from '../../api/budget'
import { KIND_LABELS, ScenarioToken, VarianceDot, budgetErrorDetail, budgetErrorText, formatAmount, formatDate, formatMoney, formatPct, formatPeriod } from './shared'

type Measure = 'budgeted' | 'expected' | 'actual' | 'variance' | 'performance_pct'
const DIMENSIONS: Record<AnalysisDimension, string> = { account: 'Төсөвт данс', group: 'Дансны бүлэг', kind: 'Төрөл', project: 'Төсөл', party_group: 'Харилцагчийн бүлэг', month: 'Сар', quarter: 'Улирал', year: 'Жил' }
const TIME: AnalysisDimension[] = ['month', 'quarter', 'year']
const MEASURES: Record<Measure, string> = { budgeted: 'Төсөвлөсөн', expected: 'Байх ёстой', actual: 'Бодит', variance: 'Зөрүү', performance_pct: 'Гүйцэтгэл %' }
const dimensionOptions = (exclude?: AnalysisDimension) => (Object.keys(DIMENSIONS) as AnalysisDimension[]).filter((dim) => dim !== exclude).map((value) => ({ value, label: DIMENSIONS[value] }))

interface ListRow extends Record<string, unknown> { id: string; row: AnalysisRow }
interface PivotRow extends Record<string, unknown> { id: string; label: string; cells: Record<string, AnalysisRow> }

function bucketEnd(dim: AnalysisDimension, start: string) {
  const date = new Date(`${start}T12:00:00`)
  const months = dim === 'month' ? 1 : dim === 'quarter' ? 3 : 12
  const end = new Date(date.getFullYear(), date.getMonth() + months, 0, 12)
  return `${end.getFullYear()}-${String(end.getMonth() + 1).padStart(2, '0')}-${String(end.getDate()).padStart(2, '0')}`
}

/** Row key → drill-down filters (d161 “Гүйлгээний жагсаалт руу шилжих”). */
function drillFilters(base: AnalysisFilters, key: AnalysisRow['key']): DrillFilters {
  const filters: DrillFilters = { ...base }
  for (const [dim, value] of Object.entries(key) as Array<[AnalysisDimension, string | number]>) {
    if (dim === 'account') filters.budget_account_id = Number(value)
    if (dim === 'group') filters.budget_group_id = Number(value)
    if (dim === 'kind') filters.kind = value as BudgetKind
    if (dim === 'project') filters.project_id = Number(value)
    if (dim === 'party_group') filters.party_group_id = Number(value)
    if (TIME.includes(dim)) { filters.period_start = String(value); filters.period_end = bucketEnd(dim, String(value)) }
  }
  return filters
}

function KpiCard({ title, values, currency, note }: { title: string; values: Measures; currency: string; note: string }) {
  const pct = values.performance_pct === null ? 0 : Number(values.performance_pct)
  return <Card padding={3}>
    <VStack gap={1.5}>
      <HStack gap={1} vAlign="center" hAlign="between"><Text type="supporting">{title}</Text><VarianceDot status={values.status} /></HStack>
      <Text type="large" weight="semibold" hasTabularNumbers>{formatMoney(values.actual, currency)}</Text>
      <ProgressBar label={`${title} гүйцэтгэл`} isLabelHidden value={Math.max(0, Math.min(pct, 150))} max={150} hasValueLabel formatValueLabel={() => formatPct(values.performance_pct)}
        variant={values.status === 'unfavorable' ? 'error' : values.status === 'favorable' ? 'success' : 'accent'} />
      <Text type="supporting">Байх ёстой {formatMoney(values.expected, currency)} · Төсөв {formatMoney(values.budgeted, currency)}</Text>
      <Text type="supporting">{note}</Text>
    </VStack>
  </Card>
}

function DrillDialog({ filters, title, currency, onClose }: { filters: DrillFilters; title: string; currency: string; onClose: () => void }) {
  const result = useBudgetTransactions(filters)
  const items: LedgerLine[] = result.data?.items ?? []
  return <Dialog isOpen onOpenChange={(open) => { if (!open) onClose() }} width={980} maxHeight="88dvh">
    <DialogHeader title="Гүйлгээний жагсаалт" subtitle={title} onOpenChange={(open) => { if (!open) onClose() }} />
    <VStack gap={3} padding={4}>
      {result.isLoading ? <Skeleton height={200} />
        : result.isError ? <Banner status="error" title={budgetErrorText(result.error)} collapsible={false} />
        : <>
          <HStack gap={3} wrap="wrap">
            <Text>{result.data?.total_count ?? 0} гүйлгээ · Нийт <Text weight="semibold" hasTabularNumbers>{formatMoney(result.data?.total_amount, currency)}</Text></Text>
            <Text type="supporting">{formatPeriod(result.data?.window.date_from ?? '', result.data?.window.as_of ?? '')}</Text>
          </HStack>
          {items.length === 0 ? <EmptyState title="Гүйлгээ алга" description="Энэ хугацаанд холбогдсон санхүүгийн дансанд бичилт хийгдээгүй байна." isCompact />
            : <Table<LedgerLine>
              data={items} idKey="id" density="compact" textOverflow="truncate"
              columns={[
                { key: 'posting_date', header: 'Огноо', width: pixel(100), renderCell: (line) => formatDate(line.posting_date) },
                { key: 'document_number', header: 'Баримт', width: pixel(150), renderCell: (line) => <VStack gap={0}><Text>{line.document_number}</Text><Text type="supporting">{line.document_type}</Text></VStack> },
                { key: 'account_code', header: 'Данс', width: proportional(1), renderCell: (line) => <VStack gap={0}><Text>{line.account_code} · {line.account_name}</Text><Text type="supporting">{line.budget_account_code} · {line.budget_account_name}</Text></VStack> },
                { key: 'party_name', header: 'Харилцагч / төсөл', width: proportional(1), renderCell: (line) => <VStack gap={0}><Text>{line.party_name || '—'}</Text><Text type="supporting">{line.project_name || ''}</Text></VStack> },
                { key: 'memo', header: 'Гүйлгээний утга', width: proportional(1), renderCell: (line) => line.memo || '—' },
                { key: 'debit', header: 'Дебет', align: 'end', width: pixel(110), renderCell: (line) => <Text hasTabularNumbers>{Number(line.debit) ? formatAmount(line.debit) : ''}</Text> },
                { key: 'credit', header: 'Кредит', align: 'end', width: pixel(110), renderCell: (line) => <Text hasTabularNumbers>{Number(line.credit) ? formatAmount(line.credit) : ''}</Text> },
              ]}
            />}
          {(result.data?.total_count ?? 0) > items.length && <Text type="supporting">Сүүлийн {items.length} гүйлгээг харуулав.</Text>}
        </>}
    </VStack>
  </Dialog>
}

export function AnalysisPanel({ capabilities, lookups }: { capabilities: BudgetCapabilities; lookups: BudgetLookups }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const budgetParam = Number(searchParams.get('budget')) || undefined
  const [view, setView] = useState<'list' | 'pivot'>('list')
  const [groupBy, setGroupBy] = useState<AnalysisDimension>('account')
  const [pivotRows, setPivotRows] = useState<AnalysisDimension>('account')
  const [pivotColumns, setPivotColumns] = useState<AnalysisDimension>('month')
  const [measure, setMeasure] = useState<Measure>('actual')
  const [range, setRange] = useState<{ date_from?: string; date_to?: string; as_of?: string }>({})
  const [filters, setFilters] = useState<{ project_id?: number; party_group_id?: number; budget_group_id?: number; kind?: BudgetKind }>({})
  const [drill, setDrill] = useState<{ filters: DrillFilters; title: string } | null>(null)
  const budgets = useBudgets({ status: 'active' })
  const base: AnalysisFilters = { budget_id: budgetParam, ...range, ...filters }
  const analysis = useBudgetAnalysis({ ...base, group_by: view === 'list' ? groupBy : `${pivotRows},${pivotColumns}` })
  const data = analysis.data
  const currency = data?.budget.currency ?? lookups.currency
  const sticky = useTableStickyColumns<PivotRow>({ startKeys: ['label'], endKeys: ['total'] })

  const pivot = useMemo(() => {
    if (!data || view !== 'pivot' || data.group_by.length !== 2) return null
    const [rowDim, colDim] = data.group_by
    const columns = new Map<string, string>()
    const rows = new Map<string, PivotRow>()
    for (const row of data.rows) {
      const colKey = String(row.key[colDim]); const rowKey = String(row.key[rowDim])
      columns.set(colKey, row.labels[colDim] ?? colKey)
      const entry = rows.get(rowKey) ?? { id: rowKey, label: row.labels[rowDim] ?? rowKey, cells: {} }
      entry.cells[colKey] = row
      rows.set(rowKey, entry)
    }
    const sortedColumns = [...columns.entries()].sort(([a], [b]) => (TIME.includes(colDim) ? a.localeCompare(b) : 0))
    return { rowDim, colDim, columns: sortedColumns, rows: [...rows.values()] }
  }, [data, view])

  const selectBudget = (value: string | null) => {
    const next = new URLSearchParams(searchParams)
    if (value) next.set('budget', value); else next.delete('budget')
    setSearchParams(next, { replace: true })
    setRange({})
  }
  const exportFile = async () => {
    try { await downloadBudgetAnalysis({ ...base, budget_id: data?.budget.id, group_by: view === 'list' ? groupBy : `${pivotRows},${pivotColumns}` }, `budget-analysis-${data?.budget.number ?? ''}`) }
    catch (error) { toast.error(budgetErrorText(error)) }
  }
  const noBudget = budgetErrorDetail(analysis.error)?.code === 'budget_none'
  const drillFor = (row: AnalysisRow, dims: AnalysisDimension[]) => setDrill({ filters: drillFilters({ ...base, budget_id: data?.budget.id }, row.key), title: dims.map((dim) => row.labels[dim]).join(' · ') })
  const costTotals = data ? sumMeasures(data.totals.cogs, data.totals.expense) : null

  if (noBudget) return <EmptyState title="Төсөв үүсгээгүй байна" description="Анализ хийхийн тулд эхлээд “Төсөв” хэсгээс төсөв үүсгэнэ үү." />

  return <VStack gap={4}>
    <Card>
      <VStack gap={3}>
        <HStack gap={2} wrap="wrap" vAlign="end">
          <Selector label="Төсөв" width={300} hasSearch value={String(data?.budget.id ?? budgetParam ?? '')} onChange={selectBudget}
            options={(budgets.data?.items ?? []).map((budget) => ({ value: String(budget.id), label: `${budget.is_primary ? '★ ' : ''}${budget.number} · ${budget.name}` }))} />
          <DateInput label="Эхлэх" value={(range.date_from ?? data?.window.date_from) as ISODateString | undefined} onChange={(value) => setRange((current) => ({ ...current, date_from: value }))} format="system_date" width={150} />
          <DateInput label="Дуусах" value={(range.date_to ?? data?.window.date_to) as ISODateString | undefined} onChange={(value) => setRange((current) => ({ ...current, date_to: value }))} format="system_date" width={150} />
          <DateInput label="Байх ёстой (хүртэл)" value={(range.as_of ?? data?.window.as_of) as ISODateString | undefined} onChange={(value) => setRange((current) => ({ ...current, as_of: value }))} format="system_date" width={180}
            labelTooltip="Төсвийг энэ өдөр хүртэл өдрөөр шугаман тооцож “байх ёстой” дүнг гаргана. Анхдагч: өнөөдөр." />
          {(range.date_from || range.date_to || range.as_of) && <Button label="Хугацаа сэргээх" variant="ghost" size="sm" onClick={() => setRange({})} />}
        </HStack>
        <HStack gap={2} wrap="wrap" vAlign="end">
          {!data?.budget.project_id && lookups.projects.length > 0 && <Selector label="Төсөл" width={200} hasSearch hasClear value={filters.project_id !== undefined ? String(filters.project_id) : null}
            onChange={(value) => setFilters((current) => ({ ...current, project_id: value ? Number(value) : undefined }))}
            options={[{ value: '0', label: 'Төсөлгүй' }, ...lookups.projects.map((project) => ({ value: String(project.id), label: `${project.code} · ${project.name}` }))]} placeholder="Бүх төсөл" />}
          {lookups.party_groups.length > 0 && <Selector label="Харилцагчийн бүлэг" width={200} hasSearch hasClear value={filters.party_group_id !== undefined ? String(filters.party_group_id) : null}
            onChange={(value) => setFilters((current) => ({ ...current, party_group_id: value ? Number(value) : undefined }))}
            options={[{ value: '0', label: 'Бүлэггүй' }, ...lookups.party_groups.map((group) => ({ value: String(group.id), label: group.name }))]} placeholder="Бүх бүлэг" />}
          <Selector label="Дансны бүлэг" width={200} hasClear value={filters.budget_group_id !== undefined ? String(filters.budget_group_id) : null}
            onChange={(value) => setFilters((current) => ({ ...current, budget_group_id: value ? Number(value) : undefined }))}
            options={lookups.groups.map((group) => ({ value: String(group.id), label: group.name }))} placeholder="Бүх бүлэг" />
          <Selector label="Төрөл" width={150} hasClear value={filters.kind ?? null} onChange={(value) => setFilters((current) => ({ ...current, kind: (value || undefined) as BudgetKind | undefined }))}
            options={(Object.keys(KIND_LABELS) as BudgetKind[]).map((kind) => ({ value: kind, label: KIND_LABELS[kind] }))} placeholder="Бүгд" />
        </HStack>
      </VStack>
    </Card>

    {analysis.isError && !noBudget && <Banner status="error" title="Анализ ачаалж чадсангүй" description={budgetErrorText(analysis.error)} collapsible={false} />}
    {analysis.isLoading && <Skeleton height={260} />}

    {data && <>
      <HStack gap={2} hAlign="between" vAlign="center" wrap="wrap">
        <HStack gap={1.5} vAlign="center" wrap="wrap">
          <Text weight="semibold">{data.budget.number} · {data.budget.name}</Text>
          <ScenarioToken scenario={data.budget.scenario} />
          <Text type="supporting">{formatPeriod(data.window.date_from, data.window.date_to)} · байх ёстой: {formatDate(data.window.as_of)} хүртэл ({formatPct(data.window.elapsed_pct)} өнгөрсөн)</Text>
        </HStack>
        {capabilities.budgets.export && <Button label="Excel татах" size="sm" icon={<Download size={14} />} clickAction={exportFile} />}
      </HStack>

      <Grid columns={{ minWidth: 220 }} gap={3}>
        <KpiCard title="Орлого" values={data.totals.income} currency={currency} note="Төлөвлөгөөнөөс давж байна уу?" />
        {costTotals && <KpiCard title="Зардал (ББӨ + зардал)" values={costTotals} currency={currency} note="Төлөвлөснөөс хэтэрч байна уу?" />}
        <KpiCard title="Ашиг" values={data.totals.profit} currency={currency} note="Төлөвлөсөн ашиг биелэх боломжтой юу?" />
      </Grid>

      {data.unmapped.length > 0 && <Banner status="warning" title={`Төсөвт дансанд холбогдоогүй ${data.unmapped.length} санхүүгийн данс гүйлгээтэй байна`}
        description="Эдгээр гүйлгээ анализд тусахгүй. “Төсөвт данс” хэсэгт холбоно уу.">
        <VStack gap={1}>{data.unmapped.map((account) => <HStack key={account.erp_account_id} gap={2} hAlign="between">
          <Text>{account.code} · {account.name}</Text><Text hasTabularNumbers>{formatMoney(account.actual, currency)}</Text>
        </HStack>)}</VStack>
      </Banner>}

      <HStack gap={2} wrap="wrap" vAlign="end">
        <SegmentedControl label="Харагдац" value={view} onChange={(value) => setView(value as 'list' | 'pivot')}>
          <SegmentedControlItem value="list" label="Жагсаалт" />
          <SegmentedControlItem value="pivot" label="Динамик" />
        </SegmentedControl>
        {view === 'list' ? <Selector label="Бүлэглэх" width={200} value={groupBy} onChange={(value) => setGroupBy(value as AnalysisDimension)} options={dimensionOptions()} />
          : <>
            <Selector label="Мөр" width={180} value={pivotRows} onChange={(value) => setPivotRows(value as AnalysisDimension)} options={dimensionOptions(pivotColumns).filter((option) => !(TIME.includes(option.value) && TIME.includes(pivotColumns)))} />
            <Selector label="Багана" width={180} value={pivotColumns} onChange={(value) => setPivotColumns(value as AnalysisDimension)} options={dimensionOptions(pivotRows).filter((option) => !(TIME.includes(option.value) && TIME.includes(pivotRows)))} />
            <Selector label="Үзүүлэлт" width={170} value={measure} onChange={(value) => setMeasure(value as Measure)} options={(Object.keys(MEASURES) as Measure[]).map((value) => ({ value, label: MEASURES[value] }))} />
          </>}
      </HStack>

      <Card padding={0}>
        {view === 'list' ? (data.rows.length === 0 ? <EmptyState title="Мэдээлэл алга" description="Сонгосон хугацаа, шүүлтүүрт төсөв ч, бодит гүйлгээ ч байхгүй байна." />
          : <Table<ListRow>
            data={data.rows.map((row, index) => ({ id: `${index}`, row }))}
            idKey="id" density="compact" hasHover
            columns={[
              { key: 'label', header: DIMENSIONS[groupBy], width: proportional(2, { minWidth: 220 }), renderCell: ({ row }) => <VStack gap={0}>
                <Text weight="medium">{row.labels[groupBy]}</Text>{row.kind && groupBy !== 'kind' && <Text type="supporting">{KIND_LABELS[row.kind]}</Text>}
              </VStack> },
              { key: 'budgeted', header: 'Төсөвлөсөн', align: 'end', width: pixel(140), renderCell: ({ row }) => <Text hasTabularNumbers>{formatAmount(row.budgeted)}</Text> },
              { key: 'expected', header: 'Байх ёстой', align: 'end', width: pixel(140), renderCell: ({ row }) => <Text hasTabularNumbers>{formatAmount(row.expected)}</Text> },
              { key: 'actual', header: 'Бодит', align: 'end', width: pixel(140), renderCell: ({ row }) => <Text hasTabularNumbers weight="semibold">{formatAmount(row.actual)}</Text> },
              { key: 'variance', header: 'Зөрүү', align: 'end', width: pixel(130), renderCell: ({ row }) => <Text hasTabularNumbers>{formatAmount(row.variance)}</Text> },
              { key: 'pct', header: 'Гүйцэтгэл', align: 'end', width: pixel(110), renderCell: ({ row }) => <Text hasTabularNumbers>{formatPct(row.performance_pct)}</Text> },
              { key: 'status', header: '', width: pixel(44), renderCell: ({ row }) => <VarianceDot status={row.status} /> },
              { key: 'drill', header: '', width: pixel(52), renderCell: ({ row }) => <IconButton label="Гүйлгээ харах" tooltip="Гүйлгээний жагсаалт" icon={<Search size={14} />} size="sm" variant="ghost" onClick={() => drillFor(row, [groupBy])} /> },
            ]}
          />)
          : pivot && (pivot.rows.length === 0 ? <EmptyState title="Мэдээлэл алга" />
            : <Table<PivotRow>
              data={pivot.rows} idKey="id" density="compact" dividers="grid" plugins={{ sticky }}
              columns={[
                { key: 'label', header: `${DIMENSIONS[pivot.rowDim]} \\ ${DIMENSIONS[pivot.colDim]}`, width: proportional(2, { minWidth: 220 }), renderCell: (row) => <Text weight="medium">{row.label}</Text> },
                ...pivot.columns.map(([colKey, label]) => ({
                  key: `c:${colKey}`, header: label, align: 'end' as const, width: pixel(130),
                  renderCell: (row: PivotRow) => {
                    const cell = row.cells[colKey]
                    if (!cell) return <Text type="supporting">—</Text>
                    return <HStack gap={1} hAlign="end" vAlign="center">
                      <Text hasTabularNumbers>{measure === 'performance_pct' ? formatPct(cell.performance_pct) : formatAmount(cell[measure])}</Text>
                      {measure === 'performance_pct' && <VarianceDot status={cell.status} />}
                    </HStack>
                  },
                })),
                { key: 'total', header: measure === 'performance_pct' ? 'Нийт %' : 'Нийт', align: 'end', width: pixel(140), renderCell: (row) => {
                  const total = sumMeasures(...Object.values(row.cells))
                  return <Text hasTabularNumbers weight="semibold">{measure === 'performance_pct' ? formatPct(total.performance_pct) : formatAmount(total[measure])}</Text>
                } },
              ]}
            />)}
      </Card>
      <Text type="supporting">🟢 Төлөвлөгөөг давсан (орлого их / зардал бага) · 🟡 ±5% дотор · 🔴 Хоцорсон эсвэл хэтэрсэн. Орлого эерэг, зардал сөрөг тул зөрүү эерэг бол таатай.</Text>
    </>}

    {drill && <DrillDialog filters={drill.filters} title={drill.title} currency={currency} onClose={() => setDrill(null)} />}
  </VStack>
}

/** Add measure rows client-side (pivot totals, cost = ББӨ + зардал); status recomputed like the server. */
function sumMeasures(...values: Measures[]): Measures {
  const total = (key: 'budgeted' | 'expected' | 'actual') => values.reduce((sum, value) => sum + Number(value[key]), 0)
  const budgeted = total('budgeted'); const expected = total('expected'); const actual = total('actual')
  const variance = actual - expected
  const band = Math.abs(expected) * 0.05
  const status: Measures['status'] = expected === 0 ? (actual === 0 ? 'no_activity' : 'unplanned') : variance > band ? 'favorable' : variance < -band ? 'unfavorable' : 'on_track'
  return {
    budgeted: budgeted.toFixed(2), expected: expected.toFixed(2), actual: actual.toFixed(2), variance: variance.toFixed(2), remaining: (budgeted - actual).toFixed(2),
    performance_pct: expected === 0 ? null : ((actual / expected) * 100).toFixed(1), status,
  }
}
