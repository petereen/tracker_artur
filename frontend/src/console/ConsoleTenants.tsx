import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import toast from 'react-hot-toast'
import { ArrowLeft, Ban, Copy, KeyRound, Play, Plus, RefreshCw, ShieldOff, Trash2 } from 'lucide-react'
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
import { Link } from '@astryxdesign/core/Link'
import { MetadataList, MetadataListItem } from '@astryxdesign/core/MetadataList'
import { NumberInput } from '@astryxdesign/core/NumberInput'
import { Selector } from '@astryxdesign/core/Selector'
import { Skeleton } from '@astryxdesign/core/Skeleton'
import { Table, pixel, proportional } from '@astryxdesign/core/Table'
import { Text } from '@astryxdesign/core/Text'
import { TextInput } from '@astryxdesign/core/TextInput'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import type { TenantFeatureCode } from '../api/tenancy'
import { DialogScrollBody } from '../components/DialogScrollBody'
import { RouterLink } from '../components/budget/shared'
import { LICENSE_STATE, formatDate } from '../components/TenantLicenseSettings'
import {
  type BillingCycle, type ConsoleLicense, type ConsoleTenant, type LicenseIssueInput, type TenantStatus,
  type ConsoleDomain,
  consoleError, fetchLicenseToken, useAddDomain, useConsoleSession, useConsoleTenant, useConsoleTenants, useCreateTenant,
  useFeatureCatalog, useIssueLicense, useOperatorActivateLicense, usePlans, usePurgeTenant, useRemoveDomain, useRenewLicense,
  useRevokeLicense, useTenantLifecycle, useUpdateTenant, useVerifyDomain,
} from './consoleApi'

export const TENANT_STATUS: Record<TenantStatus, { label: string; color: 'green' | 'blue' | 'orange' | 'red' }> = {
  active: { label: 'Идэвхтэй', color: 'green' },
  pending_activation: { label: 'Идэвхжүүлэлт хүлээж буй', color: 'blue' },
  suspended: { label: 'Түдгэлзсэн', color: 'orange' },
  terminated: { label: 'Хаагдсан', color: 'red' },
}
const LICENSE_STATUS: Record<ConsoleLicense['status'], { label: string; color: 'green' | 'blue' | 'gray' | 'red' }> = {
  active: { label: 'Идэвхтэй', color: 'green' },
  issued: { label: 'Олгосон', color: 'blue' },
  superseded: { label: 'Солигдсон', color: 'gray' },
  revoked: { label: 'Цуцалсан', color: 'red' },
}
export const CYCLES: Array<{ value: BillingCycle; label: string }> = [
  { value: 'monthly', label: 'Сар бүр' }, { value: 'quarterly', label: 'Улирал бүр' }, { value: 'yearly', label: 'Жил бүр' }, { value: 'custom', label: 'Тусгай' },
]
const SLUG = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/

function useIsSuperadmin() {
  return useConsoleSession((state) => state.operator?.role === 'superadmin')
}

function slugify(value: string) {
  return value.toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40)
}

export function FeatureChecklist({ value, onChange, isDisabled }: { value: TenantFeatureCode[]; onChange: (next: TenantFeatureCode[]) => void; isDisabled?: boolean }) {
  const catalog = useFeatureCatalog()
  return <VStack gap={1}>
    <Text weight="semibold">Модулиуд</Text>
    {(catalog.data ?? []).map((feature) => <CheckboxInput key={feature.code} label={feature.label} value={value.includes(feature.code)} isDisabled={isDisabled}
      onChange={(checked) => onChange(checked ? [...value, feature.code] : value.filter((code) => code !== feature.code))}
      description={feature.code === 'legacy_workspace' ? 'Зөвхөн үндсэн байгууллагад хүчинтэй.' : undefined} />)}
  </VStack>
}

/** Shows a freshly issued license key once, ready to copy to the customer. */
export function LicenseTokenDialog({ license, onClose }: { license: ConsoleLicense; onClose: () => void }) {
  return <Dialog isOpen onOpenChange={(open) => { if (!open) onClose() }} width={720} purpose="info">
    <DialogHeader title="Лицензийн түлхүүр" subtitle={`${license.seat_limit} хэрэглэгч · ${formatDate(license.valid_from)} – ${formatDate(license.expires_at)} · ${LICENSE_STATUS[license.status].label}`} onOpenChange={(open) => { if (!open) onClose() }} />
    <VStack gap={4} padding={4}>
      <Text type="supporting">Байгууллагын админ Тохиргоо → Систем ба аюулгүй байдал → «Лиценз ба идэвхжүүлэлт» хэсэгт буулгаж идэвхжүүлнэ. Түлхүүр зөвхөн энэ байгууллагад хүчинтэй.</Text>
      <CodeBlock code={license.token ?? ''} language="plaintext" hasCopyButton isWrapped maxHeight={260} />
      <HStack hAlign="end"><Button label="Хаах" variant="primary" onClick={onClose} /></HStack>
    </VStack>
  </Dialog>
}

interface IssueDraft { seat_limit: number | null; features: TenantFeatureCode[]; billing_cycle: BillingCycle; duration_months: number | null; expires_at: string; notes: string; activate: boolean }

function LicenseFields({ draft, onChange }: { draft: IssueDraft; onChange: (next: IssueDraft) => void }) {
  const set = <K extends keyof IssueDraft>(key: K, value: IssueDraft[K]) => onChange({ ...draft, [key]: value })
  return <VStack gap={3}>
    <FormLayout>
      <NumberInput label="Хэрэглэгчийн тоо" value={draft.seat_limit} onChange={(value) => set('seat_limit', value)} min={1} hasClear isRequired />
      <Selector label="Төлбөрийн мөчлөг" value={draft.billing_cycle} onChange={(value) => set('billing_cycle', (value ?? 'monthly') as BillingCycle)} options={CYCLES} />
      <NumberInput label="Хугацаа (сар)" value={draft.duration_months} onChange={(value) => set('duration_months', value)} min={1} max={120} hasClear isOptional
        description="Хоосон бол мөчлөгөөр (сар/улирал/жил) тооцно." />
      <TextInput label="Эсвэл дуусах огноо" value={draft.expires_at} onChange={(value) => set('expires_at', value)} placeholder="2027-12-31" isOptional description="YYYY-MM-DD. Бөглөсөн бол хугацаанаас давуу." />
      <TextInput label="Тэмдэглэл" value={draft.notes} onChange={(value) => set('notes', value)} isOptional placeholder="Нэхэмжлэх №, гэрээ…" />
    </FormLayout>
    <FeatureChecklist value={draft.features} onChange={(features) => set('features', features)} />
    <CheckboxInput label="Шууд идэвхжүүлэх" description="Байгууллагын админ түлхүүр оруулахыг хүлээхгүйгээр идэвхжүүлнэ." value={draft.activate} onChange={(value) => set('activate', value)} />
  </VStack>
}

function toIssueInput(draft: IssueDraft): LicenseIssueInput {
  return {
    seat_limit: draft.seat_limit,
    features: draft.features,
    billing_cycle: draft.billing_cycle,
    duration_months: draft.expires_at ? null : draft.duration_months,
    expires_at: draft.expires_at ? `${draft.expires_at}T23:59:59Z` : null,
    notes: draft.notes || null,
    activate: draft.activate,
  }
}

const DATE = /^\d{4}-\d{2}-\d{2}$/

function IssueLicenseDialog({ tenant, renewing, onClose, onIssued }: { tenant: ConsoleTenant; renewing?: ConsoleLicense; onClose: () => void; onIssued: (license: ConsoleLicense) => void }) {
  const issue = useIssueLicense()
  const renew = useRenewLicense()
  const [draft, setDraft] = useState<IssueDraft>({
    seat_limit: renewing?.seat_limit ?? tenant.seat_limit ?? 10,
    features: renewing?.features ?? tenant.features,
    billing_cycle: renewing?.billing_cycle ?? tenant.billing_cycle,
    duration_months: null,
    expires_at: '',
    notes: '',
    activate: Boolean(renewing && renewing.status === 'active'),
  })
  const submit = async () => {
    try {
      const license = renewing
        ? await renew.mutateAsync({ id: renewing.id, ...toIssueInput(draft) })
        : await issue.mutateAsync({ tenantId: tenant.id, ...toIssueInput(draft) })
      toast.success(renewing ? 'Шинэ лиценз олгогдлоо' : 'Лиценз олгогдлоо')
      onIssued(license)
    } catch (error) {
      toast.error(consoleError(error, 'Лиценз олгож чадсангүй'))
    }
  }
  return <Dialog isOpen onOpenChange={(open) => { if (!open) onClose() }} width={640} purpose="form" maxHeight="90dvh">
    <DialogHeader title={renewing ? 'Лиценз сунгах / өргөтгөх' : 'Лиценз олгох'} subtitle={renewing ? 'Шинэ түлхүүр өмнөхийг орлоно; хугацаа өмнөх лицензийн дуусах огнооноос үргэлжилнэ.' : `${tenant.name} (${tenant.slug})`} onOpenChange={(open) => { if (!open) onClose() }} />
    <DialogScrollBody label="Лицензийн талбарууд" actions={<><Button label="Болих" variant="ghost" onClick={onClose} />
      <Button label={renewing ? 'Шинэ түлхүүр олгох' : 'Олгох'} variant="primary" clickAction={submit} isDisabled={!draft.seat_limit || (Boolean(draft.expires_at) && !DATE.test(draft.expires_at))} /></>}>
      <LicenseFields draft={draft} onChange={setDraft} />
    </DialogScrollBody>
  </Dialog>
}

function CreateTenantDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (tenant: ConsoleTenant, license: ConsoleLicense | null) => void }) {
  const plans = usePlans()
  const create = useCreateTenant()
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [slugEdited, setSlugEdited] = useState(false)
  const [planCode, setPlanCode] = useState<string | null>('starter')
  const [contact, setContact] = useState('')
  const [adminEmail, setAdminEmail] = useState('')
  const [adminPassword, setAdminPassword] = useState('')
  const [issueLicense, setIssueLicense] = useState(true)
  const plan = plans.data?.find((row) => row.code === planCode)
  const [license, setLicense] = useState<IssueDraft>({ seat_limit: 10, features: ['contracts'], billing_cycle: 'monthly', duration_months: null, expires_at: '', notes: '', activate: false })

  useEffect(() => {
    if (plan) setLicense((current) => ({ ...current, seat_limit: plan.seat_limit ?? current.seat_limit, features: plan.features, billing_cycle: plan.billing_cycle }))
  }, [plan])
  useEffect(() => { if (!slugEdited) setSlug(slugify(name)) }, [name, slugEdited])

  const valid = name.trim() && SLUG.test(slug) && adminEmail.trim() && adminPassword.length >= 10 && license.seat_limit
  const submit = async () => {
    try {
      const result = await create.mutateAsync({
        name: name.trim(), slug, plan_code: planCode, seat_limit: license.seat_limit, features: license.features,
        billing_cycle: license.billing_cycle, contact_email: contact.trim() || null,
        admin: { email: adminEmail.trim(), password: adminPassword },
        license: issueLicense ? toIssueInput(license) : null,
      })
      toast.success('Байгууллага үүслээ')
      onCreated(result.tenant, result.license)
    } catch (error) {
      toast.error(consoleError(error, 'Байгууллага үүсгэж чадсангүй'))
    }
  }
  return <Dialog isOpen onOpenChange={(open) => { if (!open) onClose() }} width={720} purpose="form" maxHeight="92dvh">
    <DialogHeader title="Шинэ байгууллага" subtitle="Байгууллага, анхны админ, багц ба лицензийг нэг дор үүсгэнэ." onOpenChange={(open) => { if (!open) onClose() }} />
    <DialogScrollBody label="Шинэ байгууллагын талбарууд" actions={<><Button label="Болих" variant="ghost" onClick={onClose} /><Button label="Үүсгэх" variant="primary" clickAction={submit} isDisabled={!valid} /></>}>
      <FormLayout>
        <TextInput label="Байгууллагын нэр" value={name} onChange={setName} isRequired />
        <TextInput label="Хаяг (subdomain)" value={slug} onChange={(value) => { setSlugEdited(true); setSlug(value.toLowerCase()) }} isRequired
          description="Жижиг латин үсэг, тоо, зураас. Жишээ: acme → acme.oyunserp.com" status={slug && !SLUG.test(slug) ? { type: 'error', message: 'Буруу хэлбэр' } : undefined} />
        <Selector label="Багц" value={planCode} onChange={setPlanCode} hasClear options={(plans.data ?? []).map((row) => ({ value: row.code, label: row.name, description: `${row.seat_limit ?? '∞'} хэрэглэгч` }))} />
        <TextInput label="Холбоо барих и-мэйл" value={contact} onChange={setContact} isOptional type="email" />
        <TextInput label="Анхны админы нэвтрэх нэр" value={adminEmail} onChange={setAdminEmail} isRequired description="Анх нэвтрэхэд нууц үгээ солино." />
        <TextInput label="Анхны нууц үг" value={adminPassword} onChange={setAdminPassword} type="password" isRequired
          status={adminPassword && adminPassword.length < 10 ? { type: 'error', message: '10+ тэмдэгт' } : undefined} />
      </FormLayout>
      <CheckboxInput label="Лицензийн түлхүүр одоо олгох" value={issueLicense} onChange={setIssueLicense} />
      {issueLicense ? <LicenseFields draft={license} onChange={setLicense} />
        : <FormLayout><NumberInput label="Хэрэглэгчийн хязгаар" value={license.seat_limit} onChange={(value) => setLicense({ ...license, seat_limit: value })} min={1} hasClear /></FormLayout>}
    </DialogScrollBody>
  </Dialog>
}

interface TenantRow extends Record<string, unknown> { id: number; tenant: ConsoleTenant }

export function TenantsPage() {
  const superadmin = useIsSuperadmin()
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<string | null>(null)
  const tenants = useConsoleTenants({ q: search.trim(), status: status ?? undefined })
  const [creating, setCreating] = useState(false)
  const [issued, setIssued] = useState<ConsoleLicense | null>(null)
  const rows: TenantRow[] = (tenants.data ?? []).map((tenant) => ({ id: tenant.id, tenant }))
  const totals = useMemo(() => (tenants.data ?? []).reduce((acc, tenant) => ({ ...acc, [tenant.status]: (acc[tenant.status] ?? 0) + 1 }), {} as Record<string, number>), [tenants.data])

  return <VStack gap={4}>
    <HStack gap={2} vAlign="center" hAlign="between" wrap="wrap">
      <VStack gap={0}><Heading level={1}>Байгууллагууд</Heading><Text type="supporting">{`${rows.length} байгууллага · ${totals.active ?? 0} идэвхтэй · ${totals.suspended ?? 0} түдгэлзсэн`}</Text></VStack>
      {superadmin && <Button label="Шинэ байгууллага" variant="primary" icon={<Plus size={15} />} onClick={() => setCreating(true)} />}
    </HStack>
    <HStack gap={2} wrap="wrap">
      <TextInput label="Хайх" isLabelHidden value={search} onChange={setSearch} placeholder="Нэр, хаяг…" hasClear width={260} />
      <Selector label="Төлөв" isLabelHidden value={status} onChange={setStatus} hasClear placeholder="Бүх төлөв" width={220}
        options={Object.entries(TENANT_STATUS).map(([value, meta]) => ({ value, label: meta.label }))} />
    </HStack>
    <Card padding={0}>
      {tenants.isLoading ? <Skeleton height={240} /> : tenants.isError ? <Banner status="error" collapsible={false} title={consoleError(tenants.error, 'Жагсаалтыг ачаалж чадсангүй')} />
        : rows.length === 0 ? <EmptyState title="Байгууллага олдсонгүй" />
          : <Table<TenantRow> data={rows} idKey="id" density="compact" hasHover columns={[
            { key: 'name', header: 'Байгууллага', width: proportional(3), renderCell: ({ tenant }) => <VStack gap={0}>
              <HStack gap={1} vAlign="center"><Link as={RouterLink} href={`/platform/tenants/${tenant.id}`}>{tenant.name}</Link>{tenant.is_primary && <Token size="sm" color="purple" label="Үндсэн" />}</HStack>
              <Text type="supporting">{tenant.slug}</Text>
            </VStack> },
            { key: 'status', header: 'Төлөв', width: pixel(230), renderCell: ({ tenant }) => <Token size="sm" color={TENANT_STATUS[tenant.status].color} label={TENANT_STATUS[tenant.status].label} /> },
            { key: 'plan', header: 'Багц', width: proportional(1), renderCell: ({ tenant }) => <Text>{tenant.plan_code ?? '—'}</Text> },
            { key: 'seats', header: 'Хэрэглэгч', width: pixel(110), renderCell: ({ tenant }) => <Text>{`${tenant.seats_used} / ${tenant.seat_limit ?? '∞'}`}</Text> },
            { key: 'license', header: 'Лиценз', width: proportional(2), renderCell: ({ tenant }) => <VStack gap={0}>
              <Text>{LICENSE_STATE[tenant.license.state].label}</Text>
              {tenant.license.expires_at && <Text type="supporting">{`${formatDate(tenant.license.expires_at)} хүртэл`}</Text>}
            </VStack> },
          ]} />}
    </Card>
    {creating && <CreateTenantDialog onClose={() => setCreating(false)} onCreated={(tenant, license) => { setCreating(false); if (license?.token) setIssued(license); else navigate(`/platform/tenants/${tenant.id}`) }} />}
    {issued && <LicenseTokenDialog license={issued} onClose={() => { const tenantId = issued.organization_id; setIssued(null); navigate(`/platform/tenants/${tenantId}`) }} />}
  </VStack>
}

type LifecycleAction = { kind: 'suspend' | 'reactivate' | 'terminate' | 'purge' | 'revoke'; license?: ConsoleLicense }

function ConfirmActionDialog({ tenant, action, onClose }: { tenant: ConsoleTenant; action: LifecycleAction; onClose: (done: boolean) => void }) {
  const lifecycle = useTenantLifecycle()
  const purge = usePurgeTenant()
  const revoke = useRevokeLicense()
  const [reason, setReason] = useState('')
  const [confirm, setConfirm] = useState('')
  const needsSlug = action.kind === 'terminate' || action.kind === 'purge'
  const needsReason = action.kind !== 'reactivate' && action.kind !== 'purge'
  const copy = {
    suspend: { title: 'Байгууллагыг түдгэлзүүлэх', body: 'Бүх хэрэглэгчийн хандалт шууд хаагдаж, нэвтрэлтийн сешнүүд цуцлагдана. Өгөгдөл хадгалагдана.', button: 'Түдгэлзүүлэх' },
    reactivate: { title: 'Дахин идэвхжүүлэх', body: 'Хүчинтэй лиценз байвал байгууллага шууд ажиллаж эхэлнэ.', button: 'Идэвхжүүлэх' },
    terminate: { title: 'Байгууллагыг хаах', body: 'Бүх хэрэглэгч идэвхгүй болж, идэвхтэй лиценз цуцлагдана. Өгөгдөл устгагдахгүй (экспорт, хадгалалт).', button: 'Хаах' },
    purge: { title: 'Өгөгдлийг бүрмөсөн устгах', body: 'Энэ байгууллагын БҮХ өгөгдөл буцаах боломжгүйгээр устана.', button: 'Бүрмөсөн устгах' },
    revoke: { title: 'Лиценз цуцлах', body: 'Идэвхтэй лицензийг цуцалбал байгууллага шинэ түлхүүр идэвхжүүлэх хүртэл хаагдана.', button: 'Цуцлах' },
  }[action.kind]
  const submit = async () => {
    try {
      if (action.kind === 'purge') await purge.mutateAsync({ id: tenant.id, confirm_slug: confirm })
      else if (action.kind === 'revoke' && action.license) await revoke.mutateAsync({ id: action.license.id, reason })
      else await lifecycle.mutateAsync({ id: tenant.id, action: action.kind as 'suspend' | 'reactivate' | 'terminate', reason, confirm_slug: confirm })
      toast.success('Хадгалагдлаа')
      onClose(true)
    } catch (error) {
      toast.error(consoleError(error, 'Үйлдэл амжилтгүй'))
    }
  }
  return <Dialog isOpen onOpenChange={(open) => { if (!open) onClose(false) }} width={520} purpose="form">
    <DialogHeader title={copy.title} subtitle={`${tenant.name} (${tenant.slug})`} onOpenChange={(open) => { if (!open) onClose(false) }} />
    <VStack gap={4} padding={4}>
      <Banner status={action.kind === 'reactivate' ? 'info' : 'warning'} collapsible={false} title={copy.body} />
      <FormLayout>
        {needsReason && <TextInput label="Шалтгаан" value={reason} onChange={setReason} isRequired={action.kind !== 'suspend'} />}
        {needsSlug && <TextInput label={`Баталгаажуулахын тулд «${tenant.slug}» гэж бичнэ үү`} value={confirm} onChange={setConfirm} isRequired />}
      </FormLayout>
      <HStack gap={2} hAlign="end"><Button label="Болих" variant="ghost" onClick={() => onClose(false)} />
        <Button label={copy.button} variant="primary" clickAction={submit}
          isDisabled={(needsSlug && confirm.trim() !== tenant.slug) || ((action.kind === 'terminate' || action.kind === 'revoke') && reason.trim().length < 3)} /></HStack>
    </VStack>
  </Dialog>
}

function SubscriptionCard({ tenant, canEdit }: { tenant: ConsoleTenant; canEdit: boolean }) {
  const plans = usePlans()
  const update = useUpdateTenant()
  const [planCode, setPlanCode] = useState<string | null>(tenant.plan_code)
  const [seatLimit, setSeatLimit] = useState<number | null>(tenant.seat_limit)
  const [cycle, setCycle] = useState<BillingCycle>(tenant.billing_cycle)
  const [features, setFeatures] = useState<TenantFeatureCode[]>(tenant.features)
  const [licenseRequired, setLicenseRequired] = useState(tenant.license_required)
  useEffect(() => {
    setPlanCode(tenant.plan_code); setSeatLimit(tenant.seat_limit); setCycle(tenant.billing_cycle); setFeatures(tenant.features); setLicenseRequired(tenant.license_required)
  }, [tenant])
  const save = async () => {
    const payload: { id: number } & Record<string, unknown> = { id: tenant.id, plan_code: planCode, billing_cycle: cycle, features, license_required: licenseRequired }
    if (seatLimit === null) payload.unlimited_seats = true
    else payload.seat_limit = seatLimit
    try {
      await update.mutateAsync(payload)
      toast.success('Багц ба эрх хадгалагдлаа')
    } catch (error) {
      const message = consoleError(error, 'Хадгалж чадсангүй')
      if (message.includes('seats are in use') && window.confirm(`${message}. Одоогийн хэрэглэгчдээс бага хязгаар тогтоох уу? (Шинэ хэрэглэгч нэмэх боломжгүй болно)`)) {
        try { await update.mutateAsync({ ...payload, allow_below_usage: true }); toast.success('Хадгалагдлаа') } catch (retry) { toast.error(consoleError(retry, 'Хадгалж чадсангүй')) }
      } else toast.error(message)
    }
  }
  return <Card padding={5}>
    <VStack gap={4}>
      <VStack gap={1}><Heading level={3}>Багц, квот ба модулиуд</Heading>
        <Text type="supporting">Энд шууд өөрчилсөн квот/модуль дараагийн лиценз идэвхжих хүртэл хүчинтэй. Төлбөртэй өөрчлөлтийг лицензээр олгоно уу.</Text></VStack>
      <FormLayout>
        <Selector label="Багц" value={planCode} onChange={setPlanCode} hasClear isDisabled={!canEdit} options={(plans.data ?? []).map((row) => ({ value: row.code, label: row.name }))} />
        <NumberInput label="Хэрэглэгчийн хязгаар" value={seatLimit} onChange={setSeatLimit} min={0} hasClear isDisabled={!canEdit} description="Хоосон = хязгааргүй" />
        <Selector label="Төлбөрийн мөчлөг" value={cycle} onChange={(value) => setCycle((value ?? 'monthly') as BillingCycle)} isDisabled={!canEdit} options={CYCLES} />
        <CheckboxInput label="Лиценз шаардлагатай" description="Унтраавал лицензгүйгээр ажиллана (зөвхөн дотоод/туршилт)." value={licenseRequired} onChange={setLicenseRequired} isDisabled={!canEdit} />
      </FormLayout>
      <FeatureChecklist value={features} onChange={setFeatures} isDisabled={!canEdit} />
      {canEdit && <HStack hAlign="end"><Button label="Хадгалах" variant="primary" clickAction={save} /></HStack>}
    </VStack>
  </Card>
}

interface LicenseRow extends Record<string, unknown> { id: string; license: ConsoleLicense }

function LicensesCard({ tenant, licenses, canEdit }: { tenant: ConsoleTenant; licenses: ConsoleLicense[]; canEdit: boolean }) {
  const activate = useOperatorActivateLicense()
  const [issuing, setIssuing] = useState<{ renewing?: ConsoleLicense } | null>(null)
  const [shown, setShown] = useState<ConsoleLicense | null>(null)
  const [revoking, setRevoking] = useState<ConsoleLicense | null>(null)
  const show = async (license: ConsoleLicense) => {
    try { setShown(await fetchLicenseToken(license.id)) } catch (error) { toast.error(consoleError(error, 'Түлхүүрийг ачаалж чадсангүй')) }
  }
  const activateNow = async (license: ConsoleLicense) => {
    try { await activate.mutateAsync(license.id); toast.success('Лиценз идэвхжлээ') } catch (error) { toast.error(consoleError(error, 'Идэвхжүүлж чадсангүй')) }
  }
  const rows: LicenseRow[] = licenses.map((license) => ({ id: license.id, license }))
  return <Card padding={5}>
    <VStack gap={3}>
      <HStack gap={2} vAlign="center" hAlign="between">
        <Heading level={3}>Лицензүүд</Heading>
        {canEdit && tenant.status !== 'terminated' && <Button label="Лиценз олгох" variant="secondary" size="sm" icon={<KeyRound size={14} />} onClick={() => setIssuing({})} />}
      </HStack>
      {rows.length === 0 ? <EmptyState title="Лиценз олгоогүй" description="«Лиценз олгох»-оор түлхүүр үүсгэнэ." />
        : <Table<LicenseRow> data={rows} idKey="id" density="compact" columns={[
          { key: 'status', header: 'Төлөв', width: pixel(110), renderCell: ({ license }) => <Token size="sm" color={LICENSE_STATUS[license.status].color} label={LICENSE_STATUS[license.status].label} /> },
          { key: 'seats', header: 'Хэрэглэгч', width: pixel(90), renderCell: ({ license }) => <Text>{String(license.seat_limit)}</Text> },
          { key: 'window', header: 'Хугацаа', width: proportional(2), renderCell: ({ license }) => <Text type="supporting">{`${formatDate(license.valid_from)} – ${formatDate(license.expires_at)}`}</Text> },
          { key: 'modules', header: 'Модуль', width: proportional(2), renderCell: ({ license }) => <Text type="supporting" maxLines={2}>{license.features.join(', ') || '—'}</Text> },
          { key: 'actions', header: '', width: pixel(150), renderCell: ({ license }) => <HStack gap={0.5} hAlign="end">
            <IconButton label="Түлхүүр харах" icon={<Copy size={14} />} size="sm" variant="ghost" onClick={() => { void show(license) }} />
            {canEdit && license.status === 'issued' && <IconButton label="Одоо идэвхжүүлэх" icon={<Play size={14} />} size="sm" variant="ghost" onClick={() => { void activateNow(license) }} />}
            {canEdit && (license.status === 'active' || license.status === 'issued') && <IconButton label="Сунгах / өргөтгөх" icon={<RefreshCw size={14} />} size="sm" variant="ghost" onClick={() => setIssuing({ renewing: license })} />}
            {canEdit && license.status !== 'revoked' && license.status !== 'superseded' && <IconButton label="Цуцлах" icon={<ShieldOff size={14} />} size="sm" variant="ghost" onClick={() => setRevoking(license)} />}
          </HStack> },
        ]} />}
    </VStack>
    {issuing && <IssueLicenseDialog tenant={tenant} renewing={issuing.renewing} onClose={() => setIssuing(null)} onIssued={(license) => { setIssuing(null); setShown(license) }} />}
    {shown && <LicenseTokenDialog license={shown} onClose={() => setShown(null)} />}
    {revoking && <ConfirmActionDialog tenant={tenant} action={{ kind: 'revoke', license: revoking }} onClose={() => setRevoking(null)} />}
  </Card>
}

function domainHint(domain: ConsoleDomain) {
  if (domain.provider === 'cloudflare') {
    if (domain.last_error) return domain.last_error
    const pending = domain.dns_records.filter((record) => record.purpose !== 'routing' || domain.status !== 'active')
    return domain.status === 'active' ? 'Cloudflare · SSL идэвхтэй' : pending.map((record) => `${record.type} ${record.name} → ${record.value}`).join(' · ')
  }
  return `TXT _oyuns.${domain.hostname} = ${domain.verification_token}`
}

function DomainsCard({ tenantId, domains, hosts, canEdit }: { tenantId: number; domains: ConsoleDomain[]; hosts: string[]; canEdit: boolean }) {
  const add = useAddDomain()
  const verify = useVerifyDomain()
  const remove = useRemoveDomain()
  const [hostname, setHostname] = useState('')
  const submit = async () => {
    try {
      const result = await add.mutateAsync({ tenantId, hostname: hostname.trim().toLowerCase() })
      toast.success(result.instructions, { duration: 10_000 })
      setHostname('')
    } catch (error) { toast.error(consoleError(error, 'Домэйн нэмж чадсангүй')) }
  }
  return <Card padding={5}>
    <VStack gap={3}>
      <Heading level={3}>Домэйн</Heading>
      {hosts.map((host) => <HStack key={host} gap={2} vAlign="center"><Text>{host}</Text><Token size="sm" color="gray" label="Subdomain" /></HStack>)}
      {domains.map((domain) => <HStack key={domain.id} gap={2} vAlign="center" hAlign="between" wrap="wrap">
        <VStack gap={0}><Text>{domain.hostname}</Text><Text type="supporting" maxLines={2}>{domainHint(domain)}</Text></VStack>
        <HStack gap={1} vAlign="center">
          {domain.provider === 'cloudflare' && <Token size="sm" color="blue" label="Cloudflare" />}
          <Token size="sm" color={domain.verified_at ? 'green' : domain.status === 'error' ? 'red' : 'orange'} label={domain.verified_at ? 'Баталгаажсан' : domain.status === 'error' ? 'Алдаа' : 'Хүлээгдэж буй'} />
          {canEdit && !domain.verified_at && <Button label={domain.provider === 'cloudflare' ? 'Шалгах' : 'Баталгаажуулах'} size="sm" variant="ghost" clickAction={async () => { try { await verify.mutateAsync({ tenantId, domainId: domain.id }) } catch (error) { toast.error(consoleError(error, 'Амжилтгүй')) } }} />}
          {canEdit && <IconButton label="Устгах" icon={<Trash2 size={14} />} size="sm" variant="ghost" onClick={() => { if (window.confirm(`${domain.hostname} домэйныг салгах уу?`)) remove.mutate({ tenantId, domainId: domain.id }) }} />}
        </HStack>
      </HStack>)}
      {!hosts.length && !domains.length && <Text type="supporting">Домэйн холбоогүй — хэрэглэгчид үндсэн хаягаар нэвтэрнэ.</Text>}
      {canEdit && <HStack gap={2} vAlign="end" wrap="wrap">
        <TextInput label="Өөрийн домэйн" value={hostname} onChange={setHostname} placeholder="erp.company.mn" width={260} />
        <Button label="Нэмэх" variant="secondary" clickAction={submit} isDisabled={!hostname.includes('.')} />
      </HStack>}
    </VStack>
  </Card>
}

export function TenantDetailPage() {
  const { tenantId } = useParams()
  const id = Number(tenantId)
  const navigate = useNavigate()
  const superadmin = useIsSuperadmin()
  const detail = useConsoleTenant(id)
  const [action, setAction] = useState<LifecycleAction | null>(null)
  if (detail.isLoading) return <Skeleton height={320} />
  if (detail.isError || !detail.data) return <Banner status="error" collapsible={false} title={consoleError(detail.error, 'Байгууллага олдсонгүй')} />
  const { tenant, seats, licenses, domains, admins, audit } = detail.data
  const canEdit = superadmin && tenant.status !== 'terminated'
  return <VStack gap={4}>
    <HStack><Button label="Бүх байгууллага" variant="ghost" size="sm" icon={<ArrowLeft size={14} />} href="/platform" as={RouterLink} /></HStack>
    <HStack gap={2} vAlign="center" hAlign="between" wrap="wrap">
      <VStack gap={0}>
        <HStack gap={2} vAlign="center"><Heading level={1}>{tenant.name}</Heading><Token color={TENANT_STATUS[tenant.status].color} label={TENANT_STATUS[tenant.status].label} />{tenant.is_primary && <Token color="purple" label="Үндсэн байгууллага" />}</HStack>
        <Text type="supporting">{`${tenant.slug} · ${tenant.public_id}`}</Text>
      </VStack>
      {superadmin && <HStack gap={2} wrap="wrap">
        {tenant.status === 'suspended' && <Button label="Дахин идэвхжүүлэх" variant="primary" icon={<Play size={14} />} onClick={() => setAction({ kind: 'reactivate' })} />}
        {(tenant.status === 'active' || tenant.status === 'pending_activation') && <Button label="Түдгэлзүүлэх" variant="secondary" icon={<Ban size={14} />} onClick={() => setAction({ kind: 'suspend' })} />}
        {!tenant.is_primary && tenant.status !== 'terminated' && <Button label="Хаах" variant="secondary" icon={<ShieldOff size={14} />} onClick={() => setAction({ kind: 'terminate' })} />}
        {!tenant.is_primary && tenant.status === 'terminated' && <Button label="Бүрмөсөн устгах" variant="secondary" icon={<Trash2 size={14} />} onClick={() => setAction({ kind: 'purge' })} />}
      </HStack>}
    </HStack>
    {tenant.status_reason && <Banner status={tenant.status === 'active' ? 'info' : 'warning'} collapsible={false} title={`Шалтгаан: ${tenant.status_reason}`} />}
    <Grid columns={{ minWidth: 340 }} gap={4}>
      <Card padding={5}>
        <VStack gap={3}>
          <Heading level={3}>Тойм</Heading>
          <MetadataList columns={1}>
            <MetadataListItem label="Хэрэглэгч">{`${seats.used} / ${seats.limit ?? '∞'}`}</MetadataListItem>
            <MetadataListItem label="Лиценз">{`${LICENSE_STATE[tenant.license.state].label}${tenant.license.expires_at ? ` · ${formatDate(tenant.license.expires_at)} хүртэл` : ''}`}</MetadataListItem>
            <MetadataListItem label="Багц">{tenant.plan_code ?? '—'}</MetadataListItem>
            <MetadataListItem label="Холбоо барих">{tenant.contact_email ?? '—'}</MetadataListItem>
            <MetadataListItem label="Үүсгэсэн">{formatDate(tenant.created_at)}</MetadataListItem>
            <MetadataListItem label="Админууд">{admins.map((admin) => `${admin.email}${admin.status !== 'active' ? ` (${admin.status})` : ''}`).join(', ') || '—'}</MetadataListItem>
          </MetadataList>
        </VStack>
      </Card>
      <DomainsCard tenantId={tenant.id} domains={domains} hosts={tenant.hosts} canEdit={canEdit} />
    </Grid>
    <SubscriptionCard tenant={tenant} canEdit={canEdit} />
    <LicensesCard tenant={tenant} licenses={licenses} canEdit={superadmin} />
    <Card padding={5}>
      <VStack gap={2}>
        <Heading level={3}>Сүүлийн үйлдлүүд</Heading>
        {audit.length === 0 ? <Text type="supporting">Бүртгэл алга.</Text> : audit.slice(0, 20).map((event) => <HStack key={event.id} gap={2} hAlign="between" wrap="wrap">
          <Text>{event.action}</Text><Text type="supporting">{`${new Date(event.created_at).toLocaleString('mn-MN')}${event.ip_address ? ` · ${event.ip_address}` : ''}`}</Text>
        </HStack>)}
      </VStack>
    </Card>
    {action && <ConfirmActionDialog tenant={tenant} action={action} onClose={(done) => { setAction(null); if (done && action.kind === 'purge') navigate('/platform') }} />}
  </VStack>
}
