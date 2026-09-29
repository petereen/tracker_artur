import { useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import { Archive, Pencil, Plus, Trash2 } from 'lucide-react'
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
      toast.success(account ? 'Данс хадгалагдлаа' : 'Данс нээгдлээ')
      onClose()
    } catch (error) { toast.error(accountErrorText(error)) }
  }
  const lockMessage = 'Ашиглагдсан дансны энэ талбарыг өөрчлөхгүй — шинэ данс нээнэ үү'
  return <Dialog isOpen onOpenChange={(open) => { if (!open) onClose() }} width={600} purpose="form" maxHeight="90dvh">
    <DialogHeader title={account ? `Данс засах · ${account.code}` : 'Шинэ данс'} subtitle="Дансны код, ангилал, зориулалт нь цалин, төсөв, төлбөр тооцооны бичилт аль дансанд орохыг тодорхойлно." onOpenChange={(open) => { if (!open) onClose() }} />
    <VStack gap={4} padding={4}>
      {locked && <Banner status="info" collapsible={false} title="Энэ данс ашиглагдаж байна" description={`${usageText(usage, catalog)}. Нэр, хураангуй данс, банкны мэдээлэл, идэвхийг засах боломжтой.`} />}
      <FormLayout>
        <TextInput label="Дансны код" value={draft.code} onChange={(code) => set('code', code)} isRequired placeholder="1010" isDisabled={locked} disabledMessage={lockMessage}
          description="249-р тушаалын дансны төлөвлөгөөний дагуу дугаарлана (1 — хөрөнгө, 2 — өр төлбөр, 3 — өмч, 4/5 — орлого, зардал)." />
        <TextInput label="Дансны нэр" value={draft.name} onChange={(name) => set('name', name)} isRequired placeholder="Харилцах данс — Хаан банк" />
        <Selector label="Ангилал" value={draft.classification} onChange={pickClassification} isDisabled={locked} disabledMessage={lockMessage}
          options={catalog.classifications.map((row) => ({ value: row.key, label: row.label, description: row.normal_side === 'debit' ? 'Дебет шинжтэй' : 'Кредит шинжтэй' }))} />
        <Selector label="Зориулалт" value={draft.purpose} onChange={(purpose) => set('purpose', purpose ?? 'general')} isDisabled={locked} disabledMessage={lockMessage}
          options={purposes.map((row) => ({ value: row.key, label: row.label }))}
          description="Систем бичилт хийхдээ энэ зориулалтаар данс хайна: касс/банк — төлбөр, авлага/өглөг — тооцоо, цалингийн — цалин." />
        <Selector label="Хураангуй данс" value={draft.parent_id ? String(draft.parent_id) : null} onChange={(value) => set('parent_id', value ? Number(value) : null)} hasClear hasSearch isOptional
          options={parents.map((row) => ({ value: String(row.id), label: accountLabel(row) }))} emptyText="Энэ ангилалд бүлэг данс алга" placeholder="—" />
        <TextInput label="Валют" value={draft.currency} onChange={(currency) => set('currency', currency.toUpperCase().slice(0, 3))} isDisabled={locked} disabledMessage={lockMessage} width={120} />
        <CheckboxInput label="Бүлэг (хураангуй) данс" description="Бүлэг дансанд гүйлгээ бичихгүй — дэд дансуудыг нэгтгэнэ." value={draft.is_group} onChange={(is_group) => set('is_group', is_group)} isDisabled={locked} />
        <CheckboxInput label="Идэвхтэй" description="Идэвхгүй данс сонголтод гарахгүй, түүх хэвээр үлдэнэ." value={draft.is_active} onChange={(is_active) => set('is_active', is_active)} />
      </FormLayout>
      {purposeSpec?.has_bank_details && !draft.is_group && <VStack gap={2}>
        <Heading level={4}>Банкны мэдээлэл</Heading>
        <FormLayout>
          <TextInput label="Банк" value={draft.bank_name ?? ''} onChange={(value) => set('bank_name', value)} isOptional placeholder="Хаан банк" />
          <TextInput label="Дансны дугаар" value={draft.bank_account_number ?? ''} onChange={(value) => set('bank_account_number', value)} isOptional />
          <TextInput label="IBAN" value={draft.bank_iban ?? ''} onChange={(value) => set('bank_iban', value)} isOptional placeholder="MN12 0005 00…" />
          <TextInput label="Данс эзэмшигч" value={draft.bank_account_holder ?? ''} onChange={(value) => set('bank_account_holder', value)} isOptional />
        </FormLayout>
      </VStack>}
      <HStack gap={2} hAlign="end"><Button label="Болих" variant="ghost" onClick={onClose} /><Button label="Хадгалах" variant="primary" clickAction={submit} isDisabled={!draft.code.trim() || !draft.name.trim() || draft.currency.length !== 3} /></HStack>
    </VStack>
  </Dialog>
}

/** Дансны төлөвлөгөө («Данс код», Dayansoft d047): the one chart of accounts payroll, budget and posting share. */
export function ChartOfAccountsPage() {
  const permissions = useERPAccountPermissions()
  const canView = Boolean(permissions.data?.view)
  const accounts = useERPAccountOptions(canView)
  const catalog = useERPAccountCatalog(canView)
  const usage = useERPAccountUsage(canView)
  const remove = useDeleteERPAccount()
  const [editing, setEditing] = useState<ERPAccountOption | 'new' | null>(null)
  const [classification, setClassification] = useState<'all' | ERPAccountClassification>('all')
  const [status, setStatus] = useState<StatusFilter>('active')
  const [search, setSearch] = useState('')
  const usageById = useMemo(() => new Map((usage.data ?? []).map((row) => [row.account_id, row])), [usage.data])
  const purposeLabels = useMemo(() => new Map((catalog.data?.purposes ?? []).map((row) => [row.key, row.label])), [catalog.data])

  if (permissions.isLoading || (canView && (accounts.isLoading || catalog.isLoading))) return <Skeleton height={320} />
  if (!canView) return <Banner status="warning" collapsible={false} title="Дансны төлөвлөгөөнд хандах эрх танд олгогдоогүй байна" description="Системийн админаас “Accountant” ERP эрх хүснэ үү." />
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
  const inactive = all.filter((account) => account.is_active === false).length

  const removeAccount = async (account: ERPAccountOption, used: boolean) => {
    const question = used
      ? `“${accountLabel(account)}” данс гүйлгээ/тохиргоонд ашиглагдсан тул устгахгүй, идэвхгүй болгоно. Үргэлжлүүлэх үү?`
      : `“${accountLabel(account)}” дансыг устгах уу?`
    if (!window.confirm(question)) return
    try {
      const result = await remove.mutateAsync(account.id)
      toast.success(result.outcome === 'archived' ? 'Данс идэвхгүй боллоо' : 'Данс устгагдлаа')
    } catch (error) { toast.error(accountErrorText(error)) }
  }

  return <VStack gap={4}>
    <HStack gap={2} hAlign="between" vAlign="end" wrap="wrap">
      <VStack gap={0.5}>
        <Heading level={2}>Дансны төлөвлөгөө</Heading>
        <Text type="supporting">Нэг дансны төлөвлөгөө бүх модульд үйлчилнэ: цалингийн бичилт, төсвийн гүйцэтгэл, төлбөр тооцоо, үндсэн хөрөнгө эндээс данс сонгоно.</Text>
      </VStack>
      {perms.create && <Button label="Данс нэмэх" variant="primary" icon={<Plus size={15} />} onClick={() => setEditing('new')} />}
    </HStack>

    <HStack gap={2} vAlign="end" wrap="wrap">
      <SegmentedControl label="Ангилал" size="sm" value={classification} onChange={(value) => setClassification(value as 'all' | ERPAccountClassification)}>
        <SegmentedControlItem value="all" label={`Бүгд (${all.length - inactive})`} />
        {CLASSIFICATION_ORDER.map((key) => <SegmentedControlItem key={key} value={key} label={`${CLASSIFICATION_LABELS[key]} (${counts[key]})`} />)}
      </SegmentedControl>
      <Selector label="Төлөв" isLabelHidden width={160} value={status} onChange={(value) => setStatus((value ?? 'active') as StatusFilter)}
        options={[{ value: 'active', label: 'Идэвхтэй' }, { value: 'inactive', label: `Идэвхгүй (${inactive})` }, { value: 'all', label: 'Бүгд' }]} />
      <TextInput label="Хайх" isLabelHidden value={search} onChange={setSearch} placeholder="Код, нэр, банк…" hasClear width={240} />
    </HStack>

    <Card padding={0}>
      {rows.length === 0 ? <EmptyState title="Данс олдсонгүй" description={all.length ? 'Шүүлтүүрээ өөрчилнө үү.' : '“Данс нэмэх”-ээр эхэлнэ үү.'} />
        : <Table<AccountRow>
          data={rows} idKey="id" density="compact" hasHover
          columns={[
            { key: 'code', header: 'Код', width: pixel(130), renderCell: ({ account, depth }) => <Text weight={account.is_group ? 'bold' : 'medium'}>{`${depth ? `${'  '.repeat(depth - 1)}└ ` : ''}${account.code}`}</Text> },
            { key: 'name', header: 'Нэр', width: proportional(3), renderCell: ({ account }) => <VStack gap={0}>
              <HStack gap={1} vAlign="center" wrap="wrap">
                <Text weight={account.is_group ? 'bold' : undefined}>{account.name}</Text>
                {account.is_group && <Token size="sm" color="gray" label="Бүлэг" />}
                {account.is_active === false && <Token size="sm" color="gray" label="Идэвхгүй" />}
              </HStack>
              {account.bank_name && <Text type="supporting" maxLines={1}>{[account.bank_name, account.bank_account_number].filter(Boolean).join(' · ')}</Text>}
            </VStack> },
            { key: 'classification', header: 'Ангилал', width: pixel(120), renderCell: ({ account }) => <ClassificationToken classification={account.classification} /> },
            { key: 'purpose', header: 'Зориулалт', width: proportional(2), renderCell: ({ account }) => <Text type={account.purpose === 'general' ? 'supporting' : undefined}>{purposeLabels.get(account.purpose ?? 'general') ?? account.purpose}</Text> },
            { key: 'currency', header: 'Валют', width: pixel(80), renderCell: ({ account }) => <Text type="supporting">{account.currency ?? 'MNT'}</Text> },
            { key: 'usage', header: 'Ашиглалт', width: proportional(2), renderCell: ({ usage: used }) => used?.total
              ? <HStack gap={0.5} wrap="wrap">{Object.entries(used.modules).map(([module, count]) => <Token key={module} size="sm" label={catalog.data!.usage_modules[module] ?? module} description={String(count)} />)}</HStack>
              : <Text type="supporting">—</Text> },
            { key: 'actions', header: '', width: pixel(90), renderCell: ({ account, usage: used }) => {
              const inUse = Boolean(used?.total)
              return <HStack gap={0.5} hAlign="end">
                {perms.edit && <IconButton label="Засах" icon={<Pencil size={14} />} size="sm" variant="ghost" onClick={() => setEditing(account)} />}
                {perms.administer && account.is_active !== false && <IconButton label={inUse ? 'Идэвхгүй болгох' : 'Устгах'} tooltip={inUse ? 'Ашиглагдсан данс — идэвхгүй болно' : 'Устгах'}
                  icon={inUse ? <Archive size={14} /> : <Trash2 size={14} />} size="sm" variant="ghost" onClick={() => { void removeAccount(account, inUse) }} />}
              </HStack>
            } },
          ]}
        />}
    </Card>

    {editing && <AccountDialog account={editing === 'new' ? null : editing} accounts={all} catalog={catalog.data} usage={editing === 'new' ? undefined : usageById.get(editing.id)} onClose={() => setEditing(null)} />}
  </VStack>
}
