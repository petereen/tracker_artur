import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, ArrowUpDown, BarChart3, Copy, Divide, Download, MoreHorizontal, Plus, Star, Trash2, Upload } from 'lucide-react'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { DropdownMenu } from '@astryxdesign/core/DropdownMenu'
import { EmptyState } from '@astryxdesign/core/EmptyState'
import { Grid } from '@astryxdesign/core/Grid'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { IconButton } from '@astryxdesign/core/IconButton'
import { NumberInput } from '@astryxdesign/core/NumberInput'
import { Selector } from '@astryxdesign/core/Selector'
import { Skeleton } from '@astryxdesign/core/Skeleton'
import { Table, pixel, proportional, useTableStickyColumns } from '@astryxdesign/core/Table'
import { Text } from '@astryxdesign/core/Text'
import { TextInput } from '@astryxdesign/core/TextInput'
import { VStack } from '@astryxdesign/core/VStack'
import {
  type BudgetCapabilities, type BudgetDetail, type BudgetKind, type BudgetLookups,
  downloadBudgetWorkbook, useBudget, useBudgetAction, useDeleteBudget, useSaveBudgetLines, useSetPrimaryBudget,
} from '../../api/budget'
import { BudgetFormDialog } from './BudgetFormDialog'
import { CopyBudgetDialog, ImportBudgetDialog, SplitDialog } from './BudgetDialogs'
import {
  KIND_LABELS, PERIOD_LABELS, RouterLink, ScenarioToken, StatusToken, applySign, budgetErrorDetail, budgetErrorText,
  formatAmount, formatMoney, formatPeriod, signOk, splitEvenly,
} from './shared'

interface EditRow { key: string; budget_account_id: number; project_id: number | null; party_group_id: number | null; note: string | null; amounts: Record<string, number> }
interface GridRow extends Record<string, unknown> { id: string; row?: EditRow; summary?: { label: string; kinds: BudgetKind[] | 'all' } }

const rowKey = (accountId: number, projectId: number | null, groupId: number | null) => `${accountId}:${projectId ?? 0}:${groupId ?? 0}`
const toEditRows = (detail: BudgetDetail): EditRow[] => detail.rows.map((row) => ({
  key: rowKey(row.budget_account_id, row.project_id, row.party_group_id), budget_account_id: row.budget_account_id, project_id: row.project_id,
  party_group_id: row.party_group_id, note: row.note, amounts: Object.fromEntries(Object.entries(row.amounts).map(([start, value]) => [start, Number(value)])),
}))
const sum = (values: number[]) => Math.round(values.reduce((total, value) => total + value, 0) * 100) / 100
const serialize = (rows: EditRow[]) => JSON.stringify(rows.map((row) => [row.key, row.note, Object.entries(row.amounts).filter(([, value]) => value).sort()]))

function Stat({ label, value, tone }: { label: string; value: string; tone?: 'accent' }) {
  return <Card padding={3}><VStack gap={0.5}><Text type="supporting">{label}</Text><Text type="large" weight="semibold" hasTabularNumbers color={tone === 'accent' ? 'accent' : undefined}>{value}</Text></VStack></Card>
}

export function BudgetEditor({ budgetId, capabilities, lookups }: { budgetId: number; capabilities: BudgetCapabilities; lookups: BudgetLookups }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const query = useBudget(budgetId)
  const detail = query.data
  const saveLines = useSaveBudgetLines(budgetId)
  const action = useBudgetAction()
  const setPrimary = useSetPrimaryBudget()
  const remove = useDeleteBudget()
  const [rows, setRows] = useState<EditRow[]>([])
  const [baseline, setBaseline] = useState('')
  const [dialog, setDialog] = useState<null | 'info' | 'copy' | 'import'>(null)
  const [splitting, setSplitting] = useState<EditRow | null>(null)
  const [newRow, setNewRow] = useState({ account: '', project: '', group: '', note: '' })
  const sticky = useTableStickyColumns<GridRow>({ startKeys: ['account'], endKeys: ['total'] })

  useEffect(() => {
    if (!detail) return
    const next = toEditRows(detail)
    setRows(next)
    setBaseline(serialize(next))
  }, [detail])

  const accounts = useMemo(() => new Map(lookups.accounts.map((account) => [account.id, account])), [lookups.accounts])
  const projects = useMemo(() => new Map(lookups.projects.map((project) => [project.id, `${project.code} · ${project.name}`])), [lookups.projects])
  const partyGroups = useMemo(() => new Map(lookups.party_groups.map((group) => [group.id, group.name])), [lookups.party_groups])
  const columns = detail?.columns ?? []
  const kindOf = (row: EditRow): BudgetKind => accounts.get(row.budget_account_id)?.kind ?? 'other'
  const dirty = serialize(rows) !== baseline
  const editable = Boolean(detail && detail.status === 'draft' && capabilities.budgets.edit)
  const hasProjectColumn = !detail?.project_id && (rows.some((row) => row.project_id) || lookups.projects.length > 0)
  const hasGroupColumn = rows.some((row) => row.party_group_id) || lookups.party_groups.length > 0

  const violations = useMemo(() => rows.flatMap((row) => Object.entries(row.amounts).filter(([, value]) => !signOk(kindOf(row), value)).map(([start]) => `${row.key}|${start}`)), [rows, accounts])
  const totalsBy = (kinds: BudgetKind[] | 'all', start?: string) => sum(rows.filter((row) => kinds === 'all' || kinds.includes(kindOf(row)))
    .flatMap((row) => (start ? [row.amounts[start] ?? 0] : Object.values(row.amounts))))
  const hasOther = rows.some((row) => kindOf(row) === 'other')

  if (query.isLoading) return <Skeleton height={320} />
  if (query.isError || !detail) return <Banner status="error" title={t('budget.editor.notFound')} description={budgetErrorText(query.error)} collapsible={false} />

  const updateRow = (key: string, patch: (row: EditRow) => EditRow) => setRows((current) => current.map((row) => (row.key === key ? patch(row) : row)))
  const setAmount = (key: string, start: string, value: number | null) => updateRow(key, (row) => ({ ...row, amounts: { ...row.amounts, [start]: value ?? 0 } }))
  const fixSigns = () => setRows((current) => current.map((row) => ({ ...row, amounts: Object.fromEntries(Object.entries(row.amounts).map(([start, value]) => [start, applySign(kindOf(row), value)])) })))
  const addRow = () => {
    const accountId = Number(newRow.account)
    if (!accountId) return
    const projectId = newRow.project ? Number(newRow.project) : null
    const groupId = newRow.group ? Number(newRow.group) : null
    const key = rowKey(accountId, projectId, groupId)
    if (rows.some((row) => row.key === key)) { toast.error(t('budget.editor.duplicateRow')); return }
    setRows((current) => [...current, { key, budget_account_id: accountId, project_id: projectId, party_group_id: groupId, note: newRow.note || null, amounts: {} }])
    setNewRow({ account: '', project: '', group: '', note: '' })
  }
  const save = async () => {
    try {
      await saveLines.mutateAsync({
        version: detail.version,
        rows: rows.map((row) => ({ budget_account_id: row.budget_account_id, project_id: row.project_id, party_group_id: row.party_group_id, note: row.note,
          amounts: Object.fromEntries(Object.entries(row.amounts).filter(([, value]) => value).map(([start, value]) => [start, String(value)])) })),
      })
      toast.success(t('budget.editor.saved'))
    } catch (error) {
      const info = budgetErrorDetail<{ violations?: Array<{ account_code: string; period: string }> }>(error)
      if (info?.code === 'budget_version_conflict') void query.refetch()
      toast.error(info?.violations?.length ? `${budgetErrorText(error)} (${info.violations.slice(0, 3).map((item) => `${item.account_code} · ${item.period}`).join(', ')})` : budgetErrorText(error))
    }
  }
  const run = async (name: 'approve' | 'reopen' | 'archive' | 'restore', confirmText?: string) => {
    if (confirmText && !window.confirm(confirmText)) return
    try {
      await action.mutateAsync({ id: detail.id, action: name, version: detail.version })
      toast.success(t(`budget.editor.toast.${name}`))
    } catch (error) {
      toast.error(budgetErrorText(error))
    }
  }
  const togglePrimary = async () => {
    try {
      await setPrimary.mutateAsync({ id: detail.id, isPrimary: !detail.is_primary })
      toast.success(detail.is_primary ? t('budget.editor.primaryOff') : t('budget.editor.primaryOn'))
    } catch (error) {
      toast.error(budgetErrorText(error))
    }
  }
  const deleteBudget = async () => {
    if (!window.confirm(t('budget.editor.confirmDelete', { number: detail.number }))) return
    try {
      await remove.mutateAsync(detail.id)
      toast.success(t('budget.editor.deleted'))
      navigate('/erp/budget')
    } catch (error) {
      toast.error(budgetErrorText(error))
    }
  }
  const download = async () => { try { await downloadBudgetWorkbook(detail) } catch (error) { toast.error(budgetErrorText(error)) } }

  const accountLabel = (row: EditRow) => { const account = accounts.get(row.budget_account_id); return account ? `${account.code} · ${account.name}` : `#${row.budget_account_id}` }
  const gridRows: GridRow[] = [
    ...rows.map((row) => ({ id: row.key, row })),
    { id: 'sum-income', summary: { label: t('budget.editor.sumIncome'), kinds: ['income'] } },
    { id: 'sum-cost', summary: { label: t('budget.editor.sumCost'), kinds: ['cogs', 'expense'] } },
    ...(hasOther ? [{ id: 'sum-other', summary: { label: t('budget.editor.sumOther'), kinds: ['other'] as BudgetKind[] } }] : []),
    { id: 'sum-profit', summary: { label: t('budget.editor.sumProfit'), kinds: 'all' } },
  ]
  const moreActions = [
    ...(capabilities.budgets.create ? [{ label: t('budget.editor.copy'), icon: <Copy size={14} />, onClick: () => setDialog('copy') }] : []),
    ...(capabilities.budgets.export ? [{ label: t('budget.editor.exportExcel'), icon: <Download size={14} />, onClick: () => { void download() } }] : []),
    ...(editable ? [{ label: t('budget.editor.importExcel'), icon: <Upload size={14} />, onClick: () => setDialog('import') }] : []),
    ...(capabilities.budgets.archive && detail.status !== 'archived' ? [{ label: t('budget.editor.archive'), onClick: () => { void run('archive', t('budget.editor.confirmArchive')) } }] : []),
    ...(capabilities.budgets.archive && detail.status === 'archived' ? [{ label: t('budget.editor.restore'), onClick: () => { void run('restore') } }] : []),
    ...(capabilities.budgets.archive && detail.status !== 'approved' ? [{ label: t('budget.editor.delete'), variant: 'destructive' as const, icon: <Trash2 size={14} />, onClick: () => { void deleteBudget() } }] : []),
  ]
  return <VStack gap={4}>
    <HStack gap={2} hAlign="between" vAlign="start" wrap="wrap">
      <VStack gap={1}>
        <HStack gap={1} vAlign="center">
          <IconButton label={t('budget.editor.backToList')} icon={<ArrowLeft size={16} />} variant="ghost" size="sm" onClick={() => navigate('/erp/budget')} />
          <Heading level={2}>{detail.name}</Heading>
          {detail.is_primary && <Star size={16} aria-label={t('budget.editor.primary')} fill="currentColor" />}
        </HStack>
        <HStack gap={1.5} vAlign="center" wrap="wrap">
          <Text type="supporting">{detail.number}</Text>
          <ScenarioToken scenario={detail.scenario} />
          <StatusToken status={detail.status} />
          <Text type="supporting">{formatPeriod(detail.start_date, detail.end_date)} · {PERIOD_LABELS[detail.period_type]}{detail.project_name ? ` · ${t('budget.editor.projectLine', { name: detail.project_name })}` : ''}</Text>
        </HStack>
        {detail.purpose && <Text type="supporting">{detail.purpose}</Text>}
      </VStack>
      <HStack gap={2} wrap="wrap">
        <Button label={t('budget.editor.analysis')} icon={<BarChart3 size={15} />} href={`/erp/budget/analysis?budget=${detail.id}`} as={RouterLink} />
        {editable && <Button label={t('budget.editor.editInfo')} onClick={() => setDialog('info')} />}
        {detail.status === 'draft' && capabilities.budgets.approve && <Button label={t('budget.editor.approve')} variant="primary" isDisabled={dirty} tooltip={dirty ? t('budget.editor.saveFirst') : undefined}
          clickAction={() => run('approve', t('budget.editor.confirmApprove'))} />}
        {detail.status === 'approved' && capabilities.budgets.approve && <>
          <Button label={detail.is_primary ? t('budget.editor.unsetPrimary') : t('budget.editor.setPrimary')} icon={<Star size={15} />} clickAction={togglePrimary} />
          <Button label={t('budget.editor.reopen')} clickAction={() => run('reopen', t('budget.editor.confirmReopen'))} />
        </>}
        {moreActions.length > 0 && <DropdownMenu button={{ label: t('budget.editor.more') }} items={moreActions} alignment="end" />}
      </HStack>
    </HStack>

    {detail.status === 'approved' && <Banner status="success" title={detail.approved_by ? t('budget.editor.approvedTitleBy', { name: detail.approved_by }) : t('budget.editor.approvedTitle')} description={t('budget.editor.approvedHint')} collapsible={false} />}
    {detail.status === 'archived' && <Banner status="warning" title={t('budget.editor.archivedTitle')} description={t('budget.editor.archivedHint')} collapsible={false} />}

    <Grid columns={{ minWidth: 170 }} gap={3}>
      <Stat label={t('budget.editor.statIncome')} value={formatMoney(totalsBy(['income']), detail.currency)} />
      <Stat label={t('budget.editor.statCogs')} value={formatMoney(totalsBy(['cogs']), detail.currency)} />
      <Stat label={t('budget.editor.statExpense')} value={formatMoney(totalsBy(['expense']), detail.currency)} />
      <Stat label={t('budget.editor.statProfit')} value={formatMoney(totalsBy('all'), detail.currency)} tone="accent" />
    </Grid>

    {editable && violations.length > 0 && <Banner status="warning" title={t('budget.editor.signsWrong', { n: violations.length })}
      description={t('budget.editor.signsHint')}
      endContent={<Button label={t('budget.editor.fixSigns')} size="sm" onClick={fixSigns} />} collapsible={false} />}

    <Card padding={0}>
      {rows.length === 0 && !editable ? <EmptyState title={t('budget.editor.noAmounts')} description={t('budget.editor.noRows')} />
        : <Table<GridRow>
          data={gridRows}
          idKey="id"
          density="compact"
          dividers="grid"
          plugins={{ sticky }}
          columns={[
            { key: 'account', header: t('budget.editor.colAccount'), width: proportional(2, { minWidth: 240 }), renderCell: (item) => item.summary
              ? <Text weight="semibold">{item.summary.label}</Text>
              : <VStack gap={0.5}>
                <Text weight="medium" maxLines={1}>{accountLabel(item.row!)}</Text>
                <Text type="supporting" maxLines={1}>{KIND_LABELS[kindOf(item.row!)]}{item.row!.note ? ` · ${item.row!.note}` : ''}</Text>
              </VStack> },
            ...(hasProjectColumn ? [{ key: 'project', header: t('budget.editor.colProject'), width: pixel(150), renderCell: (item: GridRow) => item.row ? <Text type="supporting" maxLines={1}>{item.row.project_id ? projects.get(item.row.project_id) ?? '—' : '—'}</Text> : null }] : []),
            ...(hasGroupColumn ? [{ key: 'party_group', header: t('budget.editor.colPartyGroup'), width: pixel(150), renderCell: (item: GridRow) => item.row ? <Text type="supporting" maxLines={1}>{item.row.party_group_id ? partyGroups.get(item.row.party_group_id) ?? '—' : '—'}</Text> : null }] : []),
            ...columns.map((column) => ({
              key: column.start, header: column.label, align: 'end' as const, width: pixel(136),
              renderCell: (item: GridRow) => {
                if (item.summary) return <Text weight="semibold" hasTabularNumbers>{formatAmount(totalsBy(item.summary.kinds, column.start))}</Text>
                const row = item.row!
                const value = row.amounts[column.start]
                if (!editable) return <Text hasTabularNumbers>{value ? formatAmount(value) : '—'}</Text>
                const bad = violations.includes(`${row.key}|${column.start}`)
                return <NumberInput label={`${accountLabel(row)} · ${column.label}`} isLabelHidden size="sm" value={value || null} onChange={(next) => setAmount(row.key, column.start, next)}
                  formatValue={formatAmount} isWheelEnabled={false} status={bad ? { type: 'error', message: t('budget.editor.signWrongCell', { kind: KIND_LABELS[kindOf(row)] }) } : undefined} statusVariant="tooltip" />
              },
            })),
            { key: 'total', header: t('budget.editor.colTotal'), align: 'end', width: pixel(editable ? 196 : 150), renderCell: (item) => <HStack gap={1} hAlign="end" vAlign="center">
              <Text weight="semibold" hasTabularNumbers>{formatAmount(item.summary ? totalsBy(item.summary.kinds) : sum(Object.values(item.row!.amounts)))}</Text>
              {editable && item.row && <DropdownMenu hasChevron={false} alignment="end" button={{ label: t('budget.editor.rowActions'), icon: <MoreHorizontal size={15} />, isIconOnly: true, size: 'sm', variant: 'ghost' }} items={[
                { label: t('budget.editor.splitTotal'), description: t('budget.editor.splitTotalHint'), icon: <Divide size={14} />, onClick: () => setSplitting(item.row!) },
                { label: t('budget.editor.flipSign'), icon: <ArrowUpDown size={14} />, onClick: () => updateRow(item.row!.key, (row) => ({ ...row, amounts: Object.fromEntries(Object.entries(row.amounts).map(([start, value]) => [start, -value])) })) },
                { type: 'divider' as const },
                { label: t('budget.editor.removeRow'), variant: 'destructive' as const, icon: <Trash2 size={14} />, onClick: () => setRows((current) => current.filter((row) => row.key !== item.row!.key)) },
              ]} />}
            </HStack> },
          ]}
        />}
    </Card>

    {editable && <Card>
      <VStack gap={3}>
        <Text weight="semibold">{t('budget.editor.addRow')}</Text>
        <HStack gap={2} wrap="wrap" vAlign="end">
          <Selector label={t('budget.editor.colAccount')} hasSearch width={280} value={newRow.account || undefined} onChange={(value) => setNewRow((current) => ({ ...current, account: value ?? '' }))}
            options={lookups.groups.map((group) => ({ type: 'section' as const, title: group.name, options: lookups.accounts.filter((account) => account.is_active && account.group_id === group.id).map((account) => ({ value: String(account.id), label: `${account.code} · ${account.name}` })) }))
              .concat([{ type: 'section' as const, title: t('budget.editor.noGroup'), options: lookups.accounts.filter((account) => account.is_active && !account.group_id).map((account) => ({ value: String(account.id), label: `${account.code} · ${account.name}` })) }])
              .filter((section) => section.options.length)}
            emptyText={t('budget.editor.accountEmpty')} placeholder={t('budget.editor.accountPlaceholder')} />
          {!detail.project_id && lookups.projects.length > 0 && <Selector label={t('budget.editor.colProject')} hasSearch hasClear width={200} value={newRow.project || null} onChange={(value) => setNewRow((current) => ({ ...current, project: value ?? '' }))}
            options={lookups.projects.map((project) => ({ value: String(project.id), label: `${project.code} · ${project.name}` }))} placeholder="—" />}
          {lookups.party_groups.length > 0 && <Selector label={t('budget.editor.colPartyGroup')} hasSearch hasClear width={200} value={newRow.group || null} onChange={(value) => setNewRow((current) => ({ ...current, group: value ?? '' }))}
            options={lookups.party_groups.map((group) => ({ value: String(group.id), label: group.name }))} placeholder="—" />}
          <TextInput label={t('budget.editor.note')} value={newRow.note} onChange={(value) => setNewRow((current) => ({ ...current, note: value }))} width={200} />
          <Button label={t('budget.editor.add')} icon={<Plus size={15} />} onClick={addRow} isDisabled={!newRow.account} />
        </HStack>
      </VStack>
    </Card>}

    {editable && <HStack gap={2} hAlign="end" vAlign="center">
      {dirty && <Text type="supporting">{t('budget.editor.dirty')}</Text>}
      <Button label={t('budget.editor.revert')} variant="ghost" isDisabled={!dirty} onClick={() => { const next = toEditRows(detail); setRows(next) }} />
      <Button label={t('budget.editor.save')} variant="primary" isDisabled={!dirty} clickAction={save} />
    </HStack>}

    {dialog === 'info' && <BudgetFormDialog budget={detail} lookups={lookups} hasAmounts={detail.rows.length > 0} onClose={() => setDialog(null)} onSaved={() => setDialog(null)} />}
    {dialog === 'copy' && <CopyBudgetDialog budget={detail} onClose={() => setDialog(null)} onCopied={(copy) => { setDialog(null); navigate(`/erp/budget/${copy.id}`) }} />}
    {dialog === 'import' && <ImportBudgetDialog budget={detail} onClose={() => setDialog(null)} onDownload={() => { void download() }} />}
    {splitting && <SplitDialog accountLabel={accountLabel(splitting)} kind={kindOf(splitting)} periods={columns.length} onClose={() => setSplitting(null)} onApply={(total) => {
      const parts = splitEvenly(total, columns.length)
      updateRow(splitting.key, (row) => ({ ...row, amounts: Object.fromEntries(columns.map((column, index) => [column.start, parts[index]])) }))
      setSplitting(null)
    }} />}
  </VStack>
}
