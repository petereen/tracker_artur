import { useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import { Archive, Pencil, Plus, Trash2, Wand2 } from 'lucide-react'
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
import { SegmentedControl, SegmentedControlItem } from '@astryxdesign/core/SegmentedControl'
import { Selector } from '@astryxdesign/core/Selector'
import { Skeleton } from '@astryxdesign/core/Skeleton'
import { Table, pixel, proportional } from '@astryxdesign/core/Table'
import { Text } from '@astryxdesign/core/Text'
import { TextInput } from '@astryxdesign/core/TextInput'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import {
  type ERPAccountCatalog, type ERPAccountClassification, type ERPAccountInput, type ERPAccountOption, type ERPAccountUsage,
  useCreateERPAccount, useDeleteERPAccount, useERPAccountCatalog, useERPAccountOptions, useERPAccountPermissions, useERPAccountUsage, useUpdateERPAccount,
} from '../api/enterprise'
import { useBudgetCapabilities, useBudgetLookups, useGenerateBudgetAccounts } from '../api/budget'
import { RouterLink } from '../components/budget/shared'
import { CLASSIFICATION_LABELS, CLASSIFICATION_ORDER, ClassificationToken, accountErrorText, accountLabel } from '../components/accounts/accountShared'

type StatusFilter = 'active' | 'inactive' | 'all'
interface AccountRow extends Record<string, unknown> { id: number; account: ERPAccountOption; depth: number; usage?: ERPAccountUsage }

/** Accounts in parent → child order, each with its depth under the summary account. */
function treeOrder(accounts: ERPAccountOption[]): Array<{ account: ERPAccountOption; depth: number }> {
  const byCode = (a: ERPAccountOption, b: ERPAccountOption) => a.code.localeCompare(b.code, undefined, { numeric: true })
  const ids = new Set(accounts.map((account) => account.id))
  const children = new Map<number | null, ERPAccountOption[]>()
  for (const account of accounts) {
    const parent = account.parent_id && ids.has(account.parent_id) ? account.parent_id : null
    children.set(parent, [...(children.get(parent) ?? []), account])
  }
  const ordered: Array<{ account: ERPAccountOption; depth: number }> = []
  const visit = (parent: number | null, depth: number) => {
    for (const account of (children.get(parent) ?? []).sort(byCode)) {
      ordered.push({ account, depth })
      if (depth < 8) visit(account.id, depth + 1)
    }
  }
  visit(null, 0)
  return ordered
}

function descendantsOf(accounts: ERPAccountOption[], rootId: number): Set<number> {
  const found = new Set<number>()
  let frontier = [rootId]
  while (frontier.length) {
    frontier = accounts.filter((account) => account.parent_id !== null && frontier.includes(account.parent_id) && !found.has(account.id)).map((account) => account.id)
    frontier.forEach((id) => found.add(id))
  }
  return found
}

function usageText(usage: ERPAccountUsage | undefined, catalog: ERPAccountCatalog | undefined) {
  if (!usage?.total) return ''
  return Object.entries(usage.modules).map(([module, count]) => `${catalog?.usage_modules[module] ?? module} (${count})`).join(', ')
}

function AccountDialog({ account, accounts, catalog, usage, onClose }: {
  account: ERPAccountOption | null; accounts: ERPAccountOption[]; catalog: ERPAccountCatalog; usage?: ERPAccountUsage; onClose: () => void
}) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState<ERPAccountInput>({
    code: account?.code ?? '', name: account?.name ?? '', classification: account?.classification ?? 'expense', purpose: account?.purpose ?? 'general',
    currency: account?.currency ?? 'MNT', parent_id: account?.parent_id ?? null, is_group: account?.is_group ?? false, is_active: account?.is_active ?? true,
    bank_name: account?.bank_name ?? '', bank_account_number: account?.bank_account_number ?? '', bank_iban: account?.bank_iban ?? '', bank_account_holder: account?.bank_account_holder ?? '',
  })
  const create = useCreateERPAccount()
  const update = useUpdateERPAccount()
  // Any reference (ledger, payroll, budget, settlements, child accounts) locks the posting identity — same rule as the API.
  const locked = Boolean(usage?.total)
  const purposes = catalog.purposes.filter((purpose) => purpose.classifications.includes(draft.classification))
  const purposeSpec = catalog.purposes.find((purpose) => purpose.key === draft.purpose)
  const blocked = account ? descendantsOf(accounts, account.id) : new Set<number>()
  const parents = accounts
    .filter((row) => row.is_group && row.is_active !== false && row.classification === draft.classification && row.id !== account?.id && !blocked.has(row.id))
    .sort((a, b) => a.code.localeCompare(b.code, undefined, { numeric: true }))
  const set = <K extends keyof ERPAccountInput>(key: K, value: ERPAccountInput[K]) => setDraft((current) => ({ ...current, [key]: value }))
  const pickClassification = (value: string | null) => {
    const classification = (value ?? 'expense') as ERPAccountClassification
    setDraft((current) => {
      const keepsPurpose = catalog.purposes.find((purpose) => purpose.key === current.purpose)?.classifications.includes(classification)
      const keepsParent = accounts.find((row) => row.id === current.parent_id)?.classification === classification
      return { ...current, classification, purpose: keepsPurpose ? current.purpose : 'general', parent_id: keepsParent ? current.parent_id : null }
    })
  }
  const submit = async () => {
    try {
      if (account) await update.mutateAsync({ id: account.id, ...draft })
      else await create.mutateAsync(draft)
      toast.success(account ? t('accounts.toast.saved') : t('accounts.toast.created'))
      onClose()
    } catch (error) { toast.error(accountErrorText(error)) }
  }
  const lockMessage = t('accounts.dialog.lockedField')
  return <Dialog isOpen onOpenChange={(open) => { if (!open) onClose() }} width={600} purpose="form" maxHeight="90dvh">
    <DialogHeader title={account ? t('accounts.dialog.editTitle', { code: account.code }) : t('accounts.dialog.newTitle')} subtitle={t('accounts.dialog.subtitle')} onOpenChange={(open) => { if (!open) onClose() }} />
    <VStack gap={4} padding={4}>
      {locked && <Banner status="info" collapsible={false} title={t('accounts.dialog.inUseTitle')} description={t('accounts.dialog.inUseDescription', { usage: usageText(usage, catalog) })} />}
      <FormLayout>
        <TextInput label={t('accounts.dialog.code')} value={draft.code} onChange={(code) => set('code', code)} isRequired placeholder="1010" isDisabled={locked} disabledMessage={lockMessage}
          description={t('accounts.dialog.codeHint')} />
        <TextInput label={t('accounts.dialog.name')} value={draft.name} onChange={(name) => set('name', name)} isRequired placeholder={t('accounts.dialog.namePlaceholder')} />
        <Selector label={t('accounts.dialog.classification')} value={draft.classification} onChange={pickClassification} isDisabled={locked} disabledMessage={lockMessage}
          options={catalog.classifications.map((row) => ({ value: row.key, label: row.label, description: row.normal_side === 'debit' ? t('accounts.dialog.debitNature') : t('accounts.dialog.creditNature') }))} />
        <Selector label={t('accounts.dialog.purpose')} value={draft.purpose} onChange={(purpose) => set('purpose', purpose ?? 'general')} isDisabled={locked} disabledMessage={lockMessage}
          options={purposes.map((row) => ({ value: row.key, label: row.label }))}
          description={t('accounts.dialog.purposeHint')} />
        <Selector label={t('accounts.dialog.parent')} value={draft.parent_id ? String(draft.parent_id) : null} onChange={(value) => set('parent_id', value ? Number(value) : null)} hasClear hasSearch isOptional
          options={parents.map((row) => ({ value: String(row.id), label: accountLabel(row) }))} emptyText={t('accounts.dialog.parentEmpty')} placeholder="—" />
        <TextInput label={t('accounts.dialog.currency')} value={draft.currency} onChange={(currency) => set('currency', currency.toUpperCase().slice(0, 3))} isDisabled={locked} disabledMessage={lockMessage} width={120} />
        <CheckboxInput label={t('accounts.dialog.isGroup')} description={t('accounts.dialog.isGroupHint')} value={draft.is_group} onChange={(is_group) => set('is_group', is_group)} isDisabled={locked} />
        <CheckboxInput label={t('accounts.dialog.isActive')} description={t('accounts.dialog.isActiveHint')} value={draft.is_active} onChange={(is_active) => set('is_active', is_active)} />
      </FormLayout>
      {purposeSpec?.has_bank_details && !draft.is_group && <VStack gap={2}>
        <Heading level={4}>{t('accounts.dialog.bankHeading')}</Heading>
        <FormLayout>
          <TextInput label={t('accounts.dialog.bank')} value={draft.bank_name ?? ''} onChange={(value) => set('bank_name', value)} isOptional placeholder={t('accounts.dialog.bankPlaceholder')} />
          <TextInput label={t('accounts.dialog.bankNumber')} value={draft.bank_account_number ?? ''} onChange={(value) => set('bank_account_number', value)} isOptional />
          <TextInput label="IBAN" value={draft.bank_iban ?? ''} onChange={(value) => set('bank_iban', value)} isOptional placeholder="MN12 0005 00…" />
          <TextInput label={t('accounts.dialog.bankHolder')} value={draft.bank_account_holder ?? ''} onChange={(value) => set('bank_account_holder', value)} isOptional />
        </FormLayout>
      </VStack>}
      <HStack gap={2} hAlign="end"><Button label={t('accounts.dialog.cancel')} variant="ghost" onClick={onClose} /><Button label={t('accounts.dialog.save')} variant="primary" clickAction={submit} isDisabled={!draft.code.trim() || !draft.name.trim() || draft.currency.length !== 3} /></HStack>
    </VStack>
  </Dialog>
}

/** Дансны төлөвлөгөө («Данс код», Dayansoft d047): the one chart of accounts payroll, budget and posting share. */
export function ChartOfAccountsPage() {
  const { t } = useTranslation()
  const permissions = useERPAccountPermissions()
  const canView = Boolean(permissions.data?.view)
  const accounts = useERPAccountOptions(canView)
  const catalog = useERPAccountCatalog(canView)
  const usage = useERPAccountUsage(canView)
  const remove = useDeleteERPAccount()
  const budgetCaps = useBudgetCapabilities(canView)
  const budgetSettings = budgetCaps.data?.settings
  const budgetLookups = useBudgetLookups(Boolean(budgetSettings?.view))
  const generateBudget = useGenerateBudgetAccounts()
  const [editing, setEditing] = useState<ERPAccountOption | 'new' | null>(null)
  const [classification, setClassification] = useState<'all' | ERPAccountClassification>('all')
  const [status, setStatus] = useState<StatusFilter>('active')
  const [search, setSearch] = useState('')
  const usageById = useMemo(() => new Map((usage.data ?? []).map((row) => [row.account_id, row])), [usage.data])
  const budgetByLedger = useMemo(() => {
    const names = new Map((budgetLookups.data?.accounts ?? []).map((row) => [row.id, row]))
    return new Map((budgetLookups.data?.erp_accounts ?? []).map((row) => [row.id, row.budget_account_id ? names.get(row.budget_account_id) : undefined]))
  }, [budgetLookups.data])
  const purposeLabels = useMemo(() => new Map((catalog.data?.purposes ?? []).map((row) => [row.key, row.label])), [catalog.data])

  if (permissions.isLoading || (canView && (accounts.isLoading || catalog.isLoading))) return <Skeleton height={320} />
  if (!canView) return <Banner status="warning" collapsible={false} title={t('accounts.page.noAccess')} description={t('accounts.page.noAccessHint')} />
  if (!accounts.data || !catalog.data) return <Banner status="error" collapsible={false} title={accountErrorText(accounts.error ?? catalog.error)} />

  const all = accounts.data
  const perms = permissions.data!
  const needle = search.trim().toLowerCase()
  const filtered = all.filter((account) => (classification === 'all' || account.classification === classification)
    && (status === 'all' || (status === 'active' ? account.is_active !== false : account.is_active === false))
    && (!needle || `${account.code} ${account.name} ${account.bank_name ?? ''} ${account.bank_account_number ?? ''}`.toLowerCase().includes(needle)))
  // Keep the tree while browsing; a search shows a flat code-ordered list.
  const rows: AccountRow[] = (needle ? filtered.map((account) => ({ account, depth: 0 })).sort((a, b) => a.account.code.localeCompare(b.account.code, undefined, { numeric: true })) : treeOrder(filtered))
    .map(({ account, depth }) => ({ id: account.id, account, depth, usage: usageById.get(account.id) }))
  const counts = CLASSIFICATION_ORDER.reduce<Record<string, number>>((acc, key) => ({ ...acc, [key]: all.filter((account) => account.classification === key && account.is_active !== false).length }), {})
  const budgetable = (account: ERPAccountOption) => !account.is_group && account.is_active !== false && !!account.classification && ['income', 'expense'].includes(account.classification)
  const unlinkedBudget = budgetLookups.data ? all.filter((account) => budgetable(account) && !budgetByLedger.get(account.id)).length : 0
  const generateBudgetAccounts = async () => {
    if (!window.confirm(t('accounts.page.confirmGenerate', { n: unlinkedBudget }))) return
    try { const result = await generateBudget.mutateAsync(undefined); toast.success(t('accounts.toast.budgetCreated', { n: result.created })) } catch (error) { toast.error(accountErrorText(error)) }
  }
  const inactive = all.filter((account) => account.is_active === false).length

  const removeAccount = async (account: ERPAccountOption, used: boolean) => {
    const question = used
      ? t('accounts.page.confirmArchive', { label: accountLabel(account) })
      : t('accounts.page.confirmDelete', { label: accountLabel(account) })
    if (!window.confirm(question)) return
    try {
      const result = await remove.mutateAsync(account.id)
      toast.success(result.outcome === 'archived' ? t('accounts.toast.archived') : t('accounts.toast.deleted'))
    } catch (error) { toast.error(accountErrorText(error)) }
  }

  return <VStack gap={4}>
    <HStack gap={2} vAlign="end" hAlign="between" wrap="wrap">
      <HStack gap={2} vAlign="end" wrap="wrap">
        <SegmentedControl label={t('accounts.page.classification')} size="sm" value={classification} onChange={(value) => setClassification(value as 'all' | ERPAccountClassification)}>
          <SegmentedControlItem value="all" label={t('accounts.page.all', { n: all.length - inactive })} />
          {CLASSIFICATION_ORDER.map((key) => <SegmentedControlItem key={key} value={key} label={`${CLASSIFICATION_LABELS[key]} (${counts[key]})`} />)}
        </SegmentedControl>
        <Selector label={t('accounts.page.status')} isLabelHidden width={160} value={status} onChange={(value) => setStatus((value ?? 'active') as StatusFilter)}
          options={[{ value: 'active', label: t('accounts.page.statusActive') }, { value: 'inactive', label: t('accounts.page.statusInactive', { n: inactive }) }, { value: 'all', label: t('accounts.page.statusAll') }]} />
        <TextInput label={t('accounts.page.search')} isLabelHidden value={search} onChange={setSearch} placeholder={t('accounts.page.searchPlaceholder')} hasClear width={240} />
      </HStack>
      {perms.create && <Button label={t('accounts.page.add')} variant="primary" icon={<Plus size={15} />} onClick={() => setEditing('new')} />}
    </HStack>

    {budgetSettings?.view && budgetLookups.data && unlinkedBudget > 0 && <Banner status="warning" collapsible={false}
      title={t('accounts.page.unlinkedTitle', { n: unlinkedBudget })}
      description={t('accounts.page.unlinkedHint')}
      endContent={<HStack gap={2} vAlign="center">
        <Link as={RouterLink} href="/erp/budget/accounts">{t('accounts.page.budgetAccounts')}</Link>
        {budgetSettings.create && <Button label={t('accounts.page.generateBudget')} size="sm" icon={<Wand2 size={14} />} clickAction={generateBudgetAccounts} />}
      </HStack>} />}

    <Card padding={0}>
      {rows.length === 0 ? <EmptyState title={t('accounts.page.emptyTitle')} description={all.length ? t('accounts.page.emptyFiltered') : t('accounts.page.emptyNew')} />
        : <Table<AccountRow>
          data={rows} idKey="id" density="compact" hasHover
          columns={[
            { key: 'code', header: t('accounts.page.colCode'), width: pixel(130), renderCell: ({ account, depth }) => <Text weight={account.is_group ? 'bold' : 'medium'}>{`${depth ? `${'  '.repeat(depth - 1)}└ ` : ''}${account.code}`}</Text> },
            { key: 'name', header: t('accounts.page.colName'), width: proportional(3), renderCell: ({ account }) => <VStack gap={0}>
              <HStack gap={1} vAlign="center" wrap="wrap">
                <Text weight={account.is_group ? 'bold' : undefined}>{account.name}</Text>
                {account.is_group && <Token size="sm" color="gray" label={t('accounts.page.group')} />}
                {account.is_active === false && <Token size="sm" color="gray" label={t('accounts.inactive')} />}
              </HStack>
              {account.bank_name && <Text type="supporting" maxLines={1}>{[account.bank_name, account.bank_account_number].filter(Boolean).join(' · ')}</Text>}
            </VStack> },
            { key: 'classification', header: t('accounts.page.colClassification'), width: pixel(120), renderCell: ({ account }) => <ClassificationToken classification={account.classification} /> },
            { key: 'purpose', header: t('accounts.page.colPurpose'), width: proportional(2), renderCell: ({ account }) => <Text type={account.purpose === 'general' ? 'supporting' : undefined}>{purposeLabels.get(account.purpose ?? 'general') ?? account.purpose}</Text> },
            { key: 'currency', header: t('accounts.page.colCurrency'), width: pixel(80), renderCell: ({ account }) => <Text type="supporting">{account.currency ?? 'MNT'}</Text> },
            ...(budgetSettings?.view ? [{ key: 'budget', header: t('accounts.page.colBudget'), width: proportional(2), renderCell: ({ account }: AccountRow) => {
              if (!budgetable(account)) return <Text type="supporting">—</Text>
              const linked = budgetByLedger.get(account.id)
              return linked ? <Token size="sm" label={linked.code} description={linked.name} /> : <Token size="sm" color="orange" label={t('accounts.page.unlinked')} />
            } }] : []),
            { key: 'usage', header: t('accounts.page.colUsage'), width: proportional(2), renderCell: ({ usage: used }) => used?.total
              ? <HStack gap={0.5} wrap="wrap">{Object.entries(used.modules).map(([module, count]) => <Token key={module} size="sm" label={catalog.data!.usage_modules[module] ?? module} description={String(count)} />)}</HStack>
              : <Text type="supporting">—</Text> },
            { key: 'actions', header: '', width: pixel(90), renderCell: ({ account, usage: used }) => {
              const inUse = Boolean(used?.total)
              return <HStack gap={0.5} hAlign="end">
                {perms.edit && <IconButton label={t('accounts.page.edit')} icon={<Pencil size={14} />} size="sm" variant="ghost" onClick={() => setEditing(account)} />}
                {perms.administer && account.is_active !== false && <IconButton label={inUse ? t('accounts.page.archive') : t('accounts.page.delete')} tooltip={inUse ? t('accounts.page.archiveTooltip') : t('accounts.page.delete')}
                  icon={inUse ? <Archive size={14} /> : <Trash2 size={14} />} size="sm" variant="ghost" onClick={() => { void removeAccount(account, inUse) }} />}
              </HStack>
            } },
          ]}
        />}
    </Card>

    {editing && <AccountDialog account={editing === 'new' ? null : editing} accounts={all} catalog={catalog.data} usage={editing === 'new' ? undefined : usageById.get(editing.id)} onClose={() => setEditing(null)} />}
  </VStack>
}
