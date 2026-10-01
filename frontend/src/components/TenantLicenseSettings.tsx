import { useState } from 'react'
import toast from 'react-hot-toast'
import { KeyRound, ShieldCheck } from 'lucide-react'
import { Banner } from '@astryxdesign/core/Banner'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { EmptyState } from '@astryxdesign/core/EmptyState'
import { Grid } from '@astryxdesign/core/Grid'
import { Heading } from '@astryxdesign/core/Heading'
import { HStack } from '@astryxdesign/core/HStack'
import { List, ListItem } from '@astryxdesign/core/List'
import { MetadataList, MetadataListItem } from '@astryxdesign/core/MetadataList'
import { ProgressBar } from '@astryxdesign/core/ProgressBar'
import { Skeleton } from '@astryxdesign/core/Skeleton'
import { StatusDot } from '@astryxdesign/core/StatusDot'
import { Table, pixel, proportional } from '@astryxdesign/core/Table'
import { Text } from '@astryxdesign/core/Text'
import { TextArea } from '@astryxdesign/core/TextArea'
import { Token } from '@astryxdesign/core/Token'
import { VStack } from '@astryxdesign/core/VStack'
import {
  type LicenseRecord, type LicenseState, type LicenseVerification, type SeatUsage, type TenantLicenseOverview,
  tenancyErrorMessage, useActivateLicense, useTenantLicense, useVerifyLicense,
} from '../api/tenancy'

export const LICENSE_STATE: Record<LicenseState, { label: string; variant: 'success' | 'warning' | 'error' | 'neutral' }> = {
  valid: { label: 'Идэвхтэй', variant: 'success' },
  grace: { label: 'Хугацаа дууссан — хөнгөлөлтийн хугацаа', variant: 'warning' },
  expired: { label: 'Хугацаа дууссан', variant: 'error' },
  missing: { label: 'Идэвхжүүлээгүй', variant: 'error' },
  not_required: { label: 'Лиценз шаардлагагүй (үндсэн байгууллага)', variant: 'neutral' },
}

const LICENSE_STATUS_LABEL: Record<LicenseRecord['status'], { label: string; color: 'green' | 'gray' | 'red' | 'blue' }> = {
  active: { label: 'Идэвхтэй', color: 'green' },
  issued: { label: 'Олгосон', color: 'blue' },
  superseded: { label: 'Солигдсон', color: 'gray' },
  revoked: { label: 'Цуцалсан', color: 'red' },
}

const CYCLE_LABEL: Record<string, string> = { monthly: 'Сар бүр', quarterly: 'Улирал бүр', yearly: 'Жил бүр', custom: 'Тусгай' }

export function formatDate(value: string | null | undefined) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleDateString('mn-MN', { year: 'numeric', month: '2-digit', day: '2-digit' })
}

/** Seat meter: active users vs the license ceiling. */
export function SeatMeter({ seats }: { seats: SeatUsage }) {
  if (seats.unlimited || seats.limit === null) {
    return <HStack gap={2} vAlign="center"><Token size="sm" color="gray" label="Хязгааргүй" /><Text type="supporting">{`${seats.used} идэвхтэй хэрэглэгч`}</Text></HStack>
  }
  const full = seats.used >= seats.limit
  const nearly = !full && seats.limit > 0 && seats.used / seats.limit >= 0.8
  return <VStack gap={1}>
    <ProgressBar label="Хэрэглэгчийн эрх" isLabelHidden value={Math.min(seats.used, seats.limit)} max={Math.max(seats.limit, 1)}
      variant={full ? 'error' : nearly ? 'warning' : 'accent'} hasValueLabel formatValueLabel={() => `${seats.used} / ${seats.limit}`} />
    <Text type="supporting">{full ? 'Бүх эрх ашиглагдсан — шинэ нэвтрэх эрх олгох боломжгүй (ажилтан бүртгэх боломжтой).' : `${seats.available} сул эрх үлдсэн.`}</Text>
  </VStack>
}

function LicenseStatusCard({ data }: { data: TenantLicenseOverview }) {
  const state = LICENSE_STATE[data.license.state]
  return <Card padding={5}>
    <VStack gap={4}>
      <HStack gap={2} vAlign="center" hAlign="between" wrap="wrap">
        <Heading level={3}>Лицензийн төлөв</Heading>
        <HStack gap={2} vAlign="center"><StatusDot variant={state.variant} label={state.label} /><Text weight="semibold">{state.label}</Text></HStack>
      </HStack>
      {data.license.state === 'grace' && <Banner status="warning" collapsible={false} title="Лицензийн хугацаа дууссан"
        description={`${formatDate(data.license.grace_ends_at)} хүртэл ажиллана. Үйлчилгээ үзүүлэгчээс сунгалтын түлхүүр авч доор идэвхжүүлнэ үү.`} />}
      {(data.license.state === 'missing' || data.license.state === 'expired') && <Banner status="error" collapsible={false} title="Хүчинтэй лиценз алга"
        description="Лицензийн түлхүүр идэвхжүүлэх хүртэл ажлын орон зайн бусад хэсэг түгжигдсэн байна." />}
      <MetadataList columns={2}>
        <MetadataListItem label="Байгууллага">{data.tenant.name}</MetadataListItem>
        <MetadataListItem label="Хаяг (slug)">{data.tenant.slug}</MetadataListItem>
        <MetadataListItem label="Багц">{data.active?.plan_code ?? data.plan_code ?? '—'}</MetadataListItem>
        <MetadataListItem label="Төлбөрийн мөчлөг">{CYCLE_LABEL[data.active?.billing_cycle ?? data.billing_cycle] ?? data.billing_cycle}</MetadataListItem>
        <MetadataListItem label="Дуусах огноо">{formatDate(data.license.expires_at)}</MetadataListItem>
        <MetadataListItem label="Үлдсэн хоног">{data.license.days_left === null ? '—' : String(Math.max(data.license.days_left, 0))}</MetadataListItem>
      </MetadataList>
    </VStack>
  </Card>
}

function ActivationCard() {
  const verify = useVerifyLicense()
  const activate = useActivateLicense()
  const [token, setToken] = useState('')
  const [preview, setPreview] = useState<LicenseVerification | null>(null)
  const trimmed = token.trim()

  const check = async () => {
    setPreview(null)
    try {
      setPreview(await verify.mutateAsync(trimmed))
    } catch (error) {
      toast.error(tenancyErrorMessage(error, 'Лицензийн түлхүүрийг шалгаж чадсангүй'))
    }
  }
  const apply = async () => {
    try {
      await activate.mutateAsync(trimmed)
      toast.success('Лиценз идэвхжлээ')
      setToken('')
      setPreview(null)
    } catch (error) {
      toast.error(tenancyErrorMessage(error, 'Лиценз идэвхжүүлж чадсангүй'))
    }
  }

  return <Card padding={5}>
    <VStack gap={4}>
      <VStack gap={1}>
        <Heading level={3}>Лиценз идэвхжүүлэх</Heading>
        <Text type="supporting">OYUNS ERP-ээс ирсэн идэвхжүүлэх түлхүүрийг буулгана уу. Гарын үсэг, байгууллага, хугацааг шалгаад дараа нь идэвхжүүлнэ.</Text>
      </VStack>
      <TextArea label="Идэвхжүүлэх түлхүүр" value={token} onChange={(value) => { setToken(value); setPreview(null) }} rows={4}
        placeholder="eyJhbGciOiJFZERTQSIs…" hasSpellCheck={false} />
      {preview && <Banner status={preview.fits_current_usage ? 'success' : 'warning'} collapsible={false}
        title={preview.fits_current_usage ? 'Түлхүүр хүчинтэй' : 'Хэрэглэгчийн тоо лицензээс их байна'}
        description={`${preview.claims.seats} хэрэглэгч · ${formatDate(preview.claims.valid_from)} – ${formatDate(preview.claims.expires_at)} · ${Object.values(preview.feature_labels).join(', ') || 'Суурь модулиуд'}${preview.fits_current_usage ? '' : ` · Одоо ${preview.seats.used} идэвхтэй хэрэглэгч байна.`}`} />}
      <HStack gap={2} hAlign="end">
        <Button label="Шалгах" variant="secondary" icon={<ShieldCheck size={15} />} clickAction={check} isDisabled={!trimmed} />
        <Button label="Идэвхжүүлэх" variant="primary" icon={<KeyRound size={15} />} clickAction={apply} isDisabled={!trimmed || (preview !== null && !preview.fits_current_usage)} />
      </HStack>
    </VStack>
  </Card>
}

interface HistoryRow extends Record<string, unknown> { id: string; record: LicenseRecord }

/** Settings → System → Лиценз ба идэвхжүүлэлт (tenant admins). */
export function TenantLicenseSettings() {
  const overview = useTenantLicense()
  if (overview.isLoading) return <Card padding={5}><Skeleton height={240} /></Card>
  if (overview.isError || !overview.data) return <Banner status="error" collapsible={false} title={tenancyErrorMessage(overview.error, 'Лицензийн мэдээллийг ачаалж чадсангүй')} />
  const data = overview.data
  const rows: HistoryRow[] = data.history.map((record) => ({ id: record.id, record }))
  return <VStack gap={4}>
    <Grid columns={{ minWidth: 320 }} gap={4}>
      <LicenseStatusCard data={data} />
      <Card padding={5}>
        <VStack gap={4}>
          <Heading level={3}>Хэрэглэгчийн эрх</Heading>
          <SeatMeter seats={data.seats} />
          <List hasDividers>
            {data.features.map((feature) => <ListItem key={feature.code} label={feature.label}
              endContent={<Token size="sm" color={feature.enabled ? 'green' : 'gray'} label={feature.enabled ? 'Багцад орсон' : 'Ороогүй'} />} />)}
          </List>
        </VStack>
      </Card>
    </Grid>
    <ActivationCard />
    <Card padding={0}>
      {rows.length === 0 ? <EmptyState title="Лицензийн түүх хоосон" description="Идэвхжүүлсэн лицензүүд энд харагдана." />
        : <Table<HistoryRow> data={rows} idKey="id" density="compact" columns={[
          { key: 'status', header: 'Төлөв', width: pixel(120), renderCell: ({ record }) => <Token size="sm" color={LICENSE_STATUS_LABEL[record.status].color} label={LICENSE_STATUS_LABEL[record.status].label} /> },
          { key: 'plan', header: 'Багц', width: proportional(1), renderCell: ({ record }) => <Text>{record.plan_code ?? '—'}</Text> },
          { key: 'seats', header: 'Хэрэглэгч', width: pixel(100), renderCell: ({ record }) => <Text>{String(record.seat_limit)}</Text> },
          { key: 'window', header: 'Хугацаа', width: proportional(2), renderCell: ({ record }) => <Text type="supporting">{`${formatDate(record.valid_from)} – ${formatDate(record.expires_at)}`}</Text> },
          { key: 'activated', header: 'Идэвхжсэн', width: proportional(1), renderCell: ({ record }) => <Text type="supporting">{formatDate(record.activated_at)}</Text> },
        ]} />}
    </Card>
  </VStack>
}
