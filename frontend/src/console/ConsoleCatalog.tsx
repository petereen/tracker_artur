import { useState } from 'react'
import { DialogScrollBody } from '../components/DialogScrollBody'
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
import { useTranslation } from 'react-i18next'
import { intlLocale } from '../utils/locale'
import type { TenantFeatureCode } from '../api/tenancy'
import {
  type BillingCycle, type ConsoleAuditEvent, type ConsolePlan, type Operator,
  consoleError, useConsoleAudit, useConsoleSession, useConsoleSystem, useConsoleTenants, useCreateOperator, useOperators, usePlans,
  useSavePlan, useUpdateOperator,
} from './consoleApi'
import { CYCLES, FeatureChecklist, TENANT_STATUS } from './ConsoleTenants'

function PlanDialog({ plan, onClose }: { plan: ConsolePlan | null; onClose: () => void }) {
  const { t } = useTranslation()
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
      toast.success(t('cc.planSaved'))
      onClose()
    } catch (error) { toast.error(consoleError(error, t('cc.planSaveFailed'))) }
  }
  return <Dialog isOpen onOpenChange={(open) => { if (!open) onClose() }} width={620} purpose="form" maxHeight="90dvh">
    <DialogHeader title={plan ? t('cc.editPlan', { code: plan.code }) : t('cc.newPlan')} subtitle={t('cc.planHint')} onOpenChange={(open) => { if (!open) onClose() }} />
    <DialogScrollBody label={t('cc.planFields')} actions={<><Button label={t('ct.cancel')} variant="ghost" onClick={onClose} /><Button label={t('ct.save')} variant="primary" clickAction={submit} isDisabled={!draft.code || !draft.name} /></>}>
      <FormLayout>
        <TextInput label={t('cc.code')} value={draft.code} onChange={(value) => set('code', value.toLowerCase())} isRequired isDisabled={Boolean(plan)} placeholder="professional" />
        <TextInput label={t('cc.name')} value={draft.name} onChange={(value) => set('name', value)} isRequired />
        <TextInput label={t('cc.description')} value={draft.description} onChange={(value) => set('description', value)} isOptional />
        <NumberInput label={t('ct.seats')} value={draft.seat_limit} onChange={(value) => set('seat_limit', value)} min={1} hasClear description={t('ct.unlimitedHint')} />
        <Selector label={t('ct.billingCycle')} value={draft.billing_cycle} onChange={(value) => set('billing_cycle', (value ?? 'monthly') as BillingCycle)} options={CYCLES} />
        <NumberInput label={t('cc.price')} value={draft.price_amount} onChange={(value) => set('price_amount', value)} min={0} hasClear units={draft.currency} />
        <NumberInput label={t('cc.sortOrder')} value={draft.sort_order} onChange={(value) => set('sort_order', value)} />
        <CheckboxInput label={t('cc.active')} value={draft.is_active} onChange={(value) => set('is_active', value)} />
      </FormLayout>
      <FeatureChecklist value={draft.features} onChange={(features) => set('features', features)} />
    </DialogScrollBody>
  </Dialog>
}

interface PlanRow extends Record<string, unknown> { id: number; plan: ConsolePlan }

export function PlansPage() {
  const { t } = useTranslation()
  const superadmin = useConsoleSession((state) => state.operator?.role === 'superadmin')
  const plans = usePlans()
  const [editing, setEditing] = useState<ConsolePlan | 'new' | null>(null)
  const rows: PlanRow[] = (plans.data ?? []).map((plan) => ({ id: plan.id, plan }))
  return <VStack gap={4}>
    <HStack gap={2} vAlign="center" hAlign="between">
      <VStack gap={0}><Heading level={1}>{t('con.nav.plans')}</Heading><Text type="supporting">{t('cc.plansHint')}</Text></VStack>
      {superadmin && <Button label={t('cc.newPlan')} variant="primary" icon={<Plus size={15} />} onClick={() => setEditing('new')} />}
    </HStack>
    <Card padding={0}>
      {plans.isLoading ? <Skeleton height={200} /> : rows.length === 0 ? <EmptyState title={t('cc.noPlans')} />
        : <Table<PlanRow> data={rows} idKey="id" density="compact" columns={[
          { key: 'name', header: t('ct.plan'), width: proportional(2), renderCell: ({ plan }) => <VStack gap={0}><Text weight="semibold">{plan.name}</Text><Text type="supporting">{plan.code}</Text></VStack> },
          { key: 'seats', header: t('ct.col.users'), width: pixel(110), renderCell: ({ plan }) => <Text>{plan.seat_limit ?? '∞'}</Text> },
          { key: 'features', header: t('ct.modules'), width: proportional(3), renderCell: ({ plan }) => <Text type="supporting" maxLines={2}>{plan.features.join(', ') || t('cc.base')}</Text> },
          { key: 'price', header: t('cc.price'), width: pixel(160), renderCell: ({ plan }) => <Text>{plan.price_amount === null ? '—' : `${plan.price_amount.toLocaleString(intlLocale())} ${plan.currency} / ${CYCLES.find((cycle) => cycle.value === plan.billing_cycle)?.label ?? plan.billing_cycle}`}</Text> },
          { key: 'active', header: t('ct.status'), width: pixel(110), renderCell: ({ plan }) => <Token size="sm" color={plan.is_active ? 'green' : 'gray'} label={plan.is_active ? t('cc.active') : t('cc.inactive')} /> },
          { key: 'actions', header: '', width: pixel(60), renderCell: ({ plan }) => superadmin ? <IconButton label={t('cc.edit')} icon={<Pencil size={14} />} size="sm" variant="ghost" onClick={() => setEditing(plan)} /> : null },
        ]} />}
    </Card>
    {editing && <PlanDialog plan={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
  </VStack>
}

interface AuditRow extends Record<string, unknown> { id: number; event: ConsoleAuditEvent }

export function AuditPage() {
  const { t } = useTranslation()
  const [tenantId, setTenantId] = useState<string | null>(null)
  const tenants = useConsoleTenants({})
  const audit = useConsoleAudit(tenantId ? Number(tenantId) : undefined)
  const names = new Map((tenants.data ?? []).map((tenant) => [tenant.id, tenant.name]))
  const rows: AuditRow[] = (audit.data ?? []).map((event) => ({ id: event.id, event }))
  return <VStack gap={4}>
    <VStack gap={0}><Heading level={1}>{t('con.nav.audit')}</Heading><Text type="supporting">{t('cc.auditHint')}</Text></VStack>
    <Selector label={t('ct.col.tenant')} isLabelHidden value={tenantId} onChange={setTenantId} hasClear placeholder={t('ct.allTenants')} width={280}
      options={(tenants.data ?? []).map((tenant) => ({ value: String(tenant.id), label: tenant.name }))} />
    <Card padding={0}>
      {audit.isLoading ? <Skeleton height={240} /> : rows.length === 0 ? <EmptyState title={t('cc.noRecords')} />
        : <Table<AuditRow> data={rows} idKey="id" density="compact" columns={[
          { key: 'time', header: t('cc.col.time'), width: pixel(170), renderCell: ({ event }) => <Text type="supporting">{new Date(event.created_at).toLocaleString(intlLocale())}</Text> },
          { key: 'action', header: t('cc.col.action'), width: proportional(2), renderCell: ({ event }) => <Text weight="medium">{event.action}</Text> },
          { key: 'tenant', header: t('ct.col.tenant'), width: proportional(2), renderCell: ({ event }) => <Text>{event.organization_id ? names.get(event.organization_id) ?? `#${event.organization_id}` : '—'}</Text> },
          { key: 'actor', header: t('cc.col.who'), width: proportional(1), renderCell: ({ event }) => <Text type="supporting">{event.operator_id ? t('cc.actorOperator', { id: event.operator_id }) : event.account_id ? t('cc.actorUser', { id: event.account_id }) : '—'}</Text> },
          { key: 'details', header: t('cc.col.details'), width: proportional(3), renderCell: ({ event }) => <Text type="supporting" maxLines={2}>{Object.keys(event.details).length ? JSON.stringify(event.details) : '—'}</Text> },
        ]} />}
    </Card>
  </VStack>
}

export function SystemPage() {
  const { t } = useTranslation()
  const system = useConsoleSystem()
  if (system.isLoading) return <Skeleton height={300} />
  if (system.isError || !system.data) return <Banner status="error" collapsible={false} title={consoleError(system.error, t('cc.systemFailed'))} />
  const { rls, license_signing: signing, tenants, routing } = system.data
  return <VStack gap={4}>
    <VStack gap={0}><Heading level={1}>{t('con.nav.system')}</Heading><Text type="supporting">{t('cc.systemHint')}</Text></VStack>
    {rls.available && !rls.effective && <Banner status="warning" collapsible={false} title={t('cc.rlsOff')}
      description={t('cc.rlsDesc', { role: rls.db_role, superuser: String(rls.superuser), bypass: String(rls.bypass_rls) })} />}
    <Grid columns={{ minWidth: 320 }} gap={4}>
      <Card padding={5}>
        <VStack gap={3}>
          <HStack gap={2} vAlign="center"><StatusDot variant={rls.effective ? 'success' : 'warning'} label={rls.effective ? t('cc.rls.active') : t('cc.partial')} /><Heading level={3}>{t('cc.isolation')}</Heading></HStack>
          <MetadataList columns={1}>
            <MetadataListItem label={t('cc.dbRole')}>{rls.db_role ?? '—'}</MetadataListItem>
            <MetadataListItem label={t('cc.rlsTables')}>{`${rls.protected_tables ?? 0} / ${rls.tenant_tables ?? 0}`}</MetadataListItem>
            <MetadataListItem label={t('cc.strict')}>{rls.strict ? t('cc.on') : t('cc.off')}</MetadataListItem>
          </MetadataList>
        </VStack>
      </Card>
      <Card padding={5}>
        <VStack gap={3}>
          <HStack gap={2} vAlign="center"><StatusDot variant={signing.available ? 'success' : 'error'} label={signing.available ? t('cc.ready') : t('cc.notConfigured')} /><Heading level={3}>{t('cc.signing')}</Heading></HStack>
          <MetadataList columns={1}>
            <MetadataListItem label={t('cc.keyId')}>{signing.key_id}</MetadataListItem>
            <MetadataListItem label={t('cc.grace')}>{t('cc.days', { n: signing.grace_days })}</MetadataListItem>
          </MetadataList>
          {!signing.available && <Text type="supporting">{t('cc.signingMissing')}</Text>}
          {signing.public_key_pem && <CodeBlock code={signing.public_key_pem} title={t('cc.publicKey')} language="plaintext" hasCopyButton isWrapped size="sm" />}
        </VStack>
      </Card>
      <Card padding={5}>
        <VStack gap={3}>
          <Heading level={3}>{t('cc.routing')}</Heading>
          <MetadataList columns={1}>
            <MetadataListItem label={t('cc.rootHosts')}>{routing.root_hosts.join(', ') || '—'}</MetadataListItem>
            <MetadataListItem label={t('cc.subdomain')}>{routing.tenant_base_domain ?? t('cc.notConfigured')}</MetadataListItem>
            <MetadataListItem label={t('cc.unknownHost')}>{routing.unknown_host_policy}</MetadataListItem>
            <MetadataListItem label={t('cc.customDomain')}>{routing.custom_domains?.provider ? t('cc.cname', { target: routing.custom_domains.cname_target, limit: routing.custom_domains.limit_per_tenant }) : t('cc.notConfigured')}</MetadataListItem>
            <MetadataListItem label={t('cc.consoleHost')}>{routing.console_hosts.join(', ') || t('cc.anyRoot')}</MetadataListItem>
            <MetadataListItem label={t('ct.tenants')}>{Object.entries(tenants).map(([status, count]) => `${TENANT_STATUS[status as keyof typeof TENANT_STATUS]?.label ?? status}: ${count}`).join(' · ') || '—'}</MetadataListItem>
          </MetadataList>
        </VStack>
      </Card>
    </Grid>
  </VStack>
}

interface OperatorRow extends Record<string, unknown> { id: number; operator: Operator }

export function OperatorsPage() {
  const { t } = useTranslation()
  const me = useConsoleSession((state) => state.operator)
  const operators = useOperators(true)
  const create = useCreateOperator()
  const update = useUpdateOperator()
  const [draft, setDraft] = useState({ email: '', password: '', display_name: '', role: 'support' as Operator['role'] })
  const add = async () => {
    try {
      await create.mutateAsync({ ...draft, display_name: draft.display_name || undefined })
      toast.success(t('cc.operatorAdded'))
      setDraft({ email: '', password: '', display_name: '', role: 'support' })
    } catch (error) { toast.error(consoleError(error, t('cc.operatorAddFailed'))) }
  }
  const change = async (operator: Operator, patch: { role?: Operator['role']; status?: Operator['status'] }) => {
    try { await update.mutateAsync({ id: operator.id, ...patch }); toast.success(t('ct.saved')) } catch (error) { toast.error(consoleError(error, t('ct.saveFailed'))) }
  }
  const resetTwoFactor = async (operator: Operator) => {
    if (!window.confirm(t('cc.confirmReset', { email: operator.email }))) return
    try { await update.mutateAsync({ id: operator.id, reset_two_factor: true }); toast.success(t('cc.tfReset')) } catch (error) { toast.error(consoleError(error, t('cc.tfResetFailed'))) }
  }
  const rows: OperatorRow[] = (operators.data ?? []).map((operator) => ({ id: operator.id, operator }))
  return <VStack gap={4}>
    <VStack gap={0}><Heading level={1}>{t('con.nav.operators')}</Heading><Text type="supporting">{t('cc.operatorsHint')}</Text></VStack>
    <Card padding={5}>
      <VStack gap={3}>
        <Heading level={3}>{t('cc.addOperator')}</Heading>
        <FormLayout>
          <TextInput label={t('con.email')} value={draft.email} onChange={(email) => setDraft({ ...draft, email })} type="email" isRequired />
          <TextInput label={t('cc.displayName')} value={draft.display_name} onChange={(display_name) => setDraft({ ...draft, display_name })} isOptional />
          <TextInput label={t('cc.password12')} value={draft.password} onChange={(password) => setDraft({ ...draft, password })} type="password" isRequired />
          <Selector label={t('cc.role')} value={draft.role} onChange={(role) => setDraft({ ...draft, role: (role ?? 'support') as Operator['role'] })}
            options={[{ value: 'support', label: t('con.supportRole') }, { value: 'superadmin', label: 'Superadmin' }]} />
        </FormLayout>
        <HStack hAlign="end"><Button label={t('ct.add')} variant="primary" clickAction={add} isDisabled={!draft.email || draft.password.length < 12} /></HStack>
      </VStack>
    </Card>
    <Card padding={0}>
      {operators.isLoading ? <Skeleton height={160} /> : <Table<OperatorRow> data={rows} idKey="id" density="compact" columns={[
        { key: 'email', header: t('cc.col.operator'), width: proportional(3), renderCell: ({ operator }) => <VStack gap={0}><Text weight="semibold">{operator.email}</Text><Text type="supporting">{operator.display_name ?? ''}</Text></VStack> },
        { key: 'role', header: t('cc.role'), width: pixel(200), renderCell: ({ operator }) => <Selector label={t('cc.role')} isLabelHidden value={operator.role} isDisabled={operator.id === me?.id}
          onChange={(role) => { if (role && role !== operator.role) void change(operator, { role: role as Operator['role'] }) }}
          options={[{ value: 'support', label: 'Support' }, { value: 'superadmin', label: 'Superadmin' }]} /> },
        { key: 'twoFactor', header: t('cc.col.twoFactor'), width: pixel(230), renderCell: ({ operator }) => <HStack gap={2} vAlign="center">
          <Token size="sm" label={operator.two_factor_enabled ? t('cc.tf.on') : t('cc.tf.off')} />
          {operator.two_factor_enabled && <Button label={t('cc.reset')} size="sm" variant="ghost" clickAction={() => resetTwoFactor(operator)} />}
        </HStack> },
        { key: 'last', header: t('cc.col.lastLogin'), width: proportional(2), renderCell: ({ operator }) => <Text type="supporting">{operator.last_login_at ? new Date(operator.last_login_at).toLocaleString(intlLocale()) : '—'}</Text> },
        { key: 'status', header: '', width: pixel(160), renderCell: ({ operator }) => operator.id === me?.id ? <Token size="sm" label={t('cc.you')} />
          : <Button label={operator.status === 'active' ? t('cc.deactivate') : t('cc.activate')} size="sm" variant="ghost" clickAction={() => change(operator, { status: operator.status === 'active' ? 'disabled' : 'active' })} /> },
      ]} />}
    </Card>
  </VStack>
}
