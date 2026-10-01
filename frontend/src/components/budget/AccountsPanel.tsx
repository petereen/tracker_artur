import { useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import { Pencil, Plus, Trash2, Wand2 } from 'lucide-react'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { CheckboxInput } from '@astryxdesign/core/CheckboxInput'
import { Dialog, DialogHeader } from '@astryxdesign/core/Dialog'
import { EmptyState } from '@astryxdesign/core/EmptyState'
import { FormLayout } from '@astryxdesign/core/FormLayout'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { IconButton } from '@astryxdesign/core/IconButton'
import { Link } from '@astryxdesign/core/Link'
import { MultiSelector } from '@astryxdesign/core/MultiSelector'
import { NumberInput } from '@astryxdesign/core/NumberInput'
import { Selector } from '@astryxdesign/core/Selector'
import { Table, pixel, proportional } from '@astryxdesign/core/Table'
import { Text } from '@astryxdesign/core/Text'
import { TextArea } from '@astryxdesign/core/TextArea'
import { TextInput } from '@astryxdesign/core/TextInput'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import {
  type BudgetAccount, type BudgetCapabilities, type BudgetGroup, type BudgetKind, type BudgetLookups,
  useDeleteBudgetAccount, useDeleteBudgetGroup, useGenerateBudgetAccounts, useSaveBudgetAccount, useSaveBudgetGroup,
} from '../../api/budget'
import type { ERPAccountClassification } from '../../api/enterprise'
import { CHART_OF_ACCOUNTS_PATH, CLASSIFICATION_LABELS } from '../accounts/accountShared'
import { KIND_HINTS, KIND_LABELS, KindToken, RouterLink, budgetErrorText } from './shared'

const LEDGER_CLASSES: Record<BudgetKind, string[] | null> = { income: ['income'], cogs: ['expense'], expense: ['expense'], other: null }
const kindOptions = () => (Object.keys(KIND_LABELS) as BudgetKind[]).map((kind) => ({ value: kind, label: `${KIND_LABELS[kind]} — ${KIND_HINTS[kind]}` }))
interface GroupRow extends Record<string, unknown> { id: number; group: BudgetGroup; count: number }
interface AccountRow extends Record<string, unknown> { id: number; account: BudgetAccount }

function GroupDialog({ group, onClose }: { group: BudgetGroup | null; onClose: () => void }) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState({ code: group?.code ?? '', name: group?.name ?? '', kind: group?.kind ?? 'expense' as BudgetKind, sort: group?.sort ?? 0, is_active: group?.is_active ?? true })
  const save = useSaveBudgetGroup()
  const submit = async () => {
    try { await save.mutateAsync({ id: group?.id, ...draft }); toast.success(t('budget.accounts.groupSaved')); onClose() } catch (error) { toast.error(budgetErrorText(error)) }
  }
  return <Dialog isOpen onOpenChange={(open) => { if (!open) onClose() }} width={460} purpose="form">
    <DialogHeader title={group ? t('budget.accounts.groupEdit') : t('budget.accounts.groupNew')} subtitle={t('budget.accounts.groupSubtitle')} onOpenChange={(open) => { if (!open) onClose() }} />
    <VStack gap={4} padding={4}>
      <FormLayout>
        <TextInput label={t('budget.accounts.code')} value={draft.code} onChange={(code) => setDraft({ ...draft, code })} isRequired placeholder="MARKETING" />
        <TextInput label={t('budget.accounts.name')} value={draft.name} onChange={(name) => setDraft({ ...draft, name })} isRequired placeholder={t('budget.accounts.groupNamePlaceholder')} />
        <Selector label={t('budget.accounts.kind')} options={kindOptions()} value={draft.kind} onChange={(kind) => setDraft({ ...draft, kind: kind as BudgetKind })} description={t('budget.accounts.kindHint')} />
        <NumberInput label={t('budget.accounts.sort')} value={draft.sort} onChange={(sort) => setDraft({ ...draft, sort })} min={0} isIntegerOnly />
        <CheckboxInput label={t('budget.accounts.active')} value={draft.is_active} onChange={(is_active) => setDraft({ ...draft, is_active })} />
      </FormLayout>
      <HStack gap={2} hAlign="end"><Button label={t('budget.accounts.cancel')} variant="ghost" onClick={onClose} /><Button label={t('budget.accounts.save')} variant="primary" clickAction={submit} isDisabled={!draft.code.trim() || !draft.name.trim()} /></HStack>
    </VStack>
  </Dialog>
}

function AccountDialog({ account, lookups, onClose }: { account: BudgetAccount | null; lookups: BudgetLookups; onClose: () => void }) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState({
    code: account?.code ?? '', name: account?.name ?? '', kind: account?.kind ?? 'expense' as BudgetKind, group_id: account?.group_id ?? null as number | null,
    note: account?.note ?? '', sort: account?.sort ?? 0, is_active: account?.is_active ?? true, erp_account_ids: account?.erp_accounts.map((row) => String(row.id)) ?? [] as string[],
  })
  const save = useSaveBudgetAccount()
  const owners = useMemo(() => new Map(lookups.accounts.map((row) => [row.id, row.code])), [lookups.accounts])
  // Actuals are credit − debit on the linked ledger accounts, so only the matching P&L class makes sense.
  const ledgerClasses = LEDGER_CLASSES[draft.kind]
  const ledgerOptions = lookups.erp_accounts
    .filter((row) => draft.erp_account_ids.includes(String(row.id)) || (row.is_active && (!ledgerClasses || ledgerClasses.includes(row.classification))))
    .map((row) => {
      const takenBy = row.budget_account_id && row.budget_account_id !== account?.id ? owners.get(row.budget_account_id) : undefined
      return { value: String(row.id), label: `${row.code} · ${row.name}${takenBy ? ` (→ ${takenBy})` : ''}`, description: CLASSIFICATION_LABELS[row.classification as ERPAccountClassification], disabled: Boolean(takenBy) }
    })
  const pickGroup = (value: string | null) => {
    const group = lookups.groups.find((row) => String(row.id) === value)
    setDraft((current) => ({ ...current, group_id: group?.id ?? null, kind: !account?.in_use && group ? group.kind : current.kind }))
  }
  const submit = async () => {
    try {
      await save.mutateAsync({ id: account?.id, ...draft, note: draft.note || null, erp_account_ids: draft.erp_account_ids.map(Number) })
      toast.success(t('budget.accounts.accountSaved'))
      onClose()
    } catch (error) { toast.error(budgetErrorText(error)) }
  }
  return <Dialog isOpen onOpenChange={(open) => { if (!open) onClose() }} width={560} purpose="form" maxHeight="90dvh">
    <DialogHeader title={account ? t('budget.accounts.accountEdit') : t('budget.accounts.accountNew')} subtitle={t('budget.accounts.accountSubtitle')} onOpenChange={(open) => { if (!open) onClose() }} />
    <VStack gap={4} padding={4}>
      <FormLayout>
        <TextInput label={t('budget.accounts.code')} value={draft.code} onChange={(code) => setDraft({ ...draft, code })} isRequired />
        <TextInput label={t('budget.accounts.name')} value={draft.name} onChange={(name) => setDraft({ ...draft, name })} isRequired />
        <Selector label={t('budget.accounts.group')} options={lookups.groups.map((group) => ({ value: String(group.id), label: `${group.name} (${KIND_LABELS[group.kind]})` }))} value={draft.group_id ? String(draft.group_id) : null} onChange={pickGroup} hasClear isOptional />
        <Selector label={t('budget.accounts.kind')} options={kindOptions()} value={draft.kind} onChange={(kind) => setDraft({ ...draft, kind: kind as BudgetKind })}
          isDisabled={account?.in_use} disabledMessage={t('budget.accounts.kindLocked')} description={t('budget.accounts.kindSignHint')} />
        <MultiSelector label={t('budget.accounts.ledger')} options={ledgerOptions} value={draft.erp_account_ids} onChange={(ids) => setDraft({ ...draft, erp_account_ids: ids })}
          hasSearch triggerDisplay="badges" maxBadges={4} placeholder={t('budget.accounts.ledgerPlaceholder')} searchPlaceholder={t('budget.accounts.ledgerSearch')}
          emptyText={t('budget.accounts.ledgerEmpty')} />
        <TextArea label={t('budget.accounts.note')} value={draft.note} onChange={(note) => setDraft({ ...draft, note })} rows={2} isOptional />
        <NumberInput label={t('budget.accounts.sort')} value={draft.sort} onChange={(sort) => setDraft({ ...draft, sort })} min={0} isIntegerOnly />
        <CheckboxInput label={t('budget.accounts.active')} value={draft.is_active} onChange={(is_active) => setDraft({ ...draft, is_active })} />
      </FormLayout>
      {draft.erp_account_ids.length === 0 && <Banner status="warning" title={t('budget.accounts.noLedgerTitle')} description={t('budget.accounts.noLedgerHint')} collapsible={false} />}
      <HStack gap={2} hAlign="end"><Button label={t('budget.accounts.cancel')} variant="ghost" onClick={onClose} /><Button label={t('budget.accounts.save')} variant="primary" clickAction={submit} isDisabled={!draft.code.trim() || !draft.name.trim()} /></HStack>
    </VStack>
  </Dialog>
}

export function AccountsPanel({ capabilities, lookups }: { capabilities: BudgetCapabilities; lookups: BudgetLookups }) {
  const { t } = useTranslation()
  const [editingGroup, setEditingGroup] = useState<BudgetGroup | 'new' | null>(null)
  const [editingAccount, setEditingAccount] = useState<BudgetAccount | 'new' | null>(null)
  const [groupFilter, setGroupFilter] = useState('')
  const [search, setSearch] = useState('')
  const deleteGroup = useDeleteBudgetGroup()
  const deleteAccount = useDeleteBudgetAccount()
  const generate = useGenerateBudgetAccounts()
  const caps = capabilities.settings
  const unlinked = lookups.erp_accounts.filter((row) => row.is_active && !row.budget_account_id && ['income', 'expense'].includes(row.classification))
  const counts = useMemo(() => lookups.accounts.reduce<Record<number, number>>((acc, row) => { if (row.group_id) acc[row.group_id] = (acc[row.group_id] ?? 0) + 1; return acc }, {}), [lookups.accounts])
  const accounts = lookups.accounts.filter((row) => (!groupFilter || String(row.group_id ?? 0) === groupFilter)
    && (!search || `${row.code} ${row.name} ${row.erp_accounts.map((ledger) => ledger.code).join(' ')}`.toLowerCase().includes(search.toLowerCase())))

  const removeGroup = async (group: BudgetGroup) => {
    if (!window.confirm(t('budget.accounts.confirmDeleteGroup', { name: group.name }))) return
    try { await deleteGroup.mutateAsync(group.id); toast.success(t('budget.accounts.groupDeleted')) } catch (error) { toast.error(budgetErrorText(error)) }
  }
  const removeAccount = async (account: BudgetAccount) => {
    if (!window.confirm(t('budget.accounts.confirmDeleteAccount', { label: `${account.code} ${account.name}` }))) return
    try { await deleteAccount.mutateAsync(account.id); toast.success(t('budget.accounts.accountDeleted')) } catch (error) { toast.error(budgetErrorText(error)) }
  }
  const runGenerate = async () => {
    if (!window.confirm(t('budget.accounts.confirmGenerate', { n: unlinked.length }))) return
    try { const result = await generate.mutateAsync(undefined); toast.success(t('budget.accounts.generated', { n: result.created })) } catch (error) { toast.error(budgetErrorText(error)) }
  }

  return <VStack gap={5}>
    <Banner status={unlinked.length || !lookups.accounts.length ? 'warning' : 'success'} collapsible={false}
      title={!lookups.accounts.length ? t('budget.accounts.noneTitle') : unlinked.length ? t('budget.accounts.unlinkedTitle', { n: unlinked.length }) : t('budget.accounts.allLinkedTitle')}
      description={t('budget.accounts.flowHint')}
      endContent={<HStack gap={2} vAlign="center">
        <Link as={RouterLink} href={CHART_OF_ACCOUNTS_PATH}>{t('budget.accounts.chartLink')}</Link>
        {caps.create && unlinked.length > 0 && <Button label={t('budget.accounts.generateFromChart')} size="sm" icon={<Wand2 size={14} />} clickAction={runGenerate} />}
      </HStack>} />

    <VStack gap={2}>
      <HStack gap={2} hAlign="between" vAlign="center">
        <VStack gap={0.5}><Heading level={3}>{t('budget.accounts.groupsHeading')}</Heading><Text type="supporting">{t('budget.accounts.groupsHint')}</Text></VStack>
        {caps.create && <Button label={t('budget.accounts.addGroup')} icon={<Plus size={15} />} onClick={() => setEditingGroup('new')} />}
      </HStack>
      <Card padding={0}>
        {lookups.groups.length === 0 ? <EmptyState title={t('budget.accounts.noGroups')} isCompact />
          : <Table<GroupRow>
            data={lookups.groups.map((group) => ({ id: group.id, group, count: counts[group.id] ?? 0 }))} idKey="id" density="compact"
            columns={[
              { key: 'code', header: t('budget.accounts.code'), width: pixel(140), renderCell: ({ group }) => <Text weight="medium">{group.code}</Text> },
              { key: 'name', header: t('budget.accounts.name'), width: proportional(2), renderCell: ({ group }) => <HStack gap={1} vAlign="center"><Text>{group.name}</Text>{!group.is_active && <Token size="sm" color="gray" label={t('budget.accounts.inactive')} />}</HStack> },
              { key: 'kind', header: t('budget.accounts.kind'), width: pixel(110), renderCell: ({ group }) => <KindToken kind={group.kind} /> },
              { key: 'count', header: t('budget.accounts.colAccounts'), align: 'end', width: pixel(80) },
              { key: 'actions', header: '', width: pixel(90), renderCell: ({ group }) => <HStack gap={0.5} hAlign="end">
                {caps.edit && <IconButton label={t('budget.accounts.edit')} icon={<Pencil size={14} />} size="sm" variant="ghost" onClick={() => setEditingGroup(group)} />}
                {caps.archive && <IconButton label={t('budget.accounts.delete')} icon={<Trash2 size={14} />} size="sm" variant="ghost" onClick={() => { void removeGroup(group) }} />}
              </HStack> },
            ]}
          />}
      </Card>
    </VStack>

    <VStack gap={2}>
      <HStack gap={2} hAlign="between" vAlign="end" wrap="wrap">
        <VStack gap={0.5}><Heading level={3}>{t('budget.accounts.accountsHeading')}</Heading><Text type="supporting">{t('budget.accounts.accountsHint')}</Text></VStack>
        <HStack gap={2} vAlign="end" wrap="wrap">
          <TextInput label={t('budget.accounts.search')} isLabelHidden value={search} onChange={setSearch} placeholder={t('budget.accounts.searchPlaceholder')} hasClear width={220} />
          <Selector label={t('budget.accounts.group')} isLabelHidden hasClear width={200} value={groupFilter || null} onChange={(value) => setGroupFilter(value ?? '')} placeholder={t('budget.accounts.allGroups')}
            options={[...lookups.groups.map((group) => ({ value: String(group.id), label: group.name })), { value: '0', label: t('budget.accounts.noGroup') }]} />
          {caps.create && <Button label={t('budget.accounts.addAccount')} variant="primary" icon={<Plus size={15} />} onClick={() => setEditingAccount('new')} />}
        </HStack>
      </HStack>
      <Card padding={0}>
        {accounts.length === 0 ? <EmptyState title={t('budget.accounts.emptyTitle')} description={t('budget.accounts.emptyHint')} />
          : <Table<AccountRow>
            data={accounts.map((account) => ({ id: account.id, account }))} idKey="id" density="compact" hasHover
            columns={[
              { key: 'code', header: t('budget.accounts.code'), width: pixel(120), renderCell: ({ account }) => <Text weight="medium">{account.code}</Text> },
              { key: 'name', header: t('budget.accounts.name'), width: proportional(2), renderCell: ({ account }) => <VStack gap={0}>
                <HStack gap={1} vAlign="center"><Text>{account.name}</Text>{!account.is_active && <Token size="sm" color="gray" label={t('budget.accounts.inactive')} />}</HStack>
                {account.note && <Text type="supporting" maxLines={1}>{account.note}</Text>}
              </VStack> },
              { key: 'kind', header: t('budget.accounts.kind'), width: pixel(100), renderCell: ({ account }) => <KindToken kind={account.kind} /> },
              { key: 'group', header: t('budget.accounts.group'), width: proportional(1), renderCell: ({ account }) => <Text type="supporting">{account.group_name ?? '—'}</Text> },
              { key: 'ledger', header: t('budget.accounts.ledger'), width: proportional(2), renderCell: ({ account }) => account.erp_accounts.length
                ? <HStack gap={0.5} wrap="wrap">{account.erp_accounts.map((ledger) => <Token key={ledger.id} size="sm" label={ledger.code} description={ledger.name} />)}</HStack>
                : <Token size="sm" color="orange" label={t('budget.accounts.unlinked')} /> },
              { key: 'actions', header: '', width: pixel(90), renderCell: ({ account }) => <HStack gap={0.5} hAlign="end">
                {caps.edit && <IconButton label={t('budget.accounts.edit')} icon={<Pencil size={14} />} size="sm" variant="ghost" onClick={() => setEditingAccount(account)} />}
                {caps.archive && <IconButton label={t('budget.accounts.delete')} tooltip={account.in_use ? t('budget.accounts.deleteInUse') : t('budget.accounts.delete')} icon={<Trash2 size={14} />} size="sm" variant="ghost"
                  isDisabled={account.in_use} onClick={() => { void removeAccount(account) }} />}
              </HStack> },
            ]}
          />}
      </Card>
    </VStack>

    {editingGroup && <GroupDialog group={editingGroup === 'new' ? null : editingGroup} onClose={() => setEditingGroup(null)} />}
    {editingAccount && <AccountDialog account={editingAccount === 'new' ? null : editingAccount} lookups={lookups} onClose={() => setEditingAccount(null)} />}
  </VStack>
}
