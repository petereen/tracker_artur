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
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import { catalogText, labelOr } from '../utils/labelMap'
import { intlLocale } from '../utils/locale'

// Labels are getters so they follow the UI language when read (the console reuses LICENSE_STATE).
export const LICENSE_STATE: Record<LicenseState, { label: string; variant: 'success' | 'warning' | 'error' | 'neutral' }> = {
  valid: { get label() { return i18n.t('st.lic.state.valid') }, variant: 'success' },
  grace: { get label() { return i18n.t('st.lic.state.grace') }, variant: 'warning' },
  expired: { get label() { return i18n.t('st.lic.state.expired') }, variant: 'error' },
  missing: { get label() { return i18n.t('st.lic.state.missing') }, variant: 'error' },
  not_required: { get label() { return i18n.t('st.lic.state.not_required') }, variant: 'neutral' },
}

const LICENSE_STATUS_COLOR: Record<LicenseRecord['status'], 'green' | 'gray' | 'red' | 'blue'> = { active: 'green', issued: 'blue', superseded: 'gray', revoked: 'red' }

export function formatDate(value: string | null | undefined) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleDateString(intlLocale(), { year: 'numeric', month: '2-digit', day: '2-digit' })
}

/** Seat meter: active users vs the license ceiling. */
export function SeatMeter({ seats }: { seats: SeatUsage }) {
  const { t } = useTranslation()
  if (seats.unlimited || seats.limit === null) {
    return <HStack gap={2} vAlign="center"><Token size="sm" color="gray" label={t('st.lic.unlimited')} /><Text type="supporting">{t('st.lic.activeUsers', { n: seats.used })}</Text></HStack>
  }
  const full = seats.used >= seats.limit
  const nearly = !full && seats.limit > 0 && seats.used / seats.limit >= 0.8
  return <VStack gap={1}>
    <ProgressBar label={t('st.lic.seats')} isLabelHidden value={Math.min(seats.used, seats.limit)} max={Math.max(seats.limit, 1)}
      variant={full ? 'error' : nearly ? 'warning' : 'accent'} hasValueLabel formatValueLabel={() => `${seats.used} / ${seats.limit}`} />
    <Text type="supporting">{full ? t('st.lic.seatsFull') : t('st.lic.freeSeats', { n: seats.available })}</Text>
  </VStack>
}

function LicenseStatusCard({ data }: { data: TenantLicenseOverview }) {
  const { t } = useTranslation()
  const state = LICENSE_STATE[data.license.state]
  return <Card padding={5}>
    <VStack gap={4}>
      <HStack gap={2} vAlign="center" hAlign="between" wrap="wrap">
        <Heading level={3}>{t('st.lic.statusTitle')}</Heading>
        <HStack gap={2} vAlign="center"><StatusDot variant={state.variant} label={state.label} /><Text weight="semibold">{state.label}</Text></HStack>
      </HStack>
      {data.license.state === 'grace' && <Banner status="warning" collapsible={false} title={t('st.lic.graceTitle')}
        description={t('st.lic.graceDesc', { date: formatDate(data.license.grace_ends_at) })} />}
      {(data.license.state === 'missing' || data.license.state === 'expired') && <Banner status="error" collapsible={false} title={t('st.lic.noValidTitle')}
        description={t('st.lic.noValidDesc')} />}
      <MetadataList columns={2}>
        <MetadataListItem label={t('st.lic.org')}>{data.tenant.name}</MetadataListItem>
        <MetadataListItem label={t('st.lic.slug')}>{data.tenant.slug}</MetadataListItem>
        <MetadataListItem label={t('st.lic.plan')}>{data.active?.plan_code ?? data.plan_code ?? '—'}</MetadataListItem>
        <MetadataListItem label={t('st.lic.billingCycle')}>{labelOr('st.lic.cycle', data.active?.billing_cycle ?? data.billing_cycle)}</MetadataListItem>
        <MetadataListItem label={t('st.lic.expires')}>{formatDate(data.license.expires_at)}</MetadataListItem>
        <MetadataListItem label={t('st.lic.daysLeft')}>{data.license.days_left === null ? '—' : String(Math.max(data.license.days_left, 0))}</MetadataListItem>
      </MetadataList>
    </VStack>
  </Card>
}

function ActivationCard() {
  const { t } = useTranslation()
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
      toast.error(tenancyErrorMessage(error, t('st.lic.verifyFailed')))
    }
  }
  const apply = async () => {
    try {
      await activate.mutateAsync(trimmed)
      toast.success(t('st.lic.activated'))
      setToken('')
      setPreview(null)
    } catch (error) {
      toast.error(tenancyErrorMessage(error, t('st.lic.activateFailed')))
    }
  }

  return <Card padding={5}>
    <VStack gap={4}>
      <VStack gap={1}>
        <Heading level={3}>{t('st.lic.activateTitle')}</Heading>
        <Text type="supporting">{t('st.lic.activateHint')}</Text>
      </VStack>
      <TextArea label={t('st.lic.activationKey')} value={token} onChange={(value) => { setToken(value); setPreview(null) }} rows={4}
        placeholder="eyJhbGciOiJFZERTQSIs…" hasSpellCheck={false} />
      {preview && <Banner status={preview.fits_current_usage ? 'success' : 'warning'} collapsible={false}
        title={preview.fits_current_usage ? t('st.lic.keyValid') : t('st.lic.tooManyUsers')}
        description={`${t('st.lic.previewLine', { seats: preview.claims.seats, from: formatDate(preview.claims.valid_from), to: formatDate(preview.claims.expires_at), features: Object.entries(preview.feature_labels).map(([code, label]) => catalogText(`cat.feature.${code}`, label as string)).join(', ') || t('st.lic.baseModules') })}${preview.fits_current_usage ? '' : ` · ${t('st.lic.currentUsers', { used: preview.seats.used })}`}`} />}
      <HStack gap={2} hAlign="end">
        <Button label={t('st.lic.verify')} variant="secondary" icon={<ShieldCheck size={15} />} clickAction={check} isDisabled={!trimmed} />
        <Button label={t('st.lic.activate')} variant="primary" icon={<KeyRound size={15} />} clickAction={apply} isDisabled={!trimmed || (preview !== null && !preview.fits_current_usage)} />
      </HStack>
    </VStack>
  </Card>
}

interface HistoryRow extends Record<string, unknown> { id: string; record: LicenseRecord }

/** Settings → System → Лиценз ба идэвхжүүлэлт (tenant admins). */
export function TenantLicenseSettings() {
  const { t } = useTranslation()
  const overview = useTenantLicense()
  if (overview.isLoading) return <Card padding={5}><Skeleton height={240} /></Card>
  if (overview.isError || !overview.data) return <Banner status="error" collapsible={false} title={tenancyErrorMessage(overview.error, t('st.lic.loadFailed'))} />
  const data = overview.data
  const rows: HistoryRow[] = data.history.map((record) => ({ id: record.id, record }))
  return <VStack gap={4}>
    <Grid columns={{ minWidth: 320 }} gap={4}>
      <LicenseStatusCard data={data} />
      <Card padding={5}>
        <VStack gap={4}>
          <Heading level={3}>{t('st.lic.seats')}</Heading>
          <SeatMeter seats={data.seats} />
          <List hasDividers>
            {data.features.map((feature) => <ListItem key={feature.code} label={catalogText(`cat.feature.${feature.code}`, feature.label)}
              endContent={<Token size="sm" color={feature.enabled ? 'green' : 'gray'} label={feature.enabled ? t('st.lic.included') : t('st.lic.notIncluded')} />} />)}
          </List>
        </VStack>
      </Card>
    </Grid>
    <ActivationCard />
    <Card padding={0}>
      {rows.length === 0 ? <EmptyState title={t('st.lic.historyEmpty')} description={t('st.lic.historyEmptyDesc')} />
        : <Table<HistoryRow> data={rows} idKey="id" density="compact" columns={[
          { key: 'status', header: t('st.lic.col.status'), width: pixel(120), renderCell: ({ record }) => <Token size="sm" color={LICENSE_STATUS_COLOR[record.status]} label={t(`st.lic.status.${record.status}`)} /> },
          { key: 'plan', header: t('st.lic.plan'), width: proportional(1), renderCell: ({ record }) => <Text>{record.plan_code ?? '—'}</Text> },
          { key: 'seats', header: t('st.lic.col.users'), width: pixel(100), renderCell: ({ record }) => <Text>{String(record.seat_limit)}</Text> },
          { key: 'window', header: t('st.lic.col.window'), width: proportional(2), renderCell: ({ record }) => <Text type="supporting">{`${formatDate(record.valid_from)} – ${formatDate(record.expires_at)}`}</Text> },
          { key: 'activated', header: t('st.lic.col.activated'), width: proportional(1), renderCell: ({ record }) => <Text type="supporting">{formatDate(record.activated_at)}</Text> },
        ]} />}
    </Card>
  </VStack>
}
