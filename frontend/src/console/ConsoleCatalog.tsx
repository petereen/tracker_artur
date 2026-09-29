import { useState } from 'react'
import toast from 'react-hot-toast'
import { Pencil, Plus } from 'lucide-react'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { CheckboxInput } from '@astryxdesign/core/CheckboxInput'
import { CodeBlock } from '@astryxdesign/core/CodeBlock'
import { Dialog, DialogHeader } from '@astryxdesign/core/Dialog'
import { EmptyState } from '@astryxdesign/core/EmptyState'
import { FormLayout } from '@astryxdesign/core/FormLayout'
import { Grid } from '@astryxdesign/core/Grid'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { IconButton } from '@astryxdesign/core/IconButton'
import { MetadataList, MetadataListItem } from '@astryxdesign/core/MetadataList'
import { NumberInput } from '@astryxdesign/core/NumberInput'
import { Selector } from '@astryxdesign/core/Selector'
import { Skeleton } from '@astryxdesign/core/Skeleton'
import { StatusDot } from '@astryxdesign/core/StatusDot'
import { Table, pixel, proportional } from '@astryxdesign/core/Table'
import { Text } from '@astryxdesign/core/Text'
import { TextInput } from '@astryxdesign/core/TextInput'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import type { TenantFeatureCode } from '../api/tenancy'
import {
  type BillingCycle, type ConsoleAuditEvent, type ConsolePlan, type Operator,
  consoleError, useConsoleAudit, useConsoleSession, useConsoleSystem, useConsoleTenants, useCreateOperator, useOperators, usePlans,
  useSavePlan, useUpdateOperator,
} from './consoleApi'
import { CYCLES, FeatureChecklist, TENANT_STATUS } from './ConsoleTenants'

function PlanDialog({ plan, onClose }: { plan: ConsolePlan | null; onClose: () => void }) {
  const save = useSavePlan()
  const [draft, setDraft] = useState({
    code: plan?.code ?? '', name: plan?.name ?? '', description: plan?.description ?? '', seat_limit: plan?.seat_limit ?? null as number | null,
    features: plan?.features ?? [] as TenantFeatureCode[], billing_cycle: plan?.billing_cycle ?? 'monthly' as BillingCycle,
    price_amount: plan?.price_amount ?? null as number | null, currency: plan?.currency ?? 'MNT', is_active: plan?.is_active ?? true, sort_order: plan?.sort_order ?? 0,
  })
  const set = <K extends keyof typeof draft>(key: K, value: (typeof draft)[K]) => setDraft((current) => ({ ...current, [key]: value }))
  const submit = async () => {
    try {
      await save.mutateAsync({ ...draft, description: draft.description || null, isNew: !plan })
      toast.success('Багц хадгалагдлаа')
      onClose()
    } catch (error) { toast.error(consoleError(error, 'Багц хадгалж чадсангүй')) }
  }
  return <Dialog isOpen onOpenChange={(open) => { if (!open) onClose() }} width={620} purpose="form" maxHeight="90dvh">
    <DialogHeader title={plan ? `Багц засах · ${plan.code}` : 'Шинэ багц'} subtitle="Багц нь шинэ байгууллага, лиценз олгох үеийн анхдагч утга болно." onOpenChange={(open) => { if (!open) onClose() }} />
    <VStack gap={4} padding={4}>
      <FormLayout>
        <TextInput label="Код" value={draft.code} onChange={(value) => set('code', value.toLowerCase())} isRequired isDisabled={Boolean(plan)} placeholder="professional" />
        <TextInput label="Нэр" value={draft.name} onChange={(value) => set('name', value)} isRequired />
        <TextInput label="Тайлбар" value={draft.description} onChange={(value) => set('description', value)} isOptional />
        <NumberInput label="Хэрэглэгчийн тоо" value={draft.seat_limit} onChange={(value) => set('seat_limit', value)} min={1} hasClear description="Хоосон = хязгааргүй" />
        <Selector label="Төлбөрийн мөчлөг" value={draft.billing_cycle} onChange={(value) => set('billing_cycle', (value ?? 'monthly') as BillingCycle)} options={CYCLES} />
        <NumberInput label="Үнэ" value={draft.price_amount} onChange={(value) => set('price_amount', value)} min={0} hasClear units={draft.currency} />
        <NumberInput label="Эрэмбэ" value={draft.sort_order} onChange={(value) => set('sort_order', value)} />
        <CheckboxInput label="Идэвхтэй" value={draft.is_active} onChange={(value) => set('is_active', value)} />
      </FormLayout>
      <FeatureChecklist value={draft.features} onChange={(features) => set('features', features)} />
      <HStack gap={2} hAlign="end"><Button label="Болих" variant="ghost" onClick={onClose} /><Button label="Хадгалах" variant="primary" clickAction={submit} isDisabled={!draft.code || !draft.name} /></HStack>
    </VStack>
  </Dialog>
}

interface PlanRow extends Record<string, unknown> { id: number; plan: ConsolePlan }

export function PlansPage() {
  const superadmin = useConsoleSession((state) => state.operator?.role === 'superadmin')
  const plans = usePlans()
  const [editing, setEditing] = useState<ConsolePlan | 'new' | null>(null)
  const rows: PlanRow[] = (plans.data ?? []).map((plan) => ({ id: plan.id, plan }))
  return <VStack gap={4}>
    <HStack gap={2} vAlign="center" hAlign="between">
      <VStack gap={0}><Heading level={1}>Багцууд</Heading><Text type="supporting">Starter / Professional / Enterprise зэрэг захиалгын түвшин.</Text></VStack>
      {superadmin && <Button label="Шинэ багц" variant="primary" icon={<Plus size={15} />} onClick={() => setEditing('new')} />}
    </HStack>
    <Card padding={0}>
      {plans.isLoading ? <Skeleton height={200} /> : rows.length === 0 ? <EmptyState title="Багц алга" />
        : <Table<PlanRow> data={rows} idKey="id" density="compact" columns={[
          { key: 'name', header: 'Багц', width: proportional(2), renderCell: ({ plan }) => <VStack gap={0}><Text weight="semibold">{plan.name}</Text><Text type="supporting">{plan.code}</Text></VStack> },
          { key: 'seats', header: 'Хэрэглэгч', width: pixel(110), renderCell: ({ plan }) => <Text>{plan.seat_limit ?? '∞'}</Text> },
          { key: 'features', header: 'Модулиуд', width: proportional(3), renderCell: ({ plan }) => <Text type="supporting" maxLines={2}>{plan.features.join(', ') || 'Суурь'}</Text> },
          { key: 'price', header: 'Үнэ', width: pixel(160), renderCell: ({ plan }) => <Text>{plan.price_amount === null ? '—' : `${plan.price_amount.toLocaleString('mn-MN')} ${plan.currency} / ${CYCLES.find((cycle) => cycle.value === plan.billing_cycle)?.label ?? plan.billing_cycle}`}</Text> },
          { key: 'active', header: 'Төлөв', width: pixel(110), renderCell: ({ plan }) => <Token size="sm" color={plan.is_active ? 'green' : 'gray'} label={plan.is_active ? 'Идэвхтэй' : 'Идэвхгүй'} /> },
          { key: 'actions', header: '', width: pixel(60), renderCell: ({ plan }) => superadmin ? <IconButton label="Засах" icon={<Pencil size={14} />} size="sm" variant="ghost" onClick={() => setEditing(plan)} /> : null },
        ]} />}
    </Card>
    {editing && <PlanDialog plan={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
  </VStack>
}

interface AuditRow extends Record<string, unknown> { id: number; event: ConsoleAuditEvent }

export function AuditPage() {
  const [tenantId, setTenantId] = useState<string | null>(null)
  const tenants = useConsoleTenants({})
  const audit = useConsoleAudit(tenantId ? Number(tenantId) : undefined)
  const names = new Map((tenants.data ?? []).map((tenant) => [tenant.id, tenant.name]))
  const rows: AuditRow[] = (audit.data ?? []).map((event) => ({ id: event.id, event }))
  return <VStack gap={4}>
    <VStack gap={0}><Heading level={1}>Аудит</Heading><Text type="supporting">Операторын болон лицензийн бүх үйлдэл.</Text></VStack>
    <Selector label="Байгууллага" isLabelHidden value={tenantId} onChange={setTenantId} hasClear placeholder="Бүх байгууллага" width={280}
      options={(tenants.data ?? []).map((tenant) => ({ value: String(tenant.id), label: tenant.name }))} />
    <Card padding={0}>
      {audit.isLoading ? <Skeleton height={240} /> : rows.length === 0 ? <EmptyState title="Бүртгэл алга" />
        : <Table<AuditRow> data={rows} idKey="id" density="compact" columns={[
          { key: 'time', header: 'Хугацаа', width: pixel(170), renderCell: ({ event }) => <Text type="supporting">{new Date(event.created_at).toLocaleString('mn-MN')}</Text> },
          { key: 'action', header: 'Үйлдэл', width: proportional(2), renderCell: ({ event }) => <Text weight="medium">{event.action}</Text> },
          { key: 'tenant', header: 'Байгууллага', width: proportional(2), renderCell: ({ event }) => <Text>{event.organization_id ? names.get(event.organization_id) ?? `#${event.organization_id}` : '—'}</Text> },
          { key: 'actor', header: 'Хэн', width: proportional(1), renderCell: ({ event }) => <Text type="supporting">{event.operator_id ? `Оператор #${event.operator_id}` : event.account_id ? `Хэрэглэгч #${event.account_id}` : '—'}</Text> },
          { key: 'details', header: 'Дэлгэрэнгүй', width: proportional(3), renderCell: ({ event }) => <Text type="supporting" maxLines={2}>{Object.keys(event.details).length ? JSON.stringify(event.details) : '—'}</Text> },
        ]} />}
    </Card>
  </VStack>
}

export function SystemPage() {
  const system = useConsoleSystem()
  if (system.isLoading) return <Skeleton height={300} />
  if (system.isError || !system.data) return <Banner status="error" collapsible={false} title={consoleError(system.error, 'Системийн төлөвийг ачаалж чадсангүй')} />
  const { rls, license_signing: signing, tenants, routing } = system.data
  return <VStack gap={4}>
    <VStack gap={0}><Heading level={1}>Систем ба аюулгүй байдал</Heading><Text type="supporting">Тусгаарлалт, лицензийн гарын үсэг, хүсэлтийн чиглүүлэлт.</Text></VStack>
    {rls.available && !rls.effective && <Banner status="warning" collapsible={false} title="PostgreSQL RLS идэвхгүй байна"
      description={`API «${rls.db_role}» эрхээр холбогдсон (superuser=${String(rls.superuser)}, bypassrls=${String(rls.bypass_rls)}). ORM хамгаалалт ажиллаж байгаа ч өгөгдлийн сангийн түвшний тусгаарлалтад ops/sql/oyuns_app_role.sql-ээр oyuns_app эрх үүсгэж DATABASE_URL-д ашиглана уу.`} />}
    <Grid columns={{ minWidth: 320 }} gap={4}>
      <Card padding={5}>
        <VStack gap={3}>
          <HStack gap={2} vAlign="center"><StatusDot variant={rls.effective ? 'success' : 'warning'} label={rls.effective ? 'Идэвхтэй' : 'Хагас'} /><Heading level={3}>Өгөгдлийн тусгаарлалт</Heading></HStack>
          <MetadataList columns={1}>
            <MetadataListItem label="DB эрх">{rls.db_role ?? '—'}</MetadataListItem>
            <MetadataListItem label="RLS хүснэгт">{`${rls.protected_tables ?? 0} / ${rls.tenant_tables ?? 0}`}</MetadataListItem>
            <MetadataListItem label="Strict горим">{rls.strict ? 'Асаалттай' : 'Унтраалттай'}</MetadataListItem>
          </MetadataList>
        </VStack>
      </Card>
      <Card padding={5}>
        <VStack gap={3}>
          <HStack gap={2} vAlign="center"><StatusDot variant={signing.available ? 'success' : 'error'} label={signing.available ? 'Бэлэн' : 'Тохируулаагүй'} /><Heading level={3}>Лицензийн гарын үсэг (Ed25519)</Heading></HStack>
          <MetadataList columns={1}>
            <MetadataListItem label="Түлхүүрийн ID">{signing.key_id}</MetadataListItem>
            <MetadataListItem label="Хөнгөлөлтийн хугацаа">{`${signing.grace_days} хоног`}</MetadataListItem>
          </MetadataList>
          {!signing.available && <Text type="supporting">LICENSE_SIGNING_PRIVATE_KEY тохируулаагүй — `python -m scripts.platform_admin generate-license-keys`.</Text>}
          {signing.public_key_pem && <CodeBlock code={signing.public_key_pem} title="Нийтийн түлхүүр (шалгагчдад)" language="plaintext" hasCopyButton isWrapped size="sm" />}
        </VStack>
      </Card>
      <Card padding={5}>
        <VStack gap={3}>
          <Heading level={3}>Чиглүүлэлт ба байгууллагууд</Heading>
          <MetadataList columns={1}>
            <MetadataListItem label="Үндсэн хаягууд">{routing.root_hosts.join(', ') || '—'}</MetadataListItem>
            <MetadataListItem label="Subdomain домэйн">{routing.tenant_base_domain ?? 'Тохируулаагүй'}</MetadataListItem>
            <MetadataListItem label="Үл мэдэгдэх хаяг">{routing.unknown_host_policy}</MetadataListItem>
            <MetadataListItem label="Консолын хаяг">{routing.console_hosts.join(', ') || 'Аль ч үндсэн хаяг'}</MetadataListItem>
            <MetadataListItem label="Байгууллагууд">{Object.entries(tenants).map(([status, count]) => `${TENANT_STATUS[status as keyof typeof TENANT_STATUS]?.label ?? status}: ${count}`).join(' · ') || '—'}</MetadataListItem>
          </MetadataList>
        </VStack>
      </Card>
    </Grid>
  </VStack>
}

interface OperatorRow extends Record<string, unknown> { id: number; operator: Operator }

export function OperatorsPage() {
  const me = useConsoleSession((state) => state.operator)
  const operators = useOperators(true)
  const create = useCreateOperator()
  const update = useUpdateOperator()
  const [draft, setDraft] = useState({ email: '', password: '', display_name: '', role: 'support' as Operator['role'] })
  const add = async () => {
    try {
      await create.mutateAsync({ ...draft, display_name: draft.display_name || undefined })
      toast.success('Оператор нэмэгдлээ')
      setDraft({ email: '', password: '', display_name: '', role: 'support' })
    } catch (error) { toast.error(consoleError(error, 'Оператор нэмж чадсангүй')) }
  }
  const change = async (operator: Operator, patch: { role?: Operator['role']; status?: Operator['status'] }) => {
    try { await update.mutateAsync({ id: operator.id, ...patch }); toast.success('Хадгалагдлаа') } catch (error) { toast.error(consoleError(error, 'Хадгалж чадсангүй')) }
  }
  const rows: OperatorRow[] = (operators.data ?? []).map((operator) => ({ id: operator.id, operator }))
  return <VStack gap={4}>
    <VStack gap={0}><Heading level={1}>Операторууд</Heading><Text type="supporting">Superadmin — бүх өөрчлөлт; Support — зөвхөн харах.</Text></VStack>
    <Card padding={5}>
      <VStack gap={3}>
        <Heading level={3}>Оператор нэмэх</Heading>
        <FormLayout>
          <TextInput label="И-мэйл" value={draft.email} onChange={(email) => setDraft({ ...draft, email })} type="email" isRequired />
          <TextInput label="Нэр" value={draft.display_name} onChange={(display_name) => setDraft({ ...draft, display_name })} isOptional />
          <TextInput label="Нууц үг (12+)" value={draft.password} onChange={(password) => setDraft({ ...draft, password })} type="password" isRequired />
          <Selector label="Эрх" value={draft.role} onChange={(role) => setDraft({ ...draft, role: (role ?? 'support') as Operator['role'] })}
            options={[{ value: 'support', label: 'Support (унших)' }, { value: 'superadmin', label: 'Superadmin' }]} />
        </FormLayout>
        <HStack hAlign="end"><Button label="Нэмэх" variant="primary" clickAction={add} isDisabled={!draft.email || draft.password.length < 12} /></HStack>
      </VStack>
    </Card>
    <Card padding={0}>
      {operators.isLoading ? <Skeleton height={160} /> : <Table<OperatorRow> data={rows} idKey="id" density="compact" columns={[
        { key: 'email', header: 'Оператор', width: proportional(3), renderCell: ({ operator }) => <VStack gap={0}><Text weight="semibold">{operator.email}</Text><Text type="supporting">{operator.display_name ?? ''}</Text></VStack> },
        { key: 'role', header: 'Эрх', width: pixel(200), renderCell: ({ operator }) => <Selector label="Эрх" isLabelHidden value={operator.role} isDisabled={operator.id === me?.id}
          onChange={(role) => { if (role && role !== operator.role) void change(operator, { role: role as Operator['role'] }) }}
          options={[{ value: 'support', label: 'Support' }, { value: 'superadmin', label: 'Superadmin' }]} /> },
        { key: 'last', header: 'Сүүлд нэвтэрсэн', width: proportional(2), renderCell: ({ operator }) => <Text type="supporting">{operator.last_login_at ? new Date(operator.last_login_at).toLocaleString('mn-MN') : '—'}</Text> },
        { key: 'status', header: '', width: pixel(160), renderCell: ({ operator }) => operator.id === me?.id ? <Token size="sm" label="Та" />
          : <Button label={operator.status === 'active' ? 'Идэвхгүй болгох' : 'Идэвхжүүлэх'} size="sm" variant="ghost" clickAction={() => change(operator, { status: operator.status === 'active' ? 'disabled' : 'active' })} /> },
      ]} />}
    </Card>
  </VStack>
}
